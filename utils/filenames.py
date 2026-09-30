#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Безопасные имена файлов с сохранением кириллицы и расширения."""

from __future__ import annotations

import re
from pathlib import PurePath

# Длина имени с запасом под типичные FS-ограничения (255 байт в UTF-8).
_MAX_NAME_LEN = 180
# Буквы (включая кириллицу), цифры, точка, дефис, подчёркивание.
_UNSAFE_CHARS = re.compile(r"[^\w.\-]+", re.UNICODE)
_MULTI_UNDERSCORE = re.compile(r"_+")


def file_extension(name: str) -> str:
    """Расширение в нижнем регистре без точки; '' если нет."""
    if not name or not str(name).strip():
        return ""
    base = PurePath(str(name).replace("\\", "/")).name
    if not base or "." not in base:
        return ""
    # Имя вроде ".env" / ".gitignore" — без расширения в смысле загрузки.
    if base.startswith(".") and base.count(".") == 1:
        return ""
    ext = base.rsplit(".", 1)[-1]
    if not ext or any(ch in ext for ch in "/\\"):
        return ""
    return ext.lower()


def safe_filename(name: str, *, default: str = "file") -> str:
    """Сохраняет кириллицу и расширение, убирает путь и опасные символы, ограничивает длину.

    'Отчёт (финал).PDF' -> 'Отчёт_финал.pdf'; никогда не возвращает имя без расширения,
    если оно было в исходном.
    """
    raw = str(name or "").strip()
    if not raw:
        return default

    base = PurePath(raw.replace("\\", "/")).name
    if not base or base in {".", ".."}:
        return default

    ext = file_extension(base)
    stem = base[: -(len(ext) + 1)] if ext else base

    stem = _UNSAFE_CHARS.sub("_", stem)
    stem = _MULTI_UNDERSCORE.sub("_", stem).strip("._")
    if not stem:
        stem = default

    if ext:
        max_stem = max(1, _MAX_NAME_LEN - len(ext) - 1)
        stem = stem[:max_stem].rstrip("._") or default
        return f"{stem}.{ext}"

    return stem[:_MAX_NAME_LEN].rstrip("._") or default
