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


def ask_internal_chat_api(message: str, *, api_url: str, api_key: str = "", timeout: float = 120.0) -> str:
    """Отправить вопрос в локальный RAG API и вернуть только текст ответа."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    response = requests.post(
        f"{api_url.rstrip('/')}/api/chat",
        json={"message": message},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    answer = str(body.get("answer") or "").strip()
    if not answer:
        raise RuntimeError(body.get("error") or "RAG API вернул пустой ответ")
    return answer


def process_event(
    event: dict[str, Any],
    *,
    bitrix: Bitrix24Client,
    bot_id: int,
    bot_token: str,
    api_url: str,
    api_key: str = "",
) -> bool:
    """Обработать одно событие и отправить ответ в тот же диалог."""
    parsed = extract_message_event(event)
    if not parsed:
        return False

    logger.info("Получен вопрос из Битрикс24 dialogId=%s", parsed["dialog_id"])
    answer = ask_internal_chat_api(parsed["text"], api_url=api_url, api_key=api_key)
    bitrix.send_message(
        bot_id=bot_id,
        bot_token=bot_token,
        dialog_id=parsed["dialog_id"],
        text=answer,
    )
    logger.info("Ответ отправлен в Битрикс24 dialogId=%s", parsed["dialog_id"])
    return True


def _next_offset(result: dict[str, Any]) -> int | None:
    raw = result.get("nextOffset") or result.get("next_offset")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def run_once(bitrix: Bitrix24Client, offset: int | None, limit: int = 100) -> tuple[int | None, int]:
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
    for event in events:
        try:
            if process_event(
                event,
                bitrix=bitrix,
                bot_id=settings.BITRIX24_BOT_ID,
                bot_token=settings.BITRIX24_BOT_TOKEN,
                api_url=settings.BITRIX24_INTERNAL_API_URL,
                api_key=settings.BITRIX24_INTERNAL_API_KEY,
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
    offset = load_offset(settings.BITRIX24_EVENT_OFFSET_PATH)
    logger.info("Bitrix24 worker запущен, offset=%s", offset)

    while True:
        next_offset, processed = run_once(bitrix, offset, limit=args.limit)
        if next_offset is not None:
            offset = next_offset
            save_offset(settings.BITRIX24_EVENT_OFFSET_PATH, offset)
        logger.info("Цикл Bitrix24 завершён: обработано=%s, nextOffset=%s", processed, next_offset)

        if args.once:
            return 0
        time.sleep(max(1, settings.BITRIX24_POLL_INTERVAL_SECONDS))


if __name__ == "__main__":
    raise SystemExit(main())
