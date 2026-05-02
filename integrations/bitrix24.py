#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Клиент REST API Битрикс24 для чат-ботов imbot.v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


class Bitrix24Error(RuntimeError):
    """Ошибка вызова REST API Битрикс24."""


@dataclass
class Bitrix24Client:
    """Минимальный клиент для методов imbot.v2 через входящий вебхук."""

    webhook_url: str
    timeout: float = 20.0

    def __post_init__(self) -> None:
        self.webhook_url = (self.webhook_url or "").strip()
        if not self.webhook_url:
            raise ValueError("BITRIX24_WEBHOOK_URL не задан")

    def method_url(self, method: str) -> str:
        """Собрать URL вида https://portal/rest/user/token/method."""
        return f"{self.webhook_url.rstrip('/')}/{method}"

    def call_method(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Вызвать REST-метод Битрикс24 и вернуть поле result."""
        try:
            response = requests.post(
                self.method_url(method),
                json=payload or {},
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            raise Bitrix24Error(f"Ошибка HTTP при вызове {method}: {exc}") from exc
        except ValueError as exc:
            raise Bitrix24Error(f"Битрикс24 вернул не JSON для {method}") from exc

        if body.get("error"):
            description = body.get("error_description") or body.get("error")
            raise Bitrix24Error(f"Ошибка Битрикс24 {method}: {description}")

        return body.get("result", {})

    def register_bot(self, *, code: str, name: str, bot_token: str, work_position: str = "AI Assistant") -> dict[str, Any]:
        """Зарегистрировать чат-бота в режиме polling (`eventMode=fetch`)."""
        payload = {
            "botToken": bot_token,
            "fields": {
                "code": code,
                "type": "bot",
                "eventMode": "fetch",
                "properties": {
                    "name": name,
                    "workPosition": work_position,
                },
            },
        }
        return self.call_method("imbot.v2.Bot.register", payload)

    def get_events(
        self,
        *,
        bot_id: int,
        bot_token: str,
        offset: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Получить очередь событий чат-бота через imbot.v2.Event.get."""
        payload: dict[str, Any] = {
            "botId": bot_id,
            "botToken": bot_token,
            "limit": limit,
        }
        if offset is not None:
            payload["offset"] = offset
        return self.call_method("imbot.v2.Event.get", payload)

    def send_message(
        self,
        *,
        bot_id: int,
        bot_token: str,
        dialog_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Отправить ответ от имени чат-бота в диалог Битрикс24."""
        payload = {
            "botId": bot_id,
            "botToken": bot_token,
            "dialogId": dialog_id,
            "fields": {
                "message": text,
                "system": False,
                "urlPreview": True,
            },
        }
        return self.call_method("imbot.v2.Chat.Message.send", payload)
