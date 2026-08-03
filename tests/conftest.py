"""Общие pytest fixtures."""

import pytest


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
