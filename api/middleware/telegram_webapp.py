#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка подписанных данных запуска Telegram Mini App."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class TelegramWebAppIdentity:
    """Доверенные поля пользователя после проверки Telegram initData."""

    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    auth_date: int
    query_id: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.user_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "language_code": self.language_code,
        }


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 3600,
    now: int | None = None,
) -> TelegramWebAppIdentity:
    """Проверить HMAC, свежесть и user payload из Telegram.WebApp.initData."""
    if not isinstance(init_data, str) or not init_data.strip():
        raise ValueError("Пустые данные Telegram")
    if not isinstance(bot_token, str) or not bot_token.strip():
        raise ValueError("Токен Telegram не настроен")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("Некорректные данные Telegram") from exc

    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("Повторяющиеся поля Telegram")

    values = dict(pairs)
    received_hash = values.pop("hash", "")
    if not received_hash or len(received_hash) != 64:
        raise ValueError("Отсутствует подпись Telegram")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.strip().encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash.lower()):
        raise ValueError("Неверная подпись Telegram")

    try:
        auth_date = int(values.get("auth_date", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректная дата авторизации Telegram") from exc

    current_time = int(time.time()) if now is None else int(now)
    max_age = max(1, int(max_age_seconds))
    if auth_date > current_time + 30:
        raise ValueError("Дата авторизации Telegram находится в будущем")
    if current_time - auth_date > max_age:
        raise ValueError("Сессия Telegram устарела")

    try:
        user = json.loads(values.get("user", ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Некорректный пользователь Telegram") from exc
    if not isinstance(user, dict) or isinstance(user.get("id"), bool):
        raise ValueError("Некорректный пользователь Telegram")
    try:
        telegram_user_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Некорректный ID пользователя Telegram") from exc
    if telegram_user_id <= 0:
        raise ValueError("Некорректный ID пользователя Telegram")

    def optional_text(key: str) -> str | None:
        value = user.get(key)
        return value.strip()[:255] if isinstance(value, str) and value.strip() else None

    return TelegramWebAppIdentity(
        user_id=telegram_user_id,
        username=optional_text("username"),
        first_name=optional_text("first_name"),
        last_name=optional_text("last_name"),
        language_code=optional_text("language_code"),
        auth_date=auth_date,
        query_id=values.get("query_id") or None,
    )
