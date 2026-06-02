import pytest

from core.rag import (
    RAGResult,
    RAGSystem,
    is_chitchat_query,
    is_off_topic_query,
    should_skip_kb_retrieval,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("как дела", True),
        ("Привет!", True),
        ("здравствуйте", True),
        ("спасибо", True),
        ("привет мир", True),
        ("как дела с остатками на складе", False),
        ("как настроить пользователя в 1с", False),
        ("ошибка при создании ттн", False),
        ("расскажи про контроль остатков в ка", False),
    ],
)
def test_is_chitchat_query(text, expected):
    assert is_chitchat_query(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("каким цветом небо?", True),
        ("какой цвет у неба", True),
        ("что такое любовь", False),
        ("какой цвет индикатора выполненного задания в диадок", False),
        ("каким цветом подсвечивается статус отгрузки", False),
    ],
)
def test_is_off_topic_query(text, expected):
    assert is_off_topic_query(text) is expected


def test_should_skip_kb_retrieval_combines_chitchat_and_off_topic():
    assert should_skip_kb_retrieval("привет") is True
    assert should_skip_kb_retrieval("каким цветом небо?") is True
    assert should_skip_kb_retrieval("как настроить егаис") is False


def test_query_skips_retrieval_for_chitchat(monkeypatch):
    rag = RAGSystem.__new__(RAGSystem)

    def fail_retrieve(*_a, **_kw):
        raise AssertionError("retrieve_documents_auto must not be called for chitchat")

    monkeypatch.setattr(rag, "retrieve_documents_auto", fail_retrieve)
    monkeypatch.setattr(
        rag,
        "_answer_chitchat",
        lambda q, h, kind="chitchat": RAGResult(
            answer="Здравствуйте! Задайте вопрос по документации.",
            citations=[],
            sources=[],
            diagnostics={"retrieval_status": kind},
        ),
    )

    result = rag.query("как дела")
    assert "документации" in result.answer
    assert result.diagnostics.get("retrieval_status") == "chitchat"


def test_query_skips_retrieval_for_off_topic(monkeypatch):
    rag = RAGSystem.__new__(RAGSystem)

    def fail_retrieve(*_a, **_kw):
        raise AssertionError("retrieve_documents_auto must not be called for off_topic")

    monkeypatch.setattr(rag, "retrieve_documents_auto", fail_retrieve)
    monkeypatch.setattr(
        rag,
        "_answer_chitchat",
        lambda q, h, kind="chitchat": RAGResult(
            answer="Я помогаю по wiki 1С. Задайте рабочий вопрос.",
            citations=[],
            sources=[],
            diagnostics={"retrieval_status": kind},
        ),
    )

    result = rag.query("каким цветом небо?")
    assert result.diagnostics.get("retrieval_status") == "off_topic"
