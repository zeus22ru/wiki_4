"""Тесты HTTP API без реальных Ollama/Chroma."""

from unittest.mock import MagicMock, patch

import pytest

from core.rag import Citation, RAGResult


@pytest.fixture
def client():
    from web_app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_health_ok(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    mock_init.return_value = (MagicMock(), MagicMock())
    rv = client.get("/api/health")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ollama"] is True
    assert body["database"] is True
    assert body["rag"] is True
    assert body["status"] == "ok"


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_rag_success(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(
        answer="Ответ",
        citations=[
            Citation(
                text="цит",
                source="src",
                chunk_id="c1",
                score=0.91,
                metadata={"path": "/a"},
            )
        ],
        sources=[
            {
                "title": "T",
                "path": "/doc",
                "relevance": 0.91,
                "score": 0.91,
                "source": "s",
                "chunk_id": "c1",
                "text": "x",
            }
        ],
    )
    rv = client.post("/api/chat", json={"message": "привет мир"})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["answer"] == "Ответ"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "T"
    assert data["sources"][0]["path"] == "/doc"
    assert data["citations"][0]["text"] == "цит"
    rag.query.assert_called_once()
    assert rag.query.call_args[0][0] == "привет мир"


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_embedding_unavailable(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(
        answer="Нет эмбеддинга",
        citations=[],
        sources=[],
        retrieve_error="embedding_unavailable",
    )
    rv = client.post("/api/chat", json={"message": "вопрос тут"})
    assert rv.status_code == 200
    assert rv.get_json()["sources"] == []


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_search_error(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(
        answer="err",
        citations=[],
        sources=[],
        retrieve_error="search_error",
    )
    rv = client.post("/api/chat", json={"message": "вопрос тут"})
    assert rv.status_code == 500


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_stream_success(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.retrieve_documents.return_value = (
        [{"text": "x", "score": 1.0, "metadata": {}, "chunk_id": "c1"}],
        None,
    )
    rag.stream_rag_answer.side_effect = lambda *a, **kw: iter(
        [
            {"type": "delta", "text": "Часть"},
            {
                "type": "done",
                "rag_result": RAGResult(
                    answer="Полный ответ",
                    citations=[],
                    sources=[
                        {
                            "title": "T",
                            "path": "/doc",
                            "relevance": 0.91,
                            "score": 0.91,
                            "source": "s",
                            "chunk_id": "c1",
                            "text": "x",
                        }
                    ],
                ),
            },
        ]
    )
    rv = client.post("/api/chat/stream", json={"message": "привет мир"})
    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    assert "Часть" in text
    assert "Полный ответ" in text
    rag.retrieve_documents.assert_called_once()
    rag.stream_rag_answer.assert_called_once()


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_stream_search_error(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.retrieve_documents.return_value = ([], "search_error")
    rv = client.post("/api/chat/stream", json={"message": "вопрос тут"})
    assert rv.status_code == 500
    rag.stream_rag_answer.assert_not_called()
