from core.rag import Citation, RAGSystem


def test_format_answer_uses_readable_source_without_chunk_id():
    rag = RAGSystem.__new__(RAGSystem)
    citation = Citation(
        text="Фрагмент",
        source="Документ базы знаний",
        chunk_id="60cb49a3e0344a924885b27a0607a6f2",
        score=0.4458,
        metadata={"title": "Документ базы знаний"},
    )

    answer = rag.format_answer_with_citations("Ответ", [citation], max_citations=1)

    assert "Документ базы знаний" in answer
    assert "60cb49a3e0344a924885b27a0607a6f2" not in answer


def test_enrich_answer_falls_back_to_title_when_source_missing():
    rag = RAGSystem.__new__(RAGSystem)
    result = rag.enrich_answer_with_citations(
        "Ответ содержит достаточно длинный фрагмент из документа.",
        [
            {
                "text": "Ответ содержит достаточно длинный фрагмент из документа.",
                "score": 0.91,
                "metadata": {"title": "Название документа", "path": "folder/doc.pdf"},
                "chunk_id": "chunk-1",
            }
        ],
        max_citations=1,
    )

    assert "Неизвестный источник" not in result.answer
    assert "Название документа" in result.answer
    assert result.sources[0]["source"] == "Название документа"


def test_generate_prompt_includes_conversation_history():
    rag = RAGSystem.__new__(RAGSystem)

    prompt = rag.generate_rag_prompt(
        "А второй пункт?",
        [{"text": "Документ описывает второй пункт.", "metadata": {"title": "Регламент"}}],
        max_context_length=1000,
        conversation_history=[
            {"role": "user", "content": "Какие есть пункты регламента?"},
            {"role": "assistant", "content": "1. Первый пункт. 2. Второй пункт."},
        ],
        retrieval_query="Какие есть пункты регламента? А второй пункт?",
    )

    assert "ИСТОРИЯ ДИАЛОГА" in prompt
    assert "Пользователь: Какие есть пункты регламента?" in prompt
    assert "Ассистент: 1. Первый пункт. 2. Второй пункт." in prompt
    assert "ПОИСКОВЫЙ ЗАПРОС" in prompt
    assert "факты бери из контекста источников" in prompt


def test_build_retrieval_query_uses_recent_history():
    rag = RAGSystem.__new__(RAGSystem)

    query = rag.build_retrieval_query(
        "А второй пункт?",
        [{"role": "user", "content": "Расскажи про регламент"}],
    )

    assert "История диалога" in query
    assert "Расскажи про регламент" in query
    assert "Текущий вопрос" in query
    assert "А второй пункт?" in query
