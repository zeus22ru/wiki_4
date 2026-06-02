"""Тесты отсечения reasoning/thinking из ответа чата."""

from utils.embeddings import strip_model_reasoning

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
