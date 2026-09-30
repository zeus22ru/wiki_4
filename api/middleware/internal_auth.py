#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка доверенных внутренних запросов (Telegram/Bitrix воркеры)."""

from __future__ import annotations

import hmac

from flask import request

from config import settings


def is_trusted_internal_request() -> bool:
    """True, если заголовок X-API-Key совпадает (hmac.compare_digest) с settings.TELEGRAM_INTERNAL_API_KEY
    и этот ключ непустой. Пустой ключ никогда не считается доверенным."""
    expected = (getattr(settings, "TELEGRAM_INTERNAL_API_KEY", None) or "").strip()
    if not expected:
        return False
    provided = (request.headers.get("X-API-Key") or "").strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)
