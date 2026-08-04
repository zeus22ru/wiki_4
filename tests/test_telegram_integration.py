"""Тесты интеграции Telegram-бота wiki_4 без реальных вызовов API."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import generate_password_hash

from core.rag import RAGResult
from integrations.telegram import (
    TelegramClient,
    escape_html,
    markdown_to_telegram_html,
    split_markdown_for_telegram,
    strip_markdown_light,
)
from scripts.telegram_bot_worker import (
    BUTTON_MODE,
    build_main_keyboard,
    build_mode_inline_keyboard,
    collect_image_attachment_ids,
    handle_question,
    load_offset,
    make_rich_draft_id,
    message_has_image,
    message_question_text,
    normalize_user_input,
    parse_command,
    primary_image_file_id,
    save_offset,
    upload_chat_attachment,
)


def _create_test_user():
    """Создать тестового пользователя с ролью user."""
    from core.chat_history import get_chat_history

    return get_chat_history().create_user(
        username="telegramuser",
        email="tg@example.com",
        password_hash=generate_password_hash("password123"),
        role="user",
    )


# ============== TelegramClient ==============


def test_telegram_client_get_updates(monkeypatch):
    calls = []

    def mock_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": dict(params or {})})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": [{"update_id": 1}]}
        return response

    monkeypatch.setattr("integrations.telegram.requests.get", mock_get)

    client = TelegramClient(bot_token="test-token")
    updates = client.get_updates(offset=42, limit=10, timeout=5)

    assert len(updates) == 1
    assert updates[0]["update_id"] == 1
    assert len(calls) == 1
    assert "/bot" in calls[0]["url"]
    assert "/getUpdates" in calls[0]["url"]
    assert calls[0]["params"]["offset"] == 42
    assert calls[0]["params"]["limit"] == 10
    assert calls[0]["params"]["timeout"] == 5


def test_telegram_client_send_message(monkeypatch):
    calls = []

    def mock_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": dict(json or {})})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": {"message_id": 123}}
        return response

    monkeypatch.setattr("integrations.telegram.requests.post", mock_post)

    client = TelegramClient(bot_token="test-token")
    result = client.send_message(chat_id=987, text="Hello <b>world</b>")

    assert result["result"]["message_id"] == 123
    assert len(calls) == 1
    assert "/bot" in calls[0]["url"]
    assert "/sendMessage" in calls[0]["url"]
    assert calls[0]["payload"]["chat_id"] == 987
    assert calls[0]["payload"]["parse_mode"] == "HTML"
    assert calls[0]["payload"]["text"] == "Hello &lt;b&gt;world&lt;/b&gt;"
    assert calls[0]["payload"]["disable_web_page_preview"] is True


def test_telegram_client_send_message_with_reply_markup(monkeypatch):
    calls = []

    def mock_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": dict(json or {})})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": {"message_id": 123}}
        return response

    monkeypatch.setattr("integrations.telegram.requests.post", mock_post)

    keyboard = {"keyboard": [[{"text": "Test"}]]}
    client = TelegramClient(bot_token="test-token")
    client.send_message(chat_id=1, text="Hi", reply_markup=keyboard)

    assert calls[0]["payload"]["reply_markup"] == keyboard


def test_telegram_client_answer_callback_query(monkeypatch):
    calls = []

    def mock_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": dict(json or {})})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": True}
        return response

    monkeypatch.setattr("integrations.telegram.requests.post", mock_post)

    client = TelegramClient(bot_token="test-token")
    client.answer_callback_query("cb-1", text="Готово")

    assert "/answerCallbackQuery" in calls[0]["url"]
    assert calls[0]["payload"]["callback_query_id"] == "cb-1"
    assert calls[0]["payload"]["text"] == "Готово"


def test_telegram_client_edit_message_text(monkeypatch):
    calls = []

    def mock_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": dict(json or {})})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": {"message_id": 123}}
        return response

    monkeypatch.setattr("integrations.telegram.requests.post", mock_post)

    client = TelegramClient(bot_token="test-token")
    result = client.edit_message_text(chat_id=987, message_id=123, text="Updated text")

    assert len(calls) == 1
    assert "/bot" in calls[0]["url"]
    assert "/editMessageText" in calls[0]["url"]
    assert calls[0]["payload"]["chat_id"] == 987
    assert calls[0]["payload"]["message_id"] == 123
    assert calls[0]["payload"]["text"] == "Updated text"
    assert calls[0]["payload"]["parse_mode"] == "HTML"


def test_telegram_client_formatted_html_not_escaped(monkeypatch):
    calls = []

    def mock_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": dict(json or {})})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        return response

    monkeypatch.setattr("integrations.telegram.requests.post", mock_post)

    client = TelegramClient(bot_token="test-token")
    client.send_message(chat_id=1, text="<b>жирный</b>", formatted=True)

    assert calls[0]["payload"]["text"] == "<b>жирный</b>"


def test_markdown_to_telegram_html():
    assert markdown_to_telegram_html("**жирный** текст") == "<b>жирный</b> текст"
    assert markdown_to_telegram_html("### Заголовок") == "<b>Заголовок</b>"
    assert markdown_to_telegram_html("код `foo`") == "код <code>foo</code>"
    assert markdown_to_telegram_html("```\nline1\nline2\n```") == "<pre>line1\nline2</pre>"
    assert (
        markdown_to_telegram_html("[wiki](https://example.com)")
        == '<a href="https://example.com">wiki</a>'
    )
    assert markdown_to_telegram_html("a < b & c") == "a &lt; b &amp; c"
    assert (
        markdown_to_telegram_html("**«Упаковка не соответствует заданию»**")
        == "<b>«Упаковка не соответствует заданию»</b>"
    )
    assert (
        markdown_to_telegram_html("*   **Проверка:** текст")
        == "• <b>Проверка:</b> текст"
    )


def test_strip_markdown_light():
    raw = "### 1. Заголовок\n*   **Проверка:** шаг"
    plain = strip_markdown_light(raw)
    assert "###" not in plain
    assert "**" not in plain
    assert "1. Заголовок" in plain
    assert "• Проверка:" in plain


def test_split_markdown_for_telegram_single_part():
    text = "Короткий ответ **жирный**"
    parts = split_markdown_for_telegram(text)
    assert parts == [text]


def test_split_markdown_for_telegram_multiple_parts():
    paragraph = "### Заголовок\n" + "Текст абзаца с **жирным** словом.\n" * 40
    long_text = (paragraph + "\n\n") * 8
    parts = split_markdown_for_telegram(long_text, max_html_len=4096)
    assert len(parts) > 1
    assert "".join(parts).replace("\n\n", "\n") == long_text.replace("\n\n", "\n") or "".join(parts) == long_text.strip() or long_text.startswith(parts[0])
    # Каждая часть должна влезать в лимит после HTML-конвертации
    for part in parts:
        assert len(markdown_to_telegram_html(part)) <= 4096 - 32


def test_telegram_client_smart_truncate():
    client = TelegramClient(bot_token="test-token", max_message_length=20)

    short = "Short text"
    assert client._smart_truncate(short, 20) == short

    text_with_sep = "Line one\n\nLine two\n\nLine three"
    result = client._smart_truncate(text_with_sep, 20)
    assert len(result) <= 20
    assert result.endswith("Line two")

    long_no_sep = "A" * 5000
    prepared = client._prepare_text(long_no_sep, parse_mode="")
    assert len(prepared) <= 4096

    html_long = "<b>" + "A" * 5000 + "</b>"
    prepared_html = client._prepare_text(html_long, parse_mode="HTML")
    assert "<" not in prepared_html
    assert len(prepared_html) <= 4096


def test_telegram_client_download_file_bytes(monkeypatch):
    calls = []

    def mock_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        response = MagicMock()
        if "getFile" in url:
            response.status_code = 200
            response.json.return_value = {
                "ok": True,
                "result": {"file_path": "photos/file_1.jpg"},
            }
        else:
            response.status_code = 200
            response.content = b"\xff\xd8\xffimage"
            response.raise_for_status = MagicMock()
        return response

    monkeypatch.setattr("integrations.telegram.requests.get", mock_get)

    client = TelegramClient(bot_token="test-token")
    data, filename, mime = client.download_file_bytes("file-id-1")

    assert data == b"\xff\xd8\xffimage"
    assert filename == "file_1.jpg"
    assert mime == "image/jpeg"
    assert any("getFile" in call["url"] for call in calls)
    assert any("/file/bottest-token/photos/file_1.jpg" in call["url"] for call in calls)


def test_telegram_client_429_retry(monkeypatch):
    call_count = 0

    def mock_post(url, json=None, timeout=None):
        nonlocal call_count
        call_count += 1
        response = MagicMock()
        if call_count == 1:
            response.status_code = 429
            response.json.return_value = {"parameters": {"retry_after": 0.001}}
        else:
            response.status_code = 200
            response.json.return_value = {"ok": True, "result": {"message_id": 456}}
        return response

    monkeypatch.setattr("integrations.telegram.requests.post", mock_post)
    monkeypatch.setattr("integrations.telegram.time.sleep", lambda _x: None)

    client = TelegramClient(bot_token="test-token")
    result = client.send_message(chat_id=1, text="Test")

    assert call_count == 2
    assert result["result"]["message_id"] == 456


# ============== Worker offset ==============


def test_offset_roundtrip(tmp_path):
    offset_path = tmp_path / "telegram_offset.json"
    assert load_offset(offset_path) is None
    save_offset(offset_path, 12345)
    assert load_offset(offset_path) == 12345


# ============== parse_command ==============


def test_parse_command_start():
    assert parse_command("/start 123456") == ("start", "123456")


def test_parse_command_mode():
    assert parse_command("/mode кратко") == ("mode", "кратко")


def test_parse_command_plain_text():
    assert parse_command("Привет") == (None, "Привет")


def test_normalize_user_input_buttons():
    assert normalize_user_input("❓ Справка") == ("help", "")
    assert normalize_user_input("🔄 Новый диалог") == ("reset", "")
    assert normalize_user_input(BUTTON_MODE) == ("mode", "")
    assert normalize_user_input("/mode кратко") == ("mode", "кратко")


def test_build_main_keyboard():
    keyboard = build_main_keyboard()
    assert keyboard["resize_keyboard"] is True
    assert len(keyboard["keyboard"]) == 2
    assert keyboard["keyboard"][0][0]["text"] == "❓ Справка"


def test_build_mode_inline_keyboard():
    keyboard = build_mode_inline_keyboard()
    callbacks = [
        button["callback_data"]
        for row in keyboard["inline_keyboard"]
        for button in row
    ]
    assert "mode:кратко" in callbacks
    assert "mode:инструкция" in callbacks


def test_message_has_image_and_caption():
    photo_message = {
        "photo": [{"file_id": "small"}, {"file_id": "large"}],
        "caption": "что на скриншоте?",
    }
    assert message_has_image(photo_message) is True
    assert message_question_text(photo_message) == "что на скриншоте?"
    assert primary_image_file_id(photo_message) == "large"

    document_message = {
        "document": {
            "file_id": "doc-image",
            "mime_type": "image/png",
            "file_name": "screen.png",
        }
    }
    assert message_has_image(document_message) is True
    assert primary_image_file_id(document_message) == "doc-image"
    assert message_has_image({"text": "только текст"}) is False


def test_upload_chat_attachment(monkeypatch):
    calls = []

    def mock_post(url, headers=None, files=None, timeout=None):
        calls.append({"url": url, "headers": dict(headers or {}), "files": files, "timeout": timeout})
        response = MagicMock()
        response.status_code = 201
        response.json.return_value = {"attachments": [{"id": "att-123"}]}
        return response

    monkeypatch.setattr("scripts.telegram_bot_worker.requests.post", mock_post)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )

    att_id = upload_chat_attachment(b"png-bytes", "screen.png", "image/png")
    assert att_id == "att-123"
    assert calls[0]["url"].endswith("/api/chat/attachments")
    assert calls[0]["headers"]["X-API-Key"] == "secret"
    assert calls[0]["files"]["files"][0] == "screen.png"


def test_collect_image_attachment_ids(monkeypatch):
    client = MagicMock()
    client.download_file_bytes.return_value = (b"img", "shot.jpg", "image/jpeg")
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.upload_chat_attachment",
        lambda data, name, mime: "saved-id",
    )

    message = {"photo": [{"file_id": "a"}, {"file_id": "best"}]}
    assert collect_image_attachment_ids(client, message) == ["saved-id"]
    client.download_file_bytes.assert_called_once_with("best")


# ============== Telegram link DB operations ==============


def test_telegram_link_code_generation(monkeypatch):
    from core.chat_history import get_chat_history

    monkeypatch.setattr("config.settings.TELEGRAM_LINK_CODE_TTL_SECONDS", 300)
    chat_history = get_chat_history()
    user = _create_test_user()

    result = chat_history.create_telegram_link(user.id)
    code = result["code"]
    assert len(code) == 6
    assert code.isdigit()
    assert "expires_at" in result

    expires = datetime.fromisoformat(result["expires_at"])
    assert expires > datetime.now()

    # Уникальность: два подряд запроса для разных пользователей — разные коды
    user2 = chat_history.create_user(
        username="telegramuser2",
        email="tg2@example.com",
        password_hash="hash",
        role="user",
    )
    result2 = chat_history.create_telegram_link(user2.id)
    assert result2["code"] != code

    # После использования кода — новый create выдаёт другой код
    verify = chat_history.verify_telegram_link(
        code, telegram_user_id=111, telegram_username="tg_name"
    )
    assert verify is not None
    assert verify["user_id"] == user.id
    assert verify["role"] == "user"

    result_after_use = chat_history.create_telegram_link(user.id)
    assert result_after_use["code"] != code

    link = chat_history.get_telegram_link(111)
    assert link is not None
    assert link["user_id"] == user.id
    assert link["telegram_username"] == "tg_name"
    assert link["role"] == "user"


def test_telegram_link_reuses_active_code(monkeypatch):
    from core.chat_history import get_chat_history

    monkeypatch.setattr("config.settings.TELEGRAM_LINK_CODE_TTL_SECONDS", 300)
    chat_history = get_chat_history()
    user = _create_test_user()

    first = chat_history.create_telegram_link(user.id)
    second = chat_history.create_telegram_link(user.id)
    assert second["code"] == first["code"]
    assert second["expires_at"] == first["expires_at"]


def test_get_telegram_link_survives_code_ttl_expiry(monkeypatch):
    """После verify привязка не должна пропадать по истечении TTL кода."""
    from core.chat_history import get_chat_history

    monkeypatch.setattr("config.settings.TELEGRAM_LINK_CODE_TTL_SECONDS", 1)
    chat_history = get_chat_history()
    user = _create_test_user()
    link_row = chat_history.create_telegram_link(user.id)
    chat_history.verify_telegram_link(link_row["code"], telegram_user_id=333)

    with chat_history._get_connection() as conn:
        conn.execute(
            "UPDATE telegram_links SET expires_at = ? WHERE code = ?",
            ("2000-01-01T00:00:00", link_row["code"]),
        )
        conn.commit()

    link = chat_history.get_telegram_link(333)
    assert link is not None
    assert link["user_id"] == user.id


def test_telegram_link_verify_expired(monkeypatch):
    from core.chat_history import get_chat_history

    chat_history = get_chat_history()
    user = _create_test_user()
    result = chat_history.create_telegram_link(user.id)

    with chat_history._get_connection() as conn:
        cursor = conn.cursor()
        past = (datetime.now() - timedelta(seconds=1)).isoformat()
        cursor.execute(
            "UPDATE telegram_links SET expires_at = ? WHERE code = ?",
            (past, result["code"]),
        )
        conn.commit()

    assert chat_history.verify_telegram_link(result["code"], 111) is None


def test_telegram_link_verify_used(monkeypatch):
    from core.chat_history import get_chat_history

    chat_history = get_chat_history()
    user = _create_test_user()
    result = chat_history.create_telegram_link(user.id)

    first = chat_history.verify_telegram_link(result["code"], 111)
    assert first is not None

    second = chat_history.verify_telegram_link(result["code"], 111)
    assert second is None


# ============== API endpoints ==============


def test_telegram_api_status(client):
    rv = client.get("/api/telegram/status")
    assert rv.status_code == 200
    body = rv.get_json()
    assert "enabled" in body
    assert body["bot_username"] is None


def test_telegram_api_link(client, monkeypatch):
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_ENABLED", True)
    client.post(
        "/api/auth/register",
        json={"username": "tglink", "email": "tglink@example.com", "password": "password123"},
    )
    rv = client.post("/api/telegram/link")
    assert rv.status_code == 200
    body = rv.get_json()
    assert "code" in body
    assert "expires_at" in body


def test_telegram_api_verify(client, monkeypatch):
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_ENABLED", True)
    from core.chat_history import get_chat_history

    chat_history = get_chat_history()
    user = _create_test_user()
    link = chat_history.create_telegram_link(user.id)

    rv = client.post(
        "/api/telegram/verify",
        json={"code": link["code"], "telegram_user_id": 222},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["user_id"] == user.id
    assert body["role"] == "user"


def test_telegram_api_resolve(client, monkeypatch):
    monkeypatch.setattr("api.routes.telegram.settings.TELEGRAM_ENABLED", True)
    from core.chat_history import get_chat_history

    chat_history = get_chat_history()
    user = _create_test_user()
    link = chat_history.create_telegram_link(user.id)
    chat_history.verify_telegram_link(link["code"], telegram_user_id=555)

    rv = client.post(
        "/api/telegram/resolve",
        json={"telegram_user_id": 555},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["user_id"] == user.id
    assert body["role"] == "user"

    missing = client.post(
        "/api/telegram/resolve",
        json={"telegram_user_id": 999001},
    )
    assert missing.status_code == 404


def test_hydrate_session_from_resolve(monkeypatch):
    from scripts.telegram_bot_worker import TelegramSession, hydrate_session, _sessions

    _sessions.clear()
    calls = []

    def mock_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": dict(headers or {})})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"user_id": 42, "role": "user"}
        return response

    monkeypatch.setattr("scripts.telegram_bot_worker.requests.post", mock_post)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )

    session = TelegramSession()
    assert hydrate_session(session, 168539480) is True
    assert session.user_id == 42
    assert calls[0]["url"].endswith("/api/telegram/resolve")
    assert calls[0]["json"] == {"telegram_user_id": 168539480}

    assert hydrate_session(session, 168539480) is True
    assert len(calls) == 1


def test_hydrate_session_not_linked(monkeypatch):
    from scripts.telegram_bot_worker import TelegramSession, hydrate_session, _sessions

    _sessions.clear()

    def mock_post(url, json=None, headers=None, timeout=None):
        response = MagicMock()
        response.status_code = 404
        response.json.return_value = {"error": "not found"}
        return response

    monkeypatch.setattr("scripts.telegram_bot_worker.requests.post", mock_post)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )

    session = TelegramSession()
    assert hydrate_session(session, 1) is False
    assert session.user_id is None


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_resolve_chat_session_with_telegram_user_id(mock_reachable, mock_init, client):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="Ответ", citations=[], sources=[])

    from core.chat_history import get_chat_history

    chat_history = get_chat_history()
    user = _create_test_user()
    link = chat_history.create_telegram_link(user.id)
    chat_history.verify_telegram_link(link["code"], telegram_user_id=999)

    client.post("/api/auth/logout")

    rv = client.post("/api/chat", json={"message": "вопрос", "telegram_user_id": 999})
    assert rv.status_code == 200
    body = rv.get_json()
    chat_id = body["chat_id"]

    session = chat_history.get_session(chat_id)
    assert session.user_id == user.id

    rv = client.post(
        "/api/chat",
        json={"message": "уточнение", "chat_id": chat_id, "telegram_user_id": 999},
    )
    assert rv.status_code == 200
    assert rv.get_json()["chat_id"] == chat_id


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_resolve_chat_session_telegram_cannot_access_foreign_chat(
    mock_reachable, mock_init, client
):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="Ответ", citations=[], sources=[])

    from core.chat_history import get_chat_history

    chat_history = get_chat_history()
    owner = _create_test_user()
    other = chat_history.create_user(
        username="otheruser",
        email="other@example.com",
        password_hash=generate_password_hash("password123"),
        role="user",
    )
    foreign_chat = chat_history.create_session(user_id=other.id, title="Чужой чат")

    link = chat_history.create_telegram_link(owner.id)
    chat_history.verify_telegram_link(link["code"], telegram_user_id=888)

    client.post("/api/auth/logout")

    rv = client.post(
        "/api/chat",
        json={
            "message": "вопрос",
            "chat_id": foreign_chat.id,
            "telegram_user_id": 888,
        },
    )
    assert rv.status_code == 403
    assert rv.get_json()["error"] == "Нет доступа к чату"


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_resolve_chat_session_telegram_recovers_stale_guest_chat_id(
    mock_reachable, mock_init, client
):
    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="Ответ", citations=[], sources=[])

    from core.chat_history import get_chat_history

    chat_history = get_chat_history()
    user = _create_test_user()
    guest_chat = chat_history.create_session(user_id=None, title="Гостевой чат")

    link = chat_history.create_telegram_link(user.id)
    chat_history.verify_telegram_link(link["code"], telegram_user_id=777)

    client.post("/api/auth/logout")

    rv = client.post(
        "/api/chat",
        json={
            "message": "вопрос",
            "chat_id": guest_chat.id,
            "telegram_user_id": 777,
        },
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["chat_id"] != guest_chat.id
    assert chat_history.get_session(body["chat_id"]).user_id == user.id


def test_validate_rich_message_requires_exactly_one_representation():
    from integrations.telegram import validate_rich_message

    assert validate_rich_message({"markdown": "| a | b |\n|---|---|\n| 1 | 2 |"})["markdown"].startswith("| a |")
    with pytest.raises(ValueError):
        validate_rich_message({})
    with pytest.raises(ValueError):
        validate_rich_message({"markdown": "x", "html": "<p>x</p>"})


def test_prepare_rich_markdown_truncates():
    from integrations.telegram import prepare_rich_markdown

    long_text = "я" * 100
    out = prepare_rich_markdown(long_text, max_chars=50)
    assert len(out) <= 50
    assert out.endswith("…") or len(out) == 50


def test_telegram_client_send_rich_message(monkeypatch):
    calls = []

    def mock_request(self, method, *, params=None, json_payload=None):
        calls.append((method, json_payload))
        return {"ok": True, "result": {"message_id": 42}}

    monkeypatch.setattr(TelegramClient, "_request", mock_request)
    client = TelegramClient(bot_token="test-token")
    table = "| A | B |\n|---|---|\n| 1 | 2 |"
    result = client.send_rich_message(987, {"markdown": table})
    assert result["result"]["message_id"] == 42
    assert calls[0][0] == "sendRichMessage"
    assert calls[0][1]["chat_id"] == 987
    assert calls[0][1]["rich_message"]["markdown"] == table


def test_telegram_client_send_rich_message_draft(monkeypatch):
    calls = []

    def mock_request(self, method, *, params=None, json_payload=None):
        calls.append((method, json_payload))
        return {"ok": True, "result": True}

    monkeypatch.setattr(TelegramClient, "_request", mock_request)
    client = TelegramClient(bot_token="test-token")
    client.send_rich_message_draft(
        987,
        draft_id=555,
        rich_message={"html": "<tg-thinking>Думаю...</tg-thinking>"},
    )
    assert calls[0][0] == "sendRichMessageDraft"
    assert calls[0][1]["draft_id"] == 555
    assert "html" in calls[0][1]["rich_message"]


def test_make_rich_draft_id_uses_update_id():
    assert make_rich_draft_id({"update_id": 42}, tg_user_id=1) == 42
    draft = make_rich_draft_id({}, tg_user_id=7)
    assert isinstance(draft, int) and draft != 0


def test_handle_question_rich_messages_draft_then_final(monkeypatch):
    from scripts.telegram_bot_worker import TelegramSession, _sessions

    _sessions.clear()
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MESSAGES", True)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_MERMAID_IMAGES", False)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_SHOW_SOURCES", False)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS", 0
    )
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MAX_CHARS", 32000)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.hydrate_session",
        lambda session, tg_user_id: setattr(session, "user_id", 1) or True,
    )

    calls: list[tuple] = []

    class FakeClient:
        def send_chat_action(self, *a, **k):
            return {"ok": True}

        def send_rich_message_draft(self, chat_id, draft_id, rich_message):
            calls.append(("draft", chat_id, draft_id, rich_message))
            return {"ok": True, "result": True}

        def send_rich_message(self, chat_id, rich_message, reply_markup=None):
            calls.append(("final", chat_id, rich_message))
            return {"ok": True, "result": {"message_id": 9}}

        def send_message(self, *a, **k):
            raise AssertionError("classic send_message should not be used on success")

        def edit_message_text(self, *a, **k):
            raise AssertionError("classic edit should not be used on success")

    sse = (
        'data: {"type":"delta","text":"| A | B |\\n"}\n\n'
        'data: {"type":"delta","text":"|---|---|\\n"}\n\n'
        'data: {"type":"delta","text":"| 1 | 2 |"}\n\n'
        'data: {"type":"done","answer":"| A | B |\\n|---|---|\\n| 1 | 2 |","chat_id":"c1","sources":[],"citations":[]}\n\n'
        "data: [DONE]\n\n"
    )

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            for line in sse.splitlines():
                yield line

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.requests.post",
        lambda *a, **k: FakeResp(),
    )

    update = {
        "update_id": 1001,
        "message": {
            "chat": {"id": 55},
            "from": {"id": 77},
            "text": "покажи таблицу",
        },
    }
    handle_question(update, TelegramSession(), FakeClient(), text="покажи таблицу")

    assert calls[0][0] == "draft"
    assert calls[0][2] == 1001
    assert "tg-thinking" in calls[0][3].get("html", "")
    assert any(c[0] == "draft" and "markdown" in c[3] for c in calls)
    finals = [c for c in calls if c[0] == "final"]
    assert len(finals) == 1
    assert "| A | B |" in finals[0][2]["markdown"]


def test_handle_question_rich_failure_falls_back(monkeypatch):
    from integrations.telegram import TelegramError
    from scripts.telegram_bot_worker import TelegramSession, _sessions

    _sessions.clear()
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MESSAGES", True)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_MERMAID_IMAGES", False)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_SHOW_SOURCES", False)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS", 0
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.hydrate_session",
        lambda session, tg_user_id: setattr(session, "user_id", 1) or True,
    )

    legacy = []

    def fake_send_full(client, chat_id, message_id, markdown_text):
        legacy.append((chat_id, message_id, markdown_text))

    monkeypatch.setattr("scripts.telegram_bot_worker._send_full_answer", fake_send_full)

    class FakeClient:
        def send_chat_action(self, *a, **k):
            return {"ok": True}

        def send_rich_message_draft(self, *a, **k):
            return {"ok": True}

        def send_rich_message(self, *a, **k):
            raise TelegramError("rich failed")

        def send_message(self, chat_id, text, **k):
            legacy.append(("placeholder", chat_id, text))
            return {"ok": True, "result": {"message_id": 1}}

        def edit_message_text(self, *a, **k):
            return {"ok": True}

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield (
                'data: {"type":"done","answer":"**ok**\\n\\n**Источники:**\\n1. doc",'
                '"chat_id":"c1","sources":[],"citations":[]}'
            )
            yield "data: [DONE]"

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.requests.post",
        lambda *a, **k: FakeResp(),
    )

    update = {
        "update_id": 2,
        "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "q"},
    }
    handle_question(update, TelegramSession(), FakeClient(), text="q")
    assert legacy
    fallback_calls = [item for item in legacy if item[0] == 1 and isinstance(item[2], str)]
    assert fallback_calls
    fallback_markdown = fallback_calls[0][2]
    assert "**ok**" in fallback_markdown
    assert "**Источники:**" not in fallback_markdown


def test_handle_question_rich_failure_fallback_not_truncated(monkeypatch):
    from integrations.telegram import TelegramError
    from scripts.telegram_bot_worker import TelegramSession, _sessions

    _sessions.clear()
    rich_max = 100
    body = "x" * 250
    sources_block = "\n\n**Источники:**\n1. doc"
    full_answer = body + sources_block
    expected_stripped = body

    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MESSAGES", True)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_MERMAID_IMAGES", False)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_SHOW_SOURCES", False)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MAX_CHARS", rich_max)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS", 0
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.hydrate_session",
        lambda session, tg_user_id: setattr(session, "user_id", 1) or True,
    )

    legacy = []

    def fake_send_full(client, chat_id, message_id, markdown_text):
        legacy.append((chat_id, message_id, markdown_text))

    monkeypatch.setattr("scripts.telegram_bot_worker._send_full_answer", fake_send_full)

    class FakeClient:
        def send_chat_action(self, *a, **k):
            return {"ok": True}

        def send_rich_message_draft(self, *a, **k):
            return {"ok": True}

        def send_rich_message(self, *a, **k):
            raise TelegramError("rich failed")

        def send_message(self, *a, **k):
            raise AssertionError("classic send_message should not be used")

        def edit_message_text(self, *a, **k):
            raise AssertionError("classic edit should not be used")

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield (
                f'data: {{"type":"done","answer":{json.dumps(full_answer)},'
                '"chat_id":"c1","sources":[],"citations":[]}'
            )
            yield "data: [DONE]"

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.requests.post",
        lambda *a, **k: FakeResp(),
    )

    update = {
        "update_id": 3,
        "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "q"},
    }
    handle_question(update, TelegramSession(), FakeClient(), text="q")

    assert legacy
    fallback_markdown = legacy[0][2]
    assert len(fallback_markdown) > rich_max
    assert fallback_markdown == expected_stripped
    assert "**Источники:**" not in fallback_markdown


def test_resolve_browser_executable_prefers_explicit(tmp_path):
    from integrations.mermaid_telegram import resolve_browser_executable

    fake = tmp_path / "chrome.exe"
    fake.write_bytes(b"x")
    assert resolve_browser_executable(str(fake)) == str(fake)


def test_render_mermaid_png_passes_puppeteer_config(monkeypatch, tmp_path):
    from pathlib import Path

    from integrations import mermaid_telegram as mt

    calls = []

    class FakeCompleted:
        returncode = 0
        stderr = b""
        stdout = b""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raw = cmd if isinstance(cmd, str) else " ".join(cmd)
        assert "-p" in raw
        import re

        m = re.search(r'-o\s+"?([^"\s]+)"?', raw)
        assert m
        Path(m.group(1)).write_bytes(b"PNGFAKE")
        return FakeCompleted()

    monkeypatch.setattr(mt.subprocess, "run", fake_run)
    browser = tmp_path / "chrome.exe"
    browser.write_bytes(b"x")
    png = mt.render_mermaid_png(
        "flowchart TD\nA-->B",
        mmdc_cmd="mmdc.cmd",
        browser_executable=str(browser),
    )
    assert png == b"PNGFAKE"
    assert calls


def test_extract_mermaid_blocks_order():
    from integrations.mermaid_telegram import extract_mermaid_blocks

    text = (
        "Intro\n"
        "```mermaid\nflowchart TD\nA-->B\n```\n"
        "Mid\n"
        "```Mermaid\nsequenceDiagram\nA->>B: hi\n```\n"
    )
    blocks = extract_mermaid_blocks(text)
    assert len(blocks) == 2
    assert "flowchart TD" in blocks[0].code
    assert "sequenceDiagram" in blocks[1].code


def test_hide_mermaid_source_complete_and_incomplete():
    from integrations.mermaid_telegram import hide_mermaid_source

    full = "До\n```mermaid\nflowchart TD\nA-->B\n```\nПосле"
    assert hide_mermaid_source(full) == "До\n\nПосле"
    stream = "До\n```mermaid\nflowchart TD\nA-->"
    assert hide_mermaid_source(stream) == "До"
    assert hide_mermaid_source(stream, placeholder="⏳ Схема…") == "До\n⏳ Схема…"


def test_is_trivial_display_text():
    from integrations.mermaid_telegram import is_trivial_display_text

    assert is_trivial_display_text("")
    assert is_trivial_display_text("**")
    assert is_trivial_display_text("****")
    assert is_trivial_display_text("  *_*  ")
    assert not is_trivial_display_text("Схема")
    assert not is_trivial_display_text("**Заголовок**")


def test_process_answer_mermaid_photo_only_clears_trivial_leftover():
    from integrations.mermaid_telegram import process_answer_mermaid

    text = "**\n\n```mermaid\nflowchart TD\nA-->B\n```\n"
    result = process_answer_mermaid(
        text,
        enabled=True,
        render_fn=lambda code, timeout: b"PNG",
    )
    assert result.images == [b"PNG"]
    assert result.text == ""
    assert "```" not in result.text


def test_process_answer_mermaid_strips_success_keeps_failure():
    from integrations.mermaid_telegram import process_answer_mermaid

    text = (
        "Схема:\n"
        "```mermaid\nflowchart TD\nA-->B\n```\n"
        "И ещё:\n"
        "```mermaid\ngraph LR\nX-->Y\n```\n"
    )

    def fake_render(code: str, timeout: float) -> bytes:
        if "flowchart" in code:
            return b"PNG1"
        raise RuntimeError("boom")

    result = process_answer_mermaid(
        text,
        enabled=True,
        max_diagrams=5,
        render_fn=fake_render,
    )
    assert result.images == [b"PNG1"]
    assert "flowchart TD" not in result.text
    assert "```mermaid" not in result.text
    assert "graph LR" not in result.text
    assert "Схема:" in result.text
    assert "не удалось" in result.text.lower()


def test_process_answer_mermaid_respects_max_diagrams():
    from integrations.mermaid_telegram import process_answer_mermaid

    text = "\n\n".join(
        f"```mermaid\nflowchart TD\nA{i}-->B{i}\n```" for i in range(3)
    )
    calls = []

    def fake_render(code: str, timeout: float) -> bytes:
        calls.append(code)
        return b"PNG"

    result = process_answer_mermaid(
        text,
        enabled=True,
        max_diagrams=2,
        render_fn=fake_render,
    )
    assert len(calls) == 2
    assert len(result.images) == 2
    assert "```mermaid" not in result.text
    assert "не удалось" in result.text.lower()

def test_telegram_client_send_photo(monkeypatch):
    calls = []

    def mock_request(self, method, *, params=None, json_payload=None, data=None, files=None):
        calls.append((method, data, files))
        return {"ok": True, "result": {"message_id": 11}}

    monkeypatch.setattr(TelegramClient, "_request", mock_request)
    client = TelegramClient(bot_token="test-token")
    result = client.send_photo(55, b"\x89PNG", filename="diagram_1.png")
    assert result["result"]["message_id"] == 11
    assert calls[0][0] == "sendPhoto"
    assert calls[0][1]["chat_id"] == "55"
    assert calls[0][2]["photo"][0] == "diagram_1.png"
    assert calls[0][2]["photo"][1] == b"\x89PNG"


def test_handle_question_photo_only_skips_trivial_text(monkeypatch):
    from scripts.telegram_bot_worker import TelegramSession, _sessions

    _sessions.clear()
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MESSAGES", True)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_MERMAID_IMAGES", True)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_SHOW_SOURCES", False)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_MERMAID_MAX_DIAGRAMS", 5)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS", 0
    )
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MAX_CHARS", 32000)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.hydrate_session",
        lambda session, tg_user_id: setattr(session, "user_id", 1) or True,
    )

    answer = "**\n```mermaid\nflowchart TD\nA-->B\n```\n"

    def fake_process(text, **kwargs):
        from integrations.mermaid_telegram import MermaidProcessResult

        return MermaidProcessResult(text="", images=[b"PNGONLY"])

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.process_answer_mermaid",
        fake_process,
    )

    calls: list[tuple] = []

    class FakeClient:
        def send_chat_action(self, *a, **k):
            calls.append(("action", a[1] if len(a) > 1 else k.get("action")))
            return {"ok": True}

        def send_rich_message_draft(self, *a, **k):
            calls.append(("draft",))
            return {"ok": True}

        def send_rich_message(self, *a, **k):
            calls.append(("final",))
            raise AssertionError("should not send trivial text when photos exist")

        def send_photo(self, chat_id, photo, *, filename="diagram.png", caption=None):
            calls.append(("photo", chat_id, photo))
            return {"ok": True, "result": {"message_id": 10}}

        def send_message(self, *a, **k):
            raise AssertionError("classic send_message should not be used")

        def edit_message_text(self, *a, **k):
            raise AssertionError("classic edit should not be used")

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield (
                f'data: {{"type":"done","answer":{json.dumps(answer)},'
                '"chat_id":"c1","sources":[],"citations":[]}'
            )
            yield "data: [DONE]"

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.requests.post",
        lambda *a, **k: FakeResp(),
    )

    update = {
        "update_id": 99,
        "message": {"chat": {"id": 55}, "from": {"id": 77}, "text": "только схема"},
    }
    handle_question(update, TelegramSession(), FakeClient(), text="только схема")

    assert not any(c[0] == "final" for c in calls)
    photos = [c for c in calls if c[0] == "photo"]
    assert len(photos) == 1
    assert photos[0][2] == b"PNGONLY"


def test_handle_question_sends_mermaid_photos_after_text(monkeypatch):
    from scripts.telegram_bot_worker import TelegramSession, _sessions

    _sessions.clear()
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MESSAGES", True)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_MERMAID_IMAGES", True)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_SHOW_SOURCES", False)
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_MERMAID_MAX_DIAGRAMS", 5)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS", 0
    )
    monkeypatch.setattr("scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MAX_CHARS", 32000)
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.hydrate_session",
        lambda session, tg_user_id: setattr(session, "user_id", 1) or True,
    )

    answer = "Визуализация\n\n```mermaid\nflowchart TD\nA-->B\n```\n"

    def fake_process(text, **kwargs):
        from integrations.mermaid_telegram import MermaidProcessResult

        assert "flowchart TD" in text
        return MermaidProcessResult(text="Визуализация", images=[b"PNGDATA"])

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.process_answer_mermaid",
        fake_process,
    )

    calls: list[tuple] = []

    class FakeClient:
        def send_chat_action(self, *a, **k):
            return {"ok": True}

        def send_rich_message_draft(self, *a, **k):
            calls.append(("draft",))
            return {"ok": True}

        def send_rich_message(self, chat_id, rich_message, reply_markup=None):
            calls.append(("final", rich_message))
            return {"ok": True, "result": {"message_id": 9}}

        def send_photo(self, chat_id, photo, *, filename="diagram.png", caption=None):
            calls.append(("photo", chat_id, photo, filename))
            return {"ok": True, "result": {"message_id": 10}}

        def send_message(self, *a, **k):
            raise AssertionError("classic send_message should not be used")

        def edit_message_text(self, *a, **k):
            raise AssertionError("classic edit should not be used")

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield (
                f'data: {{"type":"done","answer":{json.dumps(answer)},'
                '"chat_id":"c1","sources":[],"citations":[]}'
            )
            yield "data: [DONE]"

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.requests.post",
        lambda *a, **k: FakeResp(),
    )

    update = {
        "update_id": 42,
        "message": {"chat": {"id": 55}, "from": {"id": 77}, "text": "схема"},
    }
    handle_question(update, TelegramSession(), FakeClient(), text="схема")

    finals = [c for c in calls if c[0] == "final"]
    photos = [c for c in calls if c[0] == "photo"]
    assert len(finals) == 1
    assert finals[0][1]["markdown"] == "Визуализация"
    assert "mermaid" not in finals[0][1]["markdown"].lower()
    assert len(photos) == 1
    assert photos[0][1] == 55
    assert photos[0][2] == b"PNGDATA"
    # text before photo
    final_idx = next(i for i, c in enumerate(calls) if c[0] == "final")
    photo_idx = next(i for i, c in enumerate(calls) if c[0] == "photo")
    assert final_idx < photo_idx
