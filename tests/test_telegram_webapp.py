"""Безопасная авторизация и HTTP flow Telegram Mini App."""

import hashlib
import hmac
import json
from urllib.parse import urlencode

from api.middleware.telegram_webapp import validate_telegram_init_data


BOT_TOKEN = "123456:test-token"
NOW = 1_800_000_000


def signed_init_data(*, user_id=777, auth_date=NOW, bot_token=BOT_TOKEN, **user_fields):
    user = {"id": user_id, "first_name": "Иван", **user_fields}
    values = {
        "auth_date": str(auth_date),
        "query_id": "query-1",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def create_linked_user(telegram_user_id=777):
    from core.chat_history import get_chat_history

    history = get_chat_history()
    user = history.create_user(
        username="miniapp-user",
        email="miniapp@example.com",
        password_hash="hash",
        role="user",
    )
    link = history.create_telegram_link(user.id)
    history.verify_telegram_link(link["code"], telegram_user_id, "mini_user")
    return user


def test_validate_telegram_init_data_accepts_valid_signature():
    identity = validate_telegram_init_data(
        signed_init_data(username="ivan"), BOT_TOKEN, max_age_seconds=3600, now=NOW
    )
    assert identity.user_id == 777
    assert identity.username == "ivan"
    assert identity.first_name == "Иван"


def test_validate_telegram_init_data_rejects_tampering():
    tampered = signed_init_data().replace("query-1", "query-2")
    try:
        validate_telegram_init_data(tampered, BOT_TOKEN, max_age_seconds=3600, now=NOW)
    except ValueError as exc:
        assert "подпись" in str(exc)
    else:
        raise AssertionError("Поддельная подпись должна отклоняться")


def test_validate_telegram_init_data_rejects_expired_and_future_data():
    for auth_date in (NOW - 3601, NOW + 31):
        try:
            validate_telegram_init_data(
                signed_init_data(auth_date=auth_date), BOT_TOKEN, max_age_seconds=3600, now=NOW
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Некорректная дата должна отклоняться")


def test_telegram_app_page(client):
    rv = client.get("/telegram-app")
    assert rv.status_code == 200
    assert "telegram-web-app.js" in rv.get_data(as_text=True)


def test_webapp_auth_sets_session_for_linked_user(client, monkeypatch):
    user = create_linked_user()
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_WEBAPP_ENABLED", True)
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_WEBAPP_MAX_AGE_SECONDS", 3600)
    monkeypatch.setattr("api.middleware.telegram_webapp.time.time", lambda: NOW)

    rv = client.post("/api/telegram/webapp/auth", json={"init_data": signed_init_data(username="ivan")})

    assert rv.status_code == 200
    assert rv.get_json()["user"]["id"] == user.id
    assert client.get("/api/auth/me").get_json()["authenticated"] is True
    assert client.get("/api/chats").status_code == 200


def test_webapp_auth_rejects_unlinked_user(client, monkeypatch):
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_WEBAPP_ENABLED", True)
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr("api.middleware.telegram_webapp.time.time", lambda: NOW)

    rv = client.post("/api/telegram/webapp/auth", json={"init_data": signed_init_data(user_id=999)})

    assert rv.status_code == 403
    assert rv.get_json()["code"] == "telegram_not_linked"


def test_webapp_auth_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_WEBAPP_ENABLED", True)
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr("api.middleware.telegram_webapp.time.time", lambda: NOW)

    rv = client.post("/api/telegram/webapp/auth", json={"init_data": signed_init_data() + "x"})

    assert rv.status_code == 401
    assert rv.get_json()["code"] == "invalid_init_data"


def test_webapp_session_cannot_read_foreign_chat(client, monkeypatch):
    from core.chat_history import get_chat_history

    linked_user = create_linked_user()
    history = get_chat_history()
    other = history.create_user(
        username="foreign-user",
        email="foreign@example.com",
        password_hash="hash",
        role="user",
    )
    foreign_chat = history.create_session(user_id=other.id, title="Чужой диалог")
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_WEBAPP_ENABLED", True)
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr("api.middleware.telegram_webapp.time.time", lambda: NOW)

    auth = client.post("/api/telegram/webapp/auth", json={"init_data": signed_init_data()})
    denied = client.get(f"/api/chats/{foreign_chat.id}")

    assert auth.status_code == 200
    assert auth.get_json()["user"]["id"] == linked_user.id
    assert denied.status_code == 403


def test_api_key_allows_authenticated_webapp_session(client, monkeypatch):
    create_linked_user()
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_WEBAPP_ENABLED", True)
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr("api.middleware.telegram_webapp.time.time", lambda: NOW)
    monkeypatch.setattr("web_app.settings.API_KEY", "external-api-secret")

    auth = client.post("/api/telegram/webapp/auth", json={"init_data": signed_init_data()})
    chats = client.get("/api/chats")

    assert auth.status_code == 200
    assert chats.status_code == 200


def test_bot_keyboard_includes_webapp_button_when_configured(monkeypatch):
    from scripts.telegram_bot_worker import build_main_keyboard

    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_WEBAPP_ENABLED", True)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_WEBAPP_URL",
        "https://assistant.example.com/telegram-app",
    )

    keyboard = build_main_keyboard()

    assert keyboard["keyboard"][0][0]["web_app"]["url"].endswith("/telegram-app")
