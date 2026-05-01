"""Тесты HTTP API без реальных Ollama/Chroma."""

import io
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import generate_password_hash

from core.rag import Citation, RAGResult


def login_admin(client):
    from core.chat_history import get_chat_history

    get_chat_history().create_user(
        username="admin",
        email="admin@example.com",
        password_hash=generate_password_hash("password123"),
        role="admin",
    )
    rv = client.post("/api/auth/login", json={"identifier": "admin", "password": "password123"})
    assert rv.status_code == 200


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
def test_api_chat_employee_instruction_mode(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="Инструкция", citations=[], sources=[])

    rv = client.post("/api/chat", json={
        "message": "настрой принтер",
        "answer_mode": "employee_instruction",
    })

    assert rv.status_code == 200
    assert rag.query.call_args.kwargs["answer_mode"] == "employee_instruction"


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


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_verify_answer(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    rag.verify_answer_against_sources.return_value = {
        "status": "confirmed",
        "summary": "Ответ подтвержден",
        "details": [],
        "source_count": 1,
        "citation_count": 1,
    }
    mock_init.return_value = (MagicMock(), rag)

    rv = client.post("/api/chat/verify", json={
        "answer": "Ответ",
        "sources": [{"title": "T"}],
        "citations": [{"text": "Ответ", "source": "T"}],
    })

    assert rv.status_code == 200
    assert rv.get_json()["verification"]["status"] == "confirmed"
    rag.verify_answer_against_sources.assert_called_once()


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_suggestions(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    rag.suggest_followup_questions.return_value = ["Что проверить дальше?"]
    mock_init.return_value = (MagicMock(), rag)

    rv = client.post("/api/chat/suggestions", json={
        "answer": "Ответ",
        "sources": [{"title": "T"}],
        "citations": [{"text": "Ответ", "source": "T"}],
    })

    assert rv.status_code == 200
    assert rv.get_json()["suggestions"] == ["Что проверить дальше?"]
    rag.suggest_followup_questions.assert_called_once()


def test_api_documents_preview_txt(client, tmp_path, monkeypatch):
    login_admin(client)
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("api.routes.documents.settings.UPLOAD_DIR", str(tmp_path / "uploads"))

    rv = client.post(
        "/api/documents/preview",
        data={"file": (io.BytesIO(("Заголовок\n" + "Полезный текст. " * 80).encode("utf-8")), "source.txt")},
        content_type="multipart/form-data",
    )

    assert rv.status_code == 200
    preview = rv.get_json()["preview"]
    assert preview["filename"] == "source.txt"
    assert preview["supported"] is True
    assert preview["chunk_count"] >= 1
    assert preview["chunks"]


def test_api_documents_preview_diff_existing_txt(client, tmp_path, monkeypatch):
    login_admin(client)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    existing = uploads / "source.txt"
    existing.write_text("Старая инструкция\nШаг один\n", encoding="utf-8")
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("api.routes.documents.settings.UPLOAD_DIR", str(uploads))

    rv = client.post(
        "/api/documents/preview",
        data={"file": (io.BytesIO("Новая инструкция\nШаг два\n".encode("utf-8")), "source.txt")},
        content_type="multipart/form-data",
    )

    assert rv.status_code == 200
    diff = rv.get_json()["preview"]["version_diff"]
    assert diff["existing_path"] == "uploads/source.txt"
    assert diff["changed"] is True
    assert diff["added"]


def test_api_documents_related_uses_only_data_dir(client, tmp_path, monkeypatch):
    login_admin(client)
    base = tmp_path / "wiki" / "printer"
    base.mkdir(parents=True)
    (base / "setup.txt").write_text("setup", encoding="utf-8")
    (base / "errors.txt").write_text("errors", encoding="utf-8")
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))

    rv = client.post("/api/documents/related", json={
        "sources": [{"path": "wiki/printer/setup.txt", "title": "Настройка принтера"}],
    })

    assert rv.status_code == 200
    docs = rv.get_json()["documents"]
    assert docs
    assert docs[0]["path"] == "wiki/printer/errors.txt"


@patch("api.routes.admin._chroma_status")
@patch("api.routes.admin.fetch_remote_model_ids")
@patch("api.routes.admin.inference_server_reachable")
@patch("api.routes.admin.get_chat_history")
def test_api_admin_overview_quality(mock_history, mock_reachable, mock_models, mock_chroma, client):
    login_admin(client)
    history = MagicMock()
    history.get_session_count.return_value = 2
    history.get_total_message_count.return_value = 7
    history.get_feedback_summary.return_value = {"up": 3, "down": 1, "total": 4}
    history.get_feedback.return_value = []
    history.get_top_sources.return_value = [{"title": "Doc", "path": "doc.txt", "count": 2}]
    history.get_negative_feedback_context.return_value = []
    history.get_source_feedback.return_value = [{"title": "Bad", "path": "bad.txt", "negative_count": 1}]
    history.get_weak_answers.return_value = [{"question": "?", "reason": "Ответ без источников"}]
    history.get_knowledge_gaps.return_value = [{"topic": "printer", "count": 1, "reason": "Ответ без источников"}]
    mock_history.return_value = history
    mock_reachable.return_value = True
    mock_models.return_value = []
    mock_chroma.return_value = {"ok": True, "collection": "test", "count": 5}

    rv = client.get("/api/admin/overview")

    assert rv.status_code == 200
    body = rv.get_json()
    assert body["usage"]["message_count"] == 7
    assert body["quality"]["feedback"]["down"] == 1
    assert body["quality"]["top_sources"][0]["title"] == "Doc"
    assert body["quality"]["negative_sources"][0]["title"] == "Bad"
    assert body["quality"]["weak_answers"][0]["reason"] == "Ответ без источников"
    assert body["quality"]["knowledge_gaps"][0]["topic"] == "printer"
    assert body["quality"]["risks"]


def test_api_chats_delete_all(client):
    rv = client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    user_id = rv.get_json()["user"]["id"]
    manager = MagicMock()
    manager.delete_all_sessions.return_value = 3

    with patch("api.routes.chat.get_chat_history", return_value=manager):
        rv = client.delete("/api/chats")

    assert rv.status_code == 200
    assert rv.get_json() == {"success": True, "deleted": 3}
    manager.delete_all_sessions.assert_called_once_with(user_id=user_id)


def test_api_documents_open_serves_file_inside_data_dir(client, tmp_path, monkeypatch):
    login_admin(client)
    doc = tmp_path / "source.txt"
    doc.write_text("source content", encoding="utf-8")
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))

    rv = client.get("/api/documents/open?path=source.txt")

    assert rv.status_code == 200
    assert rv.get_data(as_text=True) == "source content"


def test_api_documents_open_rejects_path_outside_data_dir(client, tmp_path, monkeypatch):
    login_admin(client)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))

    rv = client.get(f"/api/documents/open?path={outside}")

    assert rv.status_code == 404
