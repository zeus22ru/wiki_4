"""Тесты новых продуктовых API без реальных Ollama/Chroma."""

from io import BytesIO
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

from core.chat_history import ChatHistoryManager


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


def test_chat_history_stores_citations_and_feedback(tmp_path):
    history = ChatHistoryManager(str(tmp_path / "history.db"))
    session = history.create_session(title="Тест")
    message = history.add_message(
        session_id=session.id,
        role="assistant",
        content="Ответ",
        sources=[{"title": "Док"}],
        citations=[{"text": "цитата"}],
        metadata={"latency_ms": 12},
    )

    messages = history.get_messages(session.id)
    assert messages[0].sources[0]["title"] == "Док"
    assert messages[0].citations[0]["text"] == "цитата"
    assert messages[0].metadata["latency_ms"] == 12

    feedback = history.add_feedback(session.id, message.id, "up")
    assert feedback["rating"] == "up"
    assert history.get_feedback()[0]["message_id"] == message.id


def test_documents_upload_and_list(client, tmp_path, monkeypatch):
    from config import settings

    login_admin(client)
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))

    rv = client.post(
        "/api/documents/upload",
        data={"file": (BytesIO(b"hello"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 201
    assert rv.get_json()["document"]["filename"] == "note.txt"

    rv = client.get("/api/documents")
    assert rv.status_code == 200
    assert rv.get_json()["documents"][0]["filename"] == "note.txt"


@patch("api.routes.admin.fetch_remote_model_ids")
@patch("api.routes.admin.inference_server_reachable")
@patch("api.routes.admin.chromadb.PersistentClient")
def test_admin_overview(mock_client, mock_reachable, mock_models, client):
    login_admin(client)
    mock_reachable.return_value = True
    mock_models.return_value = ["bge-m3", "qwen2.5:7b"]
    collection = MagicMock()
    collection.count.return_value = 7
    mock_client.return_value.get_collection.return_value = collection

    rv = client.get("/api/admin/overview")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["health"]["llm"] is True
    assert data["health"]["chroma"]["count"] == 7
    assert "settings" in data


def test_optional_api_key_blocks_api_when_enabled(client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "API_KEY", "secret")
    rv = client.get("/api/health")
    assert rv.status_code == 401

    rv = client.get("/api/health", headers={"X-API-Key": "secret"})
    assert rv.status_code in {200, 500}
