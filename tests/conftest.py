"""Общие pytest fixtures."""

import pytest


# Дефолты инференса «как без .env», чтобы тесты не зависели от локального .env
# (в нём могут быть заданы облачные провайдеры, раздельные URL/ключи и т.п.).
_INFERENCE_DEFAULTS = {
    "INFERENCE_BACKEND": "",
    "EMBEDDING_API_MODE": "ollama",
    "CHAT_API_MODE": "ollama",
    "OLLAMA_URL": "http://localhost:11434",
    "EMBEDDING_BASE_URL": "",
    "CHAT_BASE_URL": "",
    "OPENAI_API_KEY": "",
    "EMBEDDING_API_KEY": "",
    "CHAT_API_KEY": "",
    "OLLAMA_EMBEDDING_MODEL": "bge-m3",
    "OLLAMA_CHAT_MODEL": "qwen2.5:7b",
    "CHAT_DISABLE_THINKING": True,
    "EMBEDDING_DIMENSIONS": None,
}


@pytest.fixture(autouse=True)
def reset_inference_settings(monkeypatch):
    """Изолировать тесты от настроек инференса из локального .env."""
    from config import settings

    for key, value in _INFERENCE_DEFAULTS.items():
        monkeypatch.setattr(settings, key, value, raising=False)
    yield


@pytest.fixture(autouse=True)
def isolated_database(request, tmp_path, monkeypatch):
    """Каждый тест получает отдельную SQLite-базу приложения.

    Static DOM/CSS contract tests do not need the app database.
    """
    if request.node.get_closest_marker("no_db") or request.fspath.basename == "test_frontend_contract.py":
        yield
        return

    from config import settings
    import core.chat_history as chat_history

    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "wiki_qa_test.db"))
    chat_history._chat_history_manager = None
    yield
    chat_history._chat_history_manager = None


@pytest.fixture
def client():
    from web_app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
