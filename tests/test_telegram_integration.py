"""Тесты интеграции Telegram-бота wiki_4 без реальных вызовов API."""

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
    load_offset,
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

    # Инвалидация старого кода
    result3 = chat_history.create_telegram_link(user.id)
    assert result3["code"] != code

    # verify → get roundtrip
    verify = chat_history.verify_telegram_link(
        result3["code"], telegram_user_id=111, telegram_username="tg_name"
    )
    assert verify is not None
    assert verify["user_id"] == user.id
    assert verify["role"] == "user"

    link = chat_history.get_telegram_link(111)
    assert link is not None
    assert link["user_id"] == user.id
    assert link["telegram_username"] == "tg_name"
    assert link["role"] == "user"


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
