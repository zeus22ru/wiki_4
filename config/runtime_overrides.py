#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хранение и применение runtime-override настроек (админка).

Идея:
- .env остаётся источником “по умолчанию” и для деплоя;
- админка пишет overrides в JSON-файл;
- при старте приложения overrides применяются поверх env;
- при изменении из админки overrides сразу применяются к объекту settings.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from .validation import validate_chunk_bounds

logger = logging.getLogger(__name__)

# Общий lock для чтения-изменения-записи overrides (админка)
overrides_lock = threading.Lock()


def overrides_path() -> Path:
    raw = os.getenv("SETTINGS_OVERRIDES_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(os.getenv("DATA_DIR", "./data")) / "settings_overrides.json"


def load_overrides() -> dict[str, Any]:
    path = overrides_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def save_overrides(data: dict[str, Any]) -> None:
    """Атомарная запись overrides через уникальный временный файл."""
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _coerce_to_type(current: Any, value: Any) -> Any:
    """Привести значение override к типу текущего значения настройки."""
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
        raise ValueError(f"некорректное булево: {value!r}")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, list):
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return [part.strip() for part in str(value).split(",") if part.strip()]
    if current is None:
        return value
    return type(current)(value) if value is not None else value


def apply_overrides(settings_obj: Any, overrides: dict[str, Any]) -> None:
    """Применить overrides только к объявленным полям Settings с приведением типа."""
    settings_type = type(settings_obj)
    pending: dict[str, Any] = {}

    for key, value in (overrides or {}).items():
        if not isinstance(key, str) or not key:
            continue
        if not hasattr(settings_type, key):
            logger.warning("Пропущен неизвестный override-ключ: %s", key)
            continue
        current = getattr(settings_obj, key)
        try:
            pending[key] = _coerce_to_type(current, value)
        except Exception as exc:
            logger.warning("Не удалось привести override %s=%r: %s", key, value, exc)

    # Инвариант чанкинга: игнорируем только проблемные ключи, не все overrides
    chunk_size = pending.get("CHUNK_SIZE", getattr(settings_obj, "CHUNK_SIZE", None))
    chunk_overlap = pending.get("CHUNK_OVERLAP", getattr(settings_obj, "CHUNK_OVERLAP", None))
    try:
        if chunk_size is not None and chunk_overlap is not None:
            validate_chunk_bounds(int(chunk_size), int(chunk_overlap))
    except ValueError as exc:
        logger.warning("Инвариант чанкинга нарушен, CHUNK_* overrides пропущены: %s", exc)
        pending.pop("CHUNK_SIZE", None)
        pending.pop("CHUNK_OVERLAP", None)

    for key, value in pending.items():
        try:
            setattr(settings_obj, key, value)
        except Exception as exc:
            logger.warning("Не удалось применить override %s: %s", key, exc)
