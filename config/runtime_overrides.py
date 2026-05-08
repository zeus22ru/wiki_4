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
import os
from pathlib import Path
from typing import Any


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
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)


def apply_overrides(settings_obj: Any, overrides: dict[str, Any]) -> None:
    """Применить overrides к уже созданному объекту settings (in-memory)."""
    for key, value in (overrides or {}).items():
        if not isinstance(key, str) or not key:
            continue
        try:
            setattr(settings_obj, key, value)
        except Exception:
            continue

