"""Тесты GitHub Issues API (заглушка и валидация)."""

from unittest.mock import patch

import pytest

from api.routes import issues as issues_route
from integrations.github_issues import IssueCreateResult, create_github_issue


@pytest.fixture
def client():
    from web_app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["guest_id"] = "guest-test-001"
        yield c


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    issues_route._rate_limiter.reset()
    yield
    issues_route._rate_limiter.reset()


def test_issue_status_stub_mode(client):
    rv = client.get("/api/issues/status")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["enabled"] is True
    assert body["stub"] is True
    assert body["configured"] is False
    assert len(body["types"]) >= 1


def test_create_issue_stub(client):
    rv = client.post(
        "/api/issues",
        json={
            "type": "bug",
            "title": "Кнопка не работает",
            "description": "После обновления страницы кнопка отправки не реагирует.",
        },
    )
    assert rv.status_code == 201
    body = rv.get_json()
    assert body["stub"] is True
    assert body["issue_number"] >= 1
    assert "github.com" in body["html_url"]


def test_create_issue_validation(client):
    rv = client.post(
        "/api/issues",
        json={"type": "bug", "title": "x", "description": "short"},
    )
    assert rv.status_code == 400


def test_create_issue_honeypot(client):
    rv = client.post(
        "/api/issues",
        json={
            "type": "bug",
            "title": "Спам",
            "description": "Это сообщение должно быть отклонено фильтром.",
            "_gotcha": "http://spam.example",
        },
    )
    assert rv.status_code == 400


def test_create_issue_rate_limit(client):
    payload = {
        "type": "idea",
        "title": "Предложение",
        "description": "Добавить экспорт диалога в PDF для отчётности.",
    }
    for _ in range(3):
        rv = client.post("/api/issues", json=payload)
        assert rv.status_code == 201
    rv = client.post("/api/issues", json=payload)
    assert rv.status_code == 429


@patch("api.routes.issues.create_github_issue")
def test_create_issue_github_mode(mock_create, client):
    mock_create.return_value = IssueCreateResult(
        number=7,
        html_url="https://github.com/org/repo/issues/7",
        stub=False,
    )
    with patch("api.routes.issues.github_issues_configured", return_value=True):
        with patch("api.routes.issues.settings.GITHUB_TOKEN", "token"):
            with patch("api.routes.issues.settings.GITHUB_REPO", "org/repo"):
                rv = client.post(
                    "/api/issues",
                    json={
                        "type": "wrong_answer",
                        "title": "Неверный ответ",
                        "description": "Ассистент указал неверный срок отпуска в ответе.",
                    },
                )
    assert rv.status_code == 201
    body = rv.get_json()
    assert body["stub"] is False
    assert body["issue_number"] == 7
    mock_create.assert_called_once()


def test_create_github_issue_stub_unit():
    result = create_github_issue(
        title="Test",
        body="Body",
        token="",
        repo="",
    )
    assert result.stub is True
    assert result.number >= 1
    assert "github.com/stub/repo/issues/" in result.html_url

    second = create_github_issue(
        title="Test 2",
        body="Body",
        token="",
        repo="org/wiki-feedback",
    )
    assert second.stub is True
    assert second.number > result.number
    assert "org/wiki-feedback" in second.html_url


def test_issue_status_caches_probe(client, monkeypatch):
    calls = {"n": 0}

    def fake_probe(token, repo):
        calls["n"] += 1
        return {"writable": False, "hint": "secret github detail XYZ"}

    monkeypatch.setattr("api.routes.issues.github_issues_configured", lambda *a, **k: True)
    monkeypatch.setattr("api.routes.issues.settings.GITHUB_ISSUES_ENABLED", True)
    monkeypatch.setattr("api.routes.issues.settings.GITHUB_TOKEN", "token")
    monkeypatch.setattr("api.routes.issues.settings.GITHUB_REPO", "org/repo")
    monkeypatch.setattr("api.routes.issues.probe_github_issue_write_access", fake_probe)
    issues_route._status_probe_cache["ts"] = 0.0
    issues_route._status_probe_cache["data"] = None

    rv1 = client.get("/api/issues/status")
    rv2 = client.get("/api/issues/status")
    assert rv1.status_code == 200
    assert rv2.status_code == 200
    assert calls["n"] == 1
    assert "XYZ" not in (rv1.get_json().get("write_hint") or "")


def test_issue_rate_limit_uses_ip_only(client, monkeypatch):
    monkeypatch.setattr("api.routes.issues.settings.TRUST_PROXY", False)
    payload = {
        "type": "idea",
        "title": "Предложение",
        "description": "Добавить экспорт диалога в PDF для отчётности.",
    }
    for _ in range(3):
        assert client.post("/api/issues", json=payload).status_code == 201

    # Другой guest_id, тот же IP — всё равно 429
    with client.session_transaction() as sess:
        sess["guest_id"] = "another-guest"
    assert client.post("/api/issues", json=payload).status_code == 429


def test_issue_rate_limit_trusts_forwarded_for(client, monkeypatch):
    monkeypatch.setattr("api.routes.issues.settings.TRUST_PROXY", True)
    issues_route._rate_limiter.reset()
    payload = {
        "type": "idea",
        "title": "Предложение",
        "description": "Добавить экспорт диалога в PDF для отчётности.",
    }
    for _ in range(3):
        rv = client.post(
            "/api/issues",
            json=payload,
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        assert rv.status_code == 201
    assert client.post(
        "/api/issues",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.10"},
    ).status_code == 429
    # Другой forwarded IP проходит
    assert client.post(
        "/api/issues",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.11"},
    ).status_code == 201


def test_create_issue_hides_github_error(client, monkeypatch):
    from integrations.github_issues import GitHubIssuesError

    monkeypatch.setattr("api.routes.issues.github_issues_configured", lambda *a, **k: True)
    monkeypatch.setattr("api.routes.issues.settings.GITHUB_TOKEN", "token")
    monkeypatch.setattr("api.routes.issues.settings.GITHUB_REPO", "org/repo")

    def boom(*a, **k):
        raise GitHubIssuesError("token invalid detailed")

    monkeypatch.setattr("api.routes.issues.create_github_issue", boom)
    rv = client.post(
        "/api/issues",
        json={
            "type": "bug",
            "title": "Ошибка",
            "description": "Подробное описание проблемы для теста.",
        },
    )
    assert rv.status_code == 502
    assert "token invalid" not in rv.get_json()["error"]
