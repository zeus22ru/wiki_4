#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регистрация чат-бота Битрикс24 через imbot.v2.Bot.register."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from config import settings  # noqa: E402
from integrations.bitrix24 import Bitrix24Client, Bitrix24Error  # noqa: E402


def _prompt_secret(value: str | None, label: str) -> str:
    if value:
        return value.strip()
    env_token = settings.BITRIX24_BOT_TOKEN.strip()
    if env_token:
        return env_token
    entered = getpass.getpass(label).strip()
    return entered or secrets.token_urlsafe(32)


def main() -> int:
    parser = argparse.ArgumentParser(description="Зарегистрировать чат-бота Битрикс24 imbot.v2.")
    parser.add_argument("--code", default="wiki_qa_bot", help="Уникальный код бота на портале")
    parser.add_argument("--name", default="Wiki QA Bot", help="Имя бота в Битрикс24")
    parser.add_argument("--work-position", default="База знаний", help="Должность/описание бота")
    parser.add_argument("--bot-token", help="Секретный токен бота. Если не указан, будет запрошен или сгенерирован")
    args = parser.parse_args()

    if not settings.BITRIX24_WEBHOOK_URL:
        print("BITRIX24_WEBHOOK_URL не задан. Укажите входящий вебхук Битрикс24 в .env.")
        return 1

    bot_token = _prompt_secret(args.bot_token, "BITRIX24_BOT_TOKEN (Enter = сгенерировать): ")
    client = Bitrix24Client(settings.BITRIX24_WEBHOOK_URL)

    try:
        result = client.register_bot(
            code=args.code,
            name=args.name,
            work_position=args.work_position,
            bot_token=bot_token,
        )
    except (Bitrix24Error, ValueError) as exc:
        print(f"Не удалось зарегистрировать бота: {exc}")
        return 1

    bot = result.get("bot") if isinstance(result, dict) else {}
    bot_id = bot.get("id") if isinstance(bot, dict) else None
    print("Бот Битрикс24 зарегистрирован.")
    if bot_id:
        print(f"BITRIX24_BOT_ID={bot_id}")
    print(f"BITRIX24_BOT_TOKEN={bot_token}")
    print("Запишите эти значения в .env и запустите scripts/bitrix24_bot_worker.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
