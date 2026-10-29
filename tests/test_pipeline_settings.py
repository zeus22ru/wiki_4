"""Working pipeline settings: access, persistence and actual query generation."""

import json
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

from config import settings
from core.rag import RAGSystem


@pytest.fixture
def pipeline_admin(client, monkeypatch, tmp_path):
    from core.chat_history import get_chat_history

    path = tmp_path / "overrides.json"
    monkeypatch.setenv("SETTINGS_OVERRIDES_PATH", str(path))
    monkeypatch.setattr(settings, "RAG_MULTI_QUERY_COUNT", 3)
    monkeypatch.setattr(settings, "RAG_MULTI_QUERY_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_CHITCHAT_SKIP_RETRIEVAL", True)
    get_chat_history().create_user(
        username="pipeline-admin", email="pipeline@example.invalid",
        password_hash=generate_password_hash("test-password"), role="admin",
    )
    assert client.post("/api/auth/login", json={
        "identifier": "pipeline-admin", "password": "test-password",
    }).status_code == 200
    return client, path


def test_pipeline_count_saved_and_used_by_model(pipeline_admin):
    client, path = pipeline_admin
    response = client.post("/api/admin/settings", json={
        "key": "RAG_MULTI_QUERY_COUNT", "value": 2,
    })
    assert response.status_code == 200
    assert json.loads(path.read_text())["RAG_MULTI_QUERY_COUNT"] == 2
    with patch("core.rag.chat_completion", return_value='["первый", "второй", "третий"]') as model:
        variants = RAGSystem.__new__(RAGSystem)._llm_multi_query_variants("принтер", "принтер")
    assert variants == ["первый", "второй"]
    assert "ровно 2" in model.call_args.args[0]
    schema = client.get("/api/admin/settings/schema").get_json()
    items = {item["key"]: item for group in schema["groups"] for item in group["items"]}
    assert items["RAG_MULTI_QUERY_COUNT"]["value"] == "2"
    assert items["RAG_MULTI_QUERY_COUNT"]["ui"]["max"] == 4
    assert items["RAG_CHITCHAT_SKIP_RETRIEVAL"]["type"] == "bool"


@pytest.mark.parametrize("value", [0, 5, -1, 2.5, True, "not-a-number"])
def test_pipeline_count_rejects_invalid_without_changing_runtime(pipeline_admin, value):
    client, path = pipeline_admin
    response = client.post("/api/admin/settings", json={"key": "RAG_MULTI_QUERY_COUNT", "value": value})
    assert response.status_code == 400
    assert settings.RAG_MULTI_QUERY_COUNT == 3
    assert not path.exists()


def test_pipeline_clear_restores_environment_default(pipeline_admin):
    client, path = pipeline_admin
    assert client.post("/api/admin/settings", json={"key": "RAG_MULTI_QUERY_COUNT", "value": 1}).status_code == 200
    assert settings.RAG_MULTI_QUERY_COUNT == 1
    assert client.post("/api/admin/settings", json={"key": "RAG_MULTI_QUERY_COUNT", "action": "clear"}).status_code == 200
    assert settings.RAG_MULTI_QUERY_COUNT == type(settings).RAG_MULTI_QUERY_COUNT
    assert "RAG_MULTI_QUERY_COUNT" not in json.loads(path.read_text())


def test_failed_persistence_does_not_change_runtime(pipeline_admin):
    client, path = pipeline_admin
    with patch("config.runtime_overrides.save_overrides", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            client.post("/api/admin/settings", json={"key": "RAG_MULTI_QUERY_COUNT", "value": 1})
    assert settings.RAG_MULTI_QUERY_COUNT == 3
    assert not path.exists()


def test_pipeline_settings_require_admin(client, monkeypatch):
    from core.chat_history import get_chat_history

    assert client.get("/api/admin/settings/schema").status_code in {401, 403}
    get_chat_history().create_user(
        username="pipeline-user", email="user@example.invalid",
        password_hash=generate_password_hash("test-password"), role="user",
    )
    client.post("/api/auth/login", json={"identifier": "pipeline-user", "password": "test-password"})
    assert client.get("/api/admin/settings/schema").status_code == 403
    assert client.post("/api/admin/settings", json={"key": "RAG_MULTI_QUERY_COUNT", "value": 1}).status_code == 403


@pytest.mark.parametrize("count", [1, 4])
def test_multi_query_limits_follow_runtime_setting(monkeypatch, count):
    monkeypatch.setattr(settings, "RAG_MULTI_QUERY_COUNT", count)
    with patch("core.rag.chat_completion", return_value='["печать", "принтер", "терминал", "подключение", "настройка"]'):
        assert len(RAGSystem.__new__(RAGSystem)._llm_multi_query_variants("исходный", "исходный")) == count
