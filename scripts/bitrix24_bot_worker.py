#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Polling-worker чат-бота Битрикс24, связанного с POST /api/chat."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from config import get_logger, settings  # noqa: E402
from integrations.bitrix24 import Bitrix24Client, Bitrix24Error  # noqa: E402

logger = get_logger(__name__)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "y", "yes", "да"}


def dialog_chat_map_path(offset_path: str | Path) -> Path:
    """JSON с соответствием dialogId -> chat_id рядом с offset-файлом."""
    path = Path(offset_path)
    return path.with_name(f"{path.stem}.dialogs{path.suffix or '.json'}")


def load_offset(path: str | Path) -> int | None:
    """Прочитать сохранённый offset очереди Битрикс24."""
    offset_path = Path(path)
    if not offset_path.exists():
        return None
    try:
        data = json.loads(offset_path.read_text(encoding="utf-8"))
        offset = data.get("offset")
        return int(offset) if offset is not None else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning("Не удалось прочитать offset Битрикс24 из %s", offset_path)
        return None


def save_offset(path: str | Path, offset: int) -> None:
    """Сохранить offset атомарной заменой файла."""
    offset_path = Path(path)
    offset_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = offset_path.with_suffix(offset_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps({"offset": int(offset)}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(offset_path)


def load_dialog_chats(path: str | Path) -> dict[str, int]:
    """Прочитать соответствие dialogId -> wiki chat_id."""
    map_path = dialog_chat_map_path(path)
    if not map_path.exists():
        return {}
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in data.items():
            try:
                result[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning("Не удалось прочитать карту диалогов Битрикс24 из %s", map_path)
        return {}


def save_dialog_chats(path: str | Path, mapping: dict[str, int]) -> None:
    """Сохранить соответствие dialogId -> chat_id атомарно."""
    map_path = dialog_chat_map_path(path)
    map_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = map_path.with_suffix(map_path.suffix + ".tmp")
    payload = {str(k): int(v) for k, v in mapping.items()}
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(map_path)


def extract_message_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Достать текст и dialogId из события ONIMBOTV2MESSAGEADD."""
    event_type = event.get("type") or event.get("event")
    if event_type != "ONIMBOTV2MESSAGEADD":
        return None

    data = event.get("data") if isinstance(event.get("data"), dict) else event
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    chat = data.get("chat") if isinstance(data.get("chat"), dict) else {}
    user = data.get("user") if isinstance(data.get("user"), dict) else {}

    if _as_bool(message.get("isSystem")) or _as_bool(user.get("bot")):
        return None

    text = str(message.get("text") or "").strip()
    dialog_id = str(chat.get("dialogId") or message.get("dialogId") or "").strip()
    if not text or not dialog_id:
        return None

    return {
        "text": text,
        "dialog_id": dialog_id,
        "message_id": message.get("id"),
        "author_id": message.get("authorId") or user.get("id"),
    }


def ask_internal_chat_api(
    message: str,
    *,
    api_url: str,
    api_key: str = "",
    chat_id: int | None = None,
    timeout: float = 120.0,
) -> tuple[str, int | None]:
    """Отправить вопрос в локальный RAG API; вернуть (answer, chat_id)."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    payload: dict[str, Any] = {"message": message}
    if chat_id is not None:
        payload["chat_id"] = chat_id

    with requests.post(
        f"{api_url.rstrip('/')}/api/chat",
        json=payload,
        headers=headers,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        body = response.json()
    answer = str(body.get("answer") or "").strip()
    if not answer:
        raise RuntimeError(body.get("error") or "RAG API вернул пустой ответ")
    returned_chat_id = body.get("chat_id")
    try:
        resolved_chat_id = int(returned_chat_id) if returned_chat_id is not None else chat_id
    except (TypeError, ValueError):
        resolved_chat_id = chat_id
    return answer, resolved_chat_id


def process_event(
    event: dict[str, Any],
    *,
    bitrix: Bitrix24Client,
    bot_id: int,
    bot_token: str,
    api_url: str,
    api_key: str = "",
    dialog_chats: dict[str, int] | None = None,
    offset_path: str | Path | None = None,
) -> bool:
    """Обработать одно событие и отправить ответ в тот же диалог."""
    parsed = extract_message_event(event)
    if not parsed:
        return False

    mapping = dialog_chats if dialog_chats is not None else {}
    dialog_id = parsed["dialog_id"]
    known_chat_id = mapping.get(dialog_id)

    logger.info("Получен вопрос из Битрикс24 dialogId=%s chat_id=%s", dialog_id, known_chat_id)
    answer, new_chat_id = ask_internal_chat_api(
        parsed["text"],
        api_url=api_url,
        api_key=api_key,
        chat_id=known_chat_id,
    )
    if new_chat_id is not None and mapping.get(dialog_id) != new_chat_id:
        mapping[dialog_id] = int(new_chat_id)
        if offset_path is not None:
            save_dialog_chats(offset_path, mapping)

    bitrix.send_message(
        bot_id=bot_id,
        bot_token=bot_token,
        dialog_id=dialog_id,
        text=answer,
    )
    logger.info("Ответ отправлен в Битрикс24 dialogId=%s", dialog_id)
    return True


def _next_offset(result: dict[str, Any]) -> int | None:
    raw = result.get("nextOffset") or result.get("next_offset")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def run_once(
    bitrix: Bitrix24Client,
    offset: int | None,
    limit: int = 100,
    *,
    dialog_chats: dict[str, int] | None = None,
    offset_path: str | Path | None = None,
) -> tuple[int | None, int]:
    """Получить пачку событий, обработать её и вернуть следующий offset."""
    if settings.BITRIX24_BOT_ID is None:
        raise RuntimeError("BITRIX24_BOT_ID не задан")
    if not settings.BITRIX24_BOT_TOKEN:
        raise RuntimeError("BITRIX24_BOT_TOKEN не задан")

    result = bitrix.get_events(
        bot_id=settings.BITRIX24_BOT_ID,
        bot_token=settings.BITRIX24_BOT_TOKEN,
        offset=offset,
        limit=limit,
    )
    events = result.get("events") or []
    processed = 0
    mapping = dialog_chats if dialog_chats is not None else {}
    for event in events:
        try:
            if process_event(
                event,
                bitrix=bitrix,
                bot_id=settings.BITRIX24_BOT_ID,
                bot_token=settings.BITRIX24_BOT_TOKEN,
                api_url=settings.BITRIX24_INTERNAL_API_URL,
                api_key=settings.BITRIX24_INTERNAL_API_KEY,
                dialog_chats=mapping,
                offset_path=offset_path,
            ):
                processed += 1
        except (requests.RequestException, Bitrix24Error, RuntimeError):
            logger.exception("Ошибка обработки события Битрикс24")

    return _next_offset(result), processed


def main() -> int:
    parser = argparse.ArgumentParser(description="Запустить polling-worker чат-бота Битрикс24.")
    parser.add_argument("--once", action="store_true", help="Выполнить один polling-цикл и завершиться")
    parser.add_argument("--limit", type=int, default=100, help="Размер пачки событий imbot.v2.Event.get")
    args = parser.parse_args()

    if not settings.BITRIX24_ENABLED:
        print("BITRIX24_ENABLED=false. Включите интеграцию в .env перед запуском worker.")
        return 1

    bitrix = Bitrix24Client(settings.BITRIX24_WEBHOOK_URL)
    offset_path = settings.BITRIX24_EVENT_OFFSET_PATH
    offset = load_offset(offset_path)
    dialog_chats = load_dialog_chats(offset_path)
    logger.info("Bitrix24 worker запущен, offset=%s, dialogs=%s", offset, len(dialog_chats))

    while True:
        try:
            next_offset, processed = run_once(
                bitrix,
                offset,
                limit=args.limit,
                dialog_chats=dialog_chats,
                offset_path=offset_path,
            )
            if next_offset is not None:
                offset = next_offset
                save_offset(offset_path, offset)
            logger.info("Цикл Bitrix24 завершён: обработано=%s, nextOffset=%s", processed, next_offset)

            if args.once:
                return 0
            time.sleep(max(1, settings.BITRIX24_POLL_INTERVAL_SECONDS))
        except KeyboardInterrupt:
            print("\nОстановка...")
            logger.info("Bitrix24 worker остановлен по KeyboardInterrupt")
            break
        except Exception:
            logger.exception("Ошибка в основном цикле Bitrix24 worker")
            if args.once:
                return 1
            time.sleep(5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
