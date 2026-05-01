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
    assert "conversation_history" in rag.query.call_args.kwargs


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
    rag.build_retrieval_query.return_value = "привет мир"
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
    assert "Ищу релевантные документы" in text
    assert "Документы найдены" in text
    assert "Часть" in text
    assert "Полный ответ" in text
    rag.build_retrieval_query.assert_called_once()
    rag.retrieve_documents.assert_called_once()
    assert rag.retrieve_documents.call_args[0][0] == "привет мир"
    rag.stream_rag_answer.assert_called_once()
    assert "conversation_history" in rag.stream_rag_answer.call_args.kwargs


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_stream_search_error(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.build_retrieval_query.return_value = "вопрос тут"
    rag.retrieve_documents.return_value = ([], "search_error")
    rv = client.post("/api/chat/stream", json={"message": "вопрос тут"})
    assert rv.status_code == 200
    assert "Ошибка поиска" in rv.get_data(as_text=True)
    rag.build_retrieval_query.assert_called_once()
    rag.stream_rag_answer.assert_not_called()


def test_api_documents_open_serves_file_inside_data_dir(client, tmp_path, monkeypatch):
    doc = tmp_path / "source.txt"
    doc.write_text("source content", encoding="utf-8")
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))

    rv = client.get("/api/documents/open?path=source.txt")

    assert rv.status_code == 200
    assert rv.get_data(as_text=True) == "source content"


def test_api_documents_open_rejects_path_outside_data_dir(client, tmp_path, monkeypatch):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))

    rv = client.get(f"/api/documents/open?path={outside}")

    assert rv.status_code == 404
