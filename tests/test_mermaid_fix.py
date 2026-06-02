from core.rag import _coerce_mermaid_code, _normalize_mermaid_code, looks_like_mermaid, fix_mermaid_block_code


def test_coerce_strips_preamble_before_flowchart():
    raw = "Описание:\nflowchart TD\nA --> B"
    coerced = _coerce_mermaid_code(raw)
    assert coerced.startswith("flowchart TD")
    assert looks_like_mermaid(raw)


def test_normalize_unescapes_llm_quotes():
    raw = 'flowchart TD\nsubgraph Prep[\\"Label\\"]\nA --> B'
    norm = _normalize_mermaid_code(raw)
    assert '\\"' not in norm
    assert 'Prep["Label"]' in norm


def test_fix_mermaid_block_code_without_llm(monkeypatch):
    monkeypatch.setattr("core.rag.settings.MERMAID_AUTOFIX_ENABLED", False)
    raw = 'flowchart TD\nsubgraph Prep[\\"X\\"]\nA --> B'
    fixed = fix_mermaid_block_code(raw)
    assert fixed.startswith("flowchart TD")
    assert '\\"' not in fixed


def test_quote_labels_with_parentheses_after_br():
    raw = (
        "flowchart TD\n"
        "A[Выбрать шаблон прав<br/>(по аналогии)] --> B\n"
        "C{Определить роль<br/>вариант} --> D"
    )
    fixed = _normalize_mermaid_code(raw)
    assert '["Выбрать шаблон прав<br/>(по аналогии)"]' in fixed
    assert '{"Определить роль<br/>вариант"}' in fixed


def test_fix_russian_style_directive():
    raw = "flowchart TD\nA-->B\nстиль A fill:#f9f,stroke:#333"
    fixed = _normalize_mermaid_code(raw)
    assert "style A fill:#f9f" in fixed
    assert "стиль" not in fixed.lower()


def test_fix_real_failing_diagram_from_log():
    from pathlib import Path

    sample = Path("_test_mmd.txt")
    if not sample.is_file():
        return
    raw = sample.read_text(encoding="utf-8")
    fixed = _normalize_mermaid_code(raw)
    assert "style A fill" in fixed
    assert "стиль" not in fixed.lower()
