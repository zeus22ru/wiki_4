from unittest.mock import patch

from config.chat_runtime import resolve_chat_rag_options, rag_chat_defaults


@patch("config.chat_runtime.settings")
def test_rag_chat_defaults_reads_runtime_settings(mock_settings):
    mock_settings.RAG_TOP_K = 10
    mock_settings.RAG_MIN_SCORE = 0.38
    mock_settings.RAG_MAX_CITATIONS = 7
    mock_settings.RAG_MAX_CONTEXT_LENGTH = 90000
    mock_settings.RAG_QUERY_EXPANSION_MAX_MESSAGES = 8
    mock_settings.DEEP_RETRIEVAL_ENABLED = True
    mock_settings.RETRIEVAL_MODE = "hybrid"
    mock_settings.RERANK_ENABLED = False

    defaults = rag_chat_defaults()
    assert defaults["top_k"] == 10
    assert defaults["min_score"] == 0.38
    assert defaults["max_citations"] == 7
    assert defaults["query_expansion_max_messages"] == 8
    assert defaults["deep_retrieval_enabled"] is True


@patch("config.chat_runtime.settings")
def test_resolve_chat_rag_options_uses_admin_defaults_when_missing(mock_settings):
    mock_settings.RAG_TOP_K = 10
    mock_settings.RAG_MIN_SCORE = 0.38
    mock_settings.RAG_MAX_CITATIONS = 7
    mock_settings.RAG_MAX_CONTEXT_LENGTH = 90000
    mock_settings.RAG_QUERY_EXPANSION_MAX_MESSAGES = 8
    mock_settings.DEEP_RETRIEVAL_ENABLED = True
    mock_settings.RETRIEVAL_MODE = "hybrid"
    mock_settings.RERANK_ENABLED = False

    options = resolve_chat_rag_options({"message": "test"})
    assert options["top_k"] == 10
    assert options["min_score"] == 0.38
    assert options["answer_mode"] == "default"


@patch("config.chat_runtime.settings")
def test_resolve_chat_rag_options_keeps_explicit_overrides(mock_settings):
    mock_settings.RAG_TOP_K = 10
    mock_settings.RAG_MIN_SCORE = 0.38
    mock_settings.RAG_MAX_CITATIONS = 7
    mock_settings.RAG_MAX_CONTEXT_LENGTH = 90000
    mock_settings.RAG_QUERY_EXPANSION_MAX_MESSAGES = 8
    mock_settings.DEEP_RETRIEVAL_ENABLED = True
    mock_settings.RETRIEVAL_MODE = "hybrid"
    mock_settings.RERANK_ENABLED = False

    options = resolve_chat_rag_options({"top_k": 3, "min_score": 0.5, "answer_mode": "brief"})
    assert options["top_k"] == 3
    assert options["min_score"] == 0.5
    assert options["answer_mode"] == "brief"


@patch("config.chat_runtime.settings")
def test_resolve_chat_rag_options_clamps_request_values(mock_settings):
    mock_settings.RAG_TOP_K = 10
    mock_settings.RAG_MIN_SCORE = 0.38
    mock_settings.RAG_MAX_CITATIONS = 7
    mock_settings.RAG_MAX_CONTEXT_LENGTH = 90000
    mock_settings.RAG_QUERY_EXPANSION_MAX_MESSAGES = 8
    mock_settings.DEEP_RETRIEVAL_ENABLED = True
    mock_settings.RETRIEVAL_MODE = "hybrid"
    mock_settings.RERANK_ENABLED = False

    high = resolve_chat_rag_options({"top_k": 100000, "min_score": 2})
    low = resolve_chat_rag_options({"top_k": -1, "min_score": -1})

    assert high["top_k"] == 50
    assert high["min_score"] == 1.0
    assert low["top_k"] == 1
    assert low["min_score"] == 0.0


@patch("config.chat_runtime.settings")
def test_resolve_chat_rag_options_defaults_unknown_answer_mode(mock_settings):
    mock_settings.RAG_TOP_K = 10
    mock_settings.RAG_MIN_SCORE = 0.38
    mock_settings.RAG_MAX_CITATIONS = 7
    mock_settings.RAG_MAX_CONTEXT_LENGTH = 90000
    mock_settings.RAG_QUERY_EXPANSION_MAX_MESSAGES = 8
    mock_settings.DEEP_RETRIEVAL_ENABLED = True
    mock_settings.RETRIEVAL_MODE = "hybrid"
    mock_settings.RERANK_ENABLED = False

    options = resolve_chat_rag_options({"answer_mode": "surprise"})

    assert options["answer_mode"] == "default"
