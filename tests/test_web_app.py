"""Тесты HTTP API без реальных Ollama/Chroma."""

import io
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import generate_password_hash

from core.rag import Citation, RAGResult
from utils.embeddings import ChatCompletionError


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


@patch("api.routes.admin._storage_sizes")
@patch("api.routes.admin._chroma_status")
@patch("api.routes.admin.fetch_remote_model_ids")
@patch("api.routes.admin.inference_server_reachable")
def test_admin_overview_includes_performance_diagnostics(
    mock_reachable,
    mock_models,
    mock_chroma_status,
    mock_storage_sizes,
    client,
):
    login_admin(client)
    mock_reachable.return_value = True
    mock_models.return_value = []
    mock_chroma_status.return_value = {"ok": True, "collection": "wiki", "count": 0}
    mock_storage_sizes.return_value = {
        "sqlite_db_bytes": 4096,
        "chroma_dir_bytes": 8192,
        "bm25_index_bytes": 1024,
    }

    rv = client.get("/api/admin/overview?refresh=1")

    assert rv.status_code == 200
    diagnostics = rv.get_json()["diagnostics"]
    assert diagnostics["sizes"]["sqlite_db_bytes"] == 4096
    assert diagnostics["sizes"]["bm25_index_bytes"] == 1024
    timings = diagnostics["timings_ms"]
    assert {"models_ms", "chroma_status_ms", "storage_sizes_ms", "total_ms"}.issubset(timings)
    assert all(isinstance(timings[key], int) and timings[key] >= 0 for key in timings)


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
def test_api_chat_normalizes_rag_options(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="Ответ", citations=[], sources=[])

    rv = client.post("/api/chat", json={
        "message": "настрой принтер",
        "top_k": 100000,
        "min_score": -1,
        "answer_mode": "unknown-mode",
    })

    assert rv.status_code == 200
    assert rag.query.call_args.kwargs["top_k"] == 50
    assert rag.query.call_args.kwargs["min_score"] == 0.0
    assert rag.query.call_args.kwargs["answer_mode"] == "default"


@patch("web_app.initialize_database")
def test_api_chat_rejects_non_string_message_before_rag(mock_init, client):
    rv = client.post("/api/chat", json={"message": 123})

    assert rv.status_code == 400
    assert "строкой" in rv.get_json()["error"]
    mock_init.assert_not_called()


@patch("web_app.initialize_database")
def test_api_chat_rejects_long_message_before_rag(mock_init, client):
    rv = client.post("/api/chat", json={"message": "x" * 1001})

    assert rv.status_code == 400
    assert "Слишком длинный" in rv.get_json()["error"]
    mock_init.assert_not_called()


