from core.rag import _merge_mermaid_from_raw


def test_merge_mermaid_from_raw_when_stripped_answer_lost_fence():
    raw = (
        "The user wants a diagram.\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        "    A[Начало] --> B[Конец]\n"
        "```"
    )
    stripped = "A[Начало] --> B[Конец]\n```"
    merged = _merge_mermaid_from_raw(raw, stripped)
    assert "```mermaid" in merged.lower()
    assert "flowchart TD" in merged
    assert "A[Начало]" in merged
