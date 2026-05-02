"""Тесты интеграции чат-бота Битрикс24 без реальных REST-вызовов."""

from scripts.bitrix24_bot_worker import (
    extract_message_event,
    load_offset,
    process_event,
    save_offset,
)


def test_extract_message_event_success():
    event = {
        "type": "ONIMBOTV2MESSAGEADD",
        "data": {
            "message": {"id": 789, "authorId": 1, "text": "Как настроить принтер?", "isSystem": False},
            "chat": {"dialogId": "chat5"},
            "user": {"id": 1, "bot": False},
        },
    }

    parsed = extract_message_event(event)

    assert parsed == {
        "text": "Как настроить принтер?",
        "dialog_id": "chat5",
        "message_id": 789,
        "author_id": 1,
    }


def test_extract_message_event_ignores_system_message():
    event = {
        "type": "ONIMBOTV2MESSAGEADD",
        "data": {
            "message": {"text": "system", "isSystem": "Y"},
            "chat": {"dialogId": "chat5"},
            "user": {"bot": False},
        },
    }

    assert extract_message_event(event) is None


def test_offset_roundtrip(tmp_path):
    offset_path = tmp_path / "bitrix_offset.json"

    assert load_offset(offset_path) is None
    save_offset(offset_path, 12345)

    assert load_offset(offset_path) == 12345


def test_process_event_sends_answer(monkeypatch):
    sent_messages = []

    class FakeBitrixClient:
        def send_message(self, *, bot_id, bot_token, dialog_id, text):
            sent_messages.append({
                "bot_id": bot_id,
                "bot_token": bot_token,
                "dialog_id": dialog_id,
                "text": text,
            })
            return {"messageId": 100}

    def fake_ask(message, *, api_url, api_key="", timeout=120.0):
        assert message == "Где инструкция?"
        assert api_url == "http://127.0.0.1:5000"
        assert api_key == "secret"
        return "Инструкция находится в базе знаний."

    monkeypatch.setattr("scripts.bitrix24_bot_worker.ask_internal_chat_api", fake_ask)

    processed = process_event(
        {
            "type": "ONIMBOTV2MESSAGEADD",
            "data": {
                "message": {"text": "Где инструкция?", "isSystem": False},
                "chat": {"dialogId": "7"},
                "user": {"id": 2, "bot": False},
            },
        },
        bitrix=FakeBitrixClient(),
        bot_id=456,
        bot_token="bot-token",
        api_url="http://127.0.0.1:5000",
        api_key="secret",
    )

    assert processed is True
    assert sent_messages == [{
        "bot_id": 456,
        "bot_token": "bot-token",
        "dialog_id": "7",
        "text": "Инструкция находится в базе знаний.",
    }]