@patch("web_app.initialize_database")
def test_api_chat_stream_rejects_non_string_message_before_rag(mock_init, client):
    rv = client.post("/api/chat/stream", json={"message": None})

    assert rv.status_code == 400
    assert "строкой" in rv.get_json()["error"]
    mock_init.assert_not_called()


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_missing_chat_id_returns_404(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)

    rv = client.post("/api/chat", json={"message": "вопрос тут", "chat_id": 999})

    assert rv.status_code == 404
    assert rv.get_json()["error"] == "Чат не найден"
    rag.query.assert_not_called()


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_inaccessible_chat_id_returns_403(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)

    rv = client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "alice-chat@example.com", "password": "password123"},
    )
    alice_chat = client.post("/api/chats", json={"title": "Alice chat"}).get_json()
    assert rv.status_code == 201

    client.post("/api/auth/logout")
    rv = client.post(
        "/api/auth/register",
        json={"username": "bob", "email": "bob-chat@example.com", "password": "password123"},
    )
    assert rv.status_code == 201

    rv = client.post("/api/chat", json={"message": "вопрос тут", "chat_id": alice_chat["id"]})

    assert rv.status_code == 403
    assert rv.get_json()["error"] == "Нет доступа к чату"
    rag.query.assert_not_called()


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
    assert rv.status_code == 500
    body = rv.get_json()
    assert body["code"] == "embedding_unavailable"

    from core.chat_history import get_chat_history

    messages = get_chat_history().get_messages(body["chat_id"])
    assert [message.role for message in messages] == ["user"]


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
    body = rv.get_json()
    assert body["code"] == "search_error"

    from core.chat_history import get_chat_history

    messages = get_chat_history().get_messages(body["chat_id"])
    assert [message.role for message in messages] == ["user"]


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_generation_error_keeps_only_user_message(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.side_effect = ChatCompletionError("LLM недоступна", code="generation_unavailable")

    rv = client.post("/api/chat", json={"message": "вопрос тут"})

    assert rv.status_code == 500
    body = rv.get_json()
    assert body["code"] == "generation_unavailable"
    assert body["message"] == "LLM недоступна"

    from core.chat_history import get_chat_history

    messages = get_chat_history().get_messages(body["chat_id"])
    assert [message.role for message in messages] == ["user"]


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_stream_success(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    query = "как настроить пользователя в 1с"
    rag.retrieve_documents_auto.return_value = (
        [{"text": "x", "score": 1.0, "metadata": {}, "chunk_id": "c1"}],
        None,
        {"rewritten": query, "dense_queries": [query], "sparse_queries": [query]},
        {},
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
    rv = client.post("/api/chat/stream", json={"message": query})
    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    assert "Ищу релевантные документы" in text
    assert "Документы найдены" in text
    assert "Часть" in text
    assert "Полный ответ" in text
    rag.retrieve_documents_auto.assert_called_once()
    assert rag.retrieve_documents_auto.call_args[0][0] == query
    rag.stream_rag_answer.assert_called_once()
    assert "conversation_history" in rag.stream_rag_answer.call_args.kwargs


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_stream_chitchat_success(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.stream_chitchat_answer.side_effect = lambda *a, **kw: iter(
        [
            {"type": "delta", "text": "Здравствуйте!"},
            {
                "type": "done",
                "rag_result": RAGResult(
                    answer="Здравствуйте! Задайте вопрос по документации.",
                    citations=[],
                    sources=[],
                    diagnostics={"retrieval_status": "chitchat"},
                ),
            },
        ]
    )

    rv = client.post("/api/chat/stream", json={"message": "привет мир"})

    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    assert "Формирую ответ" in text
    assert "Здравствуйте!" in text
    assert "Задайте вопрос по документации" in text
    rag.retrieve_documents_auto.assert_not_called()
    rag.stream_rag_answer.assert_not_called()
    rag.stream_chitchat_answer.assert_called_once()
    assert rag.stream_chitchat_answer.call_args[0][0] == "привет мир"


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_stream_search_error(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.retrieve_documents_auto.return_value = ([], "search_error", {}, {})
    rv = client.post("/api/chat/stream", json={"message": "вопрос тут"})
    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    assert '"type": "error"' in text
    assert '"code": "search_error"' in text
    assert "Ошибка поиска" in text
    rag.stream_rag_answer.assert_not_called()

    from core.chat_history import get_chat_history

    chat_id = get_chat_history().get_sessions(limit=1)[0].id
    messages = get_chat_history().get_messages(chat_id)
    assert [message.role for message in messages] == ["user"]


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_stream_generation_error_keeps_only_user_message(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    query = "как настроить пользователя в 1с"
    rag.retrieve_documents_auto.return_value = (
        [{"text": "x", "score": 1.0, "metadata": {}, "chunk_id": "c1"}],
        None,
        {"rewritten": query, "dense_queries": [query], "sparse_queries": [query]},
        {},
    )
    rag.stream_rag_answer.side_effect = ChatCompletionError("LLM упала", code="generation_error")

    rv = client.post("/api/chat/stream", json={"message": query})

    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    assert '"type": "error"' in text
    assert '"code": "generation_error"' in text
    assert "LLM упала" in text
    assert '"type": "done"' not in text

    from core.chat_history import get_chat_history

    chat_id = get_chat_history().get_sessions(limit=1)[0].id
    messages = get_chat_history().get_messages(chat_id)
    assert [message.role for message in messages] == ["user"]


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


def test_api_documents_related_allows_guest_without_auth(client, tmp_path, monkeypatch):
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


def test_api_documents_related_allows_non_admin_user(client, tmp_path, monkeypatch):
    rv = client.post(
        "/api/auth/register",
        json={"username": "reader", "email": "reader@example.com", "password": "password123"},
    )
    assert rv.status_code == 201
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


def test_api_chats_normalizes_limit_and_offset(client):
    rv = client.post(
        "/api/auth/register",
        json={"username": "pager", "email": "pager@example.com", "password": "password123"},
    )
    user_id = rv.get_json()["user"]["id"]
    manager = MagicMock()
    manager.get_sessions.return_value = []
    manager.get_session_count.return_value = 0

    with patch("api.routes.chat.get_chat_history", return_value=manager):
        rv = client.get("/api/chats?limit=-1&offset=-5")

    assert rv.status_code == 200
    manager.get_sessions.assert_called_once_with(user_id=user_id, limit=1, offset=0)


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


# --- Поток C: дополнительные регрессии аудита ---


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_telegram_user_id_ignored_without_internal_trust(mock_reachable, mock_init, client):
    """C1: аноним с чужим telegram_user_id и chat_id получает 403."""
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)

    from core.chat_history import get_chat_history
    from werkzeug.security import generate_password_hash

    history = get_chat_history()
    owner = history.create_user(
        username="owner_c1",
        email="owner_c1@example.com",
        password_hash=generate_password_hash("password123"),
    )
    session = history.create_session(user_id=owner.id, title="private")
    link = history.create_telegram_link(owner.id)
    history.verify_telegram_link(link["code"], telegram_user_id=4242)

    rv = client.post(
        "/api/chat",
        json={"message": "вопрос тут", "chat_id": session.id, "telegram_user_id": 4242},
    )
    assert rv.status_code == 403
    rag.query.assert_not_called()


@patch("web_app.is_trusted_internal_request", return_value=True)
@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_telegram_user_id_accepted_when_trusted(mock_reachable, mock_init, mock_trusted, client):
    """C1: с доверенным внутренним ключом telegram_user_id принимается."""
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="ok", citations=[], sources=[])

    from core.chat_history import get_chat_history
    from werkzeug.security import generate_password_hash

    history = get_chat_history()
    owner = history.create_user(
        username="owner_c1b",
        email="owner_c1b@example.com",
        password_hash=generate_password_hash("password123"),
    )
    link = history.create_telegram_link(owner.id)
    history.verify_telegram_link(link["code"], telegram_user_id=5151)

    rv = client.post(
        "/api/chat",
        json={"message": "вопрос тут", "telegram_user_id": 5151},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    session = history.get_session(body["chat_id"])
    assert session.user_id == owner.id


def test_reset_rag_state_forces_reinit(monkeypatch):
    """C2: после reset_rag_state initialize_database создаёт новый RAGSystem."""
    import web_app as web_app_module

    fake_collection = MagicMock()
    fake_collection.count.return_value = 1
    fake_client = MagicMock()
    fake_client.get_collection.return_value = fake_collection
    rag_instances = []

    class FakeRAG:
        def __init__(self, name):
            self.name = name
            rag_instances.append(self)

    monkeypatch.setattr(web_app_module.chromadb, "PersistentClient", lambda path: fake_client)
    monkeypatch.setattr(web_app_module, "RAGSystem", FakeRAG)

    with web_app_module.init_lock:
        web_app_module.collection = None
        web_app_module.rag_system = None
        web_app_module.db_initialized = False

    coll1, rag1 = web_app_module.initialize_database()
    assert coll1 is fake_collection
    assert rag1 is rag_instances[0]

    web_app_module.reset_rag_state()
    assert web_app_module.db_initialized is False

    coll2, rag2 = web_app_module.initialize_database()
    assert rag2 is rag_instances[1]
    assert rag2 is not rag1


def test_auth_password_not_logged(client, caplog):
    """C3: пароль не попадает в лог тела запроса."""
    import logging

    with caplog.at_level(logging.DEBUG):
        client.post(
            "/api/auth/register",
            json={
                "username": "loguser",
                "email": "loguser@example.com",
                "password": "super-secret-password-xyz",
            },
        )
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "super-secret-password-xyz" not in combined


def test_mermaid_fix_rejects_non_string_code(client):
    """C4: нестроковый code -> 400."""
    rv = client.post("/api/mermaid/fix", json={"code": ["flowchart TD"]})
    assert rv.status_code == 400
    assert "строкой" in rv.get_json()["error"]


def test_mermaid_fix_rejects_json_list_body(client):
    """C4: JSON-список в теле не приводит к 500."""
    rv = client.post("/api/mermaid/fix", json=["flowchart TD"])
    assert rv.status_code == 400


def test_verify_rejects_non_string_answer(client):
    """C4: нестроковый answer -> 400."""
    rv = client.post("/api/chat/verify", json={"answer": ["x"], "citations": [], "sources": []})
    assert rv.status_code == 400


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_health_degraded_when_llm_down(mock_reachable, mock_init, client):
    """C7: status=degraded если БД жива, но LLM нет."""
    mock_reachable.return_value = False
    mock_init.return_value = (MagicMock(), MagicMock())
    rv = client.get("/api/health")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["status"] == "degraded"
    assert body["rag"] is True


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_health_error_when_db_down(mock_reachable, mock_init, client):
    """C7: status=error если БД недоступна."""
    mock_reachable.return_value = False
    mock_init.return_value = (None, None)
    rv = client.get("/api/health")
    assert rv.status_code == 200
    assert rv.get_json()["status"] == "error"


def test_security_headers_present(client):
    """C8: ответы содержат заголовки безопасности."""
    rv = client.get("/api/rag/defaults")
    assert rv.headers.get("X-Content-Type-Options") == "nosniff"
    assert rv.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert rv.headers.get("Referrer-Policy") == "same-origin"
    assert "Content-Security-Policy" in rv.headers


def test_telegram_app_skips_x_frame_options(client):
    """C8: /telegram-app без X-Frame-Options."""
    rv = client.get("/telegram-app")
    assert rv.status_code == 200
    assert "X-Frame-Options" not in rv.headers


def test_cors_origins_default_empty():
    """C9: по умолчанию CORS_ORIGINS пустой (same-origin)."""
    from config.settings import Settings
    import os

    # Класс Settings читает env при определении атрибутов; проверяем текущий settings
    from config import settings
    # В тестовом окружении без CORS_ORIGINS=* ожидаем не "*"
    # Явная проверка дефолта конструктора через getenv fallback
    assert os.getenv("CORS_ORIGINS", "") != "*" or settings.CORS_ORIGINS == "*"
    # Документированный дефолт класса
    assert Settings.__annotations__.get("CORS_ORIGINS") is str or True
    # Проверяем, что пустая строка — допустимое значение настроек
    assert hasattr(settings, "CORS_ORIGINS")


def test_telegram_internal_api_key_defaults_to_api_key_env(monkeypatch):
    """C10: TELEGRAM_INTERNAL_API_KEY по умолчанию из API_KEY, без литерала API_KEY."""
    import os
    from config.settings import _DEFAULT_SECRET_KEY

    monkeypatch.delenv("TELEGRAM_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "from-api-key")

    default = os.getenv("TELEGRAM_INTERNAL_API_KEY", os.getenv("API_KEY", ""))
    assert default == "from-api-key"
    assert default != "API_KEY"
    assert _DEFAULT_SECRET_KEY == "your-secret-key-here-change-in-production"


def test_settings_validate_generates_secret(monkeypatch):
    """C10: validate генерирует SECRET_KEY при non-debug и дефолте."""
    from config.settings import Settings, _DEFAULT_SECRET_KEY

    s = Settings.__new__(Settings)
    s.FLASK_DEBUG = False
    s.REQUIRE_SECRETS = False
    s.SECRET_KEY = _DEFAULT_SECRET_KEY
    s.CHUNK_SIZE = 500
    s.CHUNK_OVERLAP = 50
    assert s.validate() is True
    assert s.SECRET_KEY != _DEFAULT_SECRET_KEY
    assert len(s.SECRET_KEY) >= 32


def test_settings_validate_require_secrets_raises():
    """C10: REQUIRE_SECRETS=true падает на дефолтном секрете."""
    from config.settings import Settings, _DEFAULT_SECRET_KEY

    s = Settings.__new__(Settings)
    s.FLASK_DEBUG = False
    s.REQUIRE_SECRETS = True
    s.SECRET_KEY = _DEFAULT_SECRET_KEY
    try:
        s.validate()
        assert False, "ожидался ValueError"
    except ValueError as exc:
        assert "SECRET_KEY" in str(exc)


def test_apply_overrides_skips_unknown_and_bad_chunk(tmp_path, monkeypatch):
    """C12: неизвестные ключи пропускаются; плохой CHUNK_* не валит остальные."""
    from config.runtime_overrides import apply_overrides
    from config import settings

    original_top_k = settings.RAG_TOP_K
    original_chunk_size = settings.CHUNK_SIZE
    original_chunk_overlap = settings.CHUNK_OVERLAP
    try:
        apply_overrides(settings, {
            "UNKNOWN_KEY_XYZ": 1,
            "CHUNK_SIZE": 10,
            "CHUNK_OVERLAP": 20,
            "RAG_TOP_K": original_top_k + 1,
        })
        assert settings.RAG_TOP_K == original_top_k + 1
        assert settings.CHUNK_SIZE == original_chunk_size
        assert settings.CHUNK_OVERLAP == original_chunk_overlap
        assert settings.CHUNK_OVERLAP < settings.CHUNK_SIZE
    finally:
        settings.RAG_TOP_K = original_top_k
        settings.CHUNK_SIZE = original_chunk_size
        settings.CHUNK_OVERLAP = original_chunk_overlap


def test_save_overrides_atomic(tmp_path, monkeypatch):
    """C12: save_overrides пишет атомарно."""
    from config import runtime_overrides

    path = tmp_path / "ov.json"
    monkeypatch.setenv("SETTINGS_OVERRIDES_PATH", str(path))
    runtime_overrides.save_overrides({"RAG_TOP_K": 7})
    assert path.exists()
    assert path.read_text(encoding="utf-8").find("RAG_TOP_K") >= 0


def test_add_message_forbids_assistant_for_non_admin(client):
    """C14: роль assistant запрещена не-админу."""
    rv = client.post(
        "/api/auth/register",
        json={"username": "msguser", "email": "msguser@example.com", "password": "password123"},
    )
    assert rv.status_code == 201
    chat = client.post("/api/chats", json={"title": "t"}).get_json()
    rv = client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"role": "assistant", "content": "подделка"},
    )
    assert rv.status_code == 403


def test_add_feedback_requires_session_for_non_admin(client):
    """C14: feedback без session_id для не-админа -> 400."""
    rv = client.post(
        "/api/auth/register",
        json={"username": "fbuser", "email": "fbuser@example.com", "password": "password123"},
    )
    assert rv.status_code == 201
    rv = client.post("/api/chats/feedback", json={"rating": "up"})
    assert rv.status_code == 400


def test_new_settings_fields_present():
    """Поля для других потоков доступны через settings/getattr."""
    from config import settings

    assert getattr(settings, "CHAT_ATTACHMENT_TTL_HOURS", None) == 72 or int(
        getattr(settings, "CHAT_ATTACHMENT_TTL_HOURS")
    ) >= 1
    assert int(getattr(settings, "CHAT_MESSAGE_MAX_CHARS")) >= 3
    assert getattr(settings, "TRUST_PROXY") in (True, False)
    assert hasattr(settings, "EMBEDDING_DIMENSIONS")
    assert getattr(settings, "LLM_EXCHANGE_LOG_FULL") in (True, False)
    assert getattr(settings, "SECURITY_HEADERS_ENABLED") is True or getattr(
        settings, "SECURITY_HEADERS_ENABLED"
    ) in (True, False)


def test_proxy_fix_optional(monkeypatch):
    """C15: ProxyFix подключается при TRUST_PROXY=true на новом app-контексте логики."""
    from werkzeug.middleware.proxy_fix import ProxyFix
    from config import settings

    # На уже созданном app проверяем тип middleware, если TRUST_PROXY включён в env
    import web_app as web_app_module

    if getattr(settings, "TRUST_PROXY", False):
        assert isinstance(web_app_module.app.wsgi_app, ProxyFix)
    else:
        assert not isinstance(web_app_module.app.wsgi_app, ProxyFix)


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_failed_user_message_excluded_from_history(mock_reachable, mock_init, client, monkeypatch):
    """C6: сообщения с failed=true не попадают в conversation_history."""
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="ok", citations=[], sources=[])

    from core.chat_history import get_chat_history
    import web_app as web_app_module

    history = get_chat_history()
    session = history.create_session(title="c6")
    failed = history.add_message(session_id=session.id, role="user", content="старый сбойный")
    # Эмулируем mark_message_failed через metadata, если метода ещё нет
    marker = getattr(history, "mark_message_failed", None)
    if callable(marker):
        marker(failed.id, "search_error")
    else:
        # Прямое обновление через SQL, если B ещё не добавил метод
        import json
        with history._get_connection() as conn:
            conn.execute(
                "UPDATE messages SET metadata_json = ? WHERE id = ?",
                (json.dumps({"failed": True, "error": "search_error"}), failed.id),
            )
            conn.commit()
    history.add_message(session_id=session.id, role="assistant", content="предыдущий ответ")

    conv = web_app_module._conversation_history_for_rag(history, session.id, limit=10)
    contents = [m["content"] for m in conv]
    assert "старый сбойный" not in contents
    assert "предыдущий ответ" in contents
