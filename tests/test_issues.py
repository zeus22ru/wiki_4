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
