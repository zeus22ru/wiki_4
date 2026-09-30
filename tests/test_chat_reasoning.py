"""Тесты отсечения reasoning/thinking из ответа чата."""

from utils.embeddings import strip_model_reasoning, _filter_reasoning_stream

_OPEN_THINK = "<" + "think" + ">"
_CLOSE_THINK = "</" + "think" + ">"


def test_strip_think_tags():
    raw = f"{_OPEN_THINK}internal monologue{_CLOSE_THINK}\n\n# Заголовок\n\nТекст ответа."
    assert strip_model_reasoning(raw).startswith("# Заголовок")


def test_strip_english_cot_before_russian():
    raw = (
        'The user is asking "How to configure egais?"\n'
        "Let's draft the response in Russian.\n\n\n"
        "# Настройка ЕГАИС\n\nШаг 1."
    )
    out = strip_model_reasoning(raw)
    assert out.startswith("# Настройка")
    assert "The user is asking" not in out


def test_strip_leaves_clean_answer_unchanged():
    answer = "## Ответ\n\nКраткая инструкция для сотрудника."
    assert strip_model_reasoning(answer) == answer


def test_strip_preserves_1c_upp_instruction():
    """Ответ, начинающийся с цифры/латиницы без CoT, не обрезается."""
    answer = "1С:УПП — откройте раздел «Склад».\nЗатем нажмите Создать."
    assert strip_model_reasoning(answer) == answer


def test_strip_preserves_egais_latin_prefix():
    answer = "EGAIS-статусы:\n\nОтправка идёт через УТМ."
    assert strip_model_reasoning(answer) == answer


def test_strip_preserves_json_array():
    raw = '["вопрос один", "вопрос два", "вопрос три"]'
    assert strip_model_reasoning(raw) == raw


def test_strip_preserves_mermaid_fence():
    raw = (
        "```mermaid\n"
        "flowchart TD\n"
        "    A[Начало] --> B[Конец]\n"
        "```"
    )
    out = strip_model_reasoning(raw)
    assert out.startswith("```mermaid")
    assert "flowchart TD" in out
    assert "A[Начало]" in out


def test_strip_preserves_mermaid_after_english_cot():
    raw = (
        'The user wants a diagram.\n\n'
        "```mermaid\n"
        "flowchart TD\n"
        "    A[Начало] --> B[Конец]\n"
        "```"
    )
    out = strip_model_reasoning(raw)
    assert "```mermaid" in out.lower()
    assert "flowchart TD" in out
    assert "A[Начало]" in out


def test_filter_reasoning_stream_waits_for_cyrillic_on_cot():
    chunks = [
        "The user is asking about EGAIS.\n\n",
        "Ответ по-русски: откройте УТМ.",
    ]
    out = "".join(_filter_reasoning_stream(iter(chunks)))
    assert "The user is asking" not in out
    assert "Ответ по-русски" in out


def test_filter_reasoning_stream_emits_latin_without_cot():
    chunks = ["EGAIS-статусы:\n\n", "Отправка идёт через УТМ."]
    out = "".join(_filter_reasoning_stream(iter(chunks)))
    assert out.startswith("EGAIS")
    assert "УТМ" in out
