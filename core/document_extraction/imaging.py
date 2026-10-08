#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вспомогательные функции для работы с растровыми изображениями.

Мягко деградируют при отсутствии Pillow: там, где размеры неизвестны,
возвращаются ``None``, а не выдуманные значения.
"""

from __future__ import annotations

import io
from typing import Optional, Tuple

try:  # pragma: no cover - зависимость окружения
    from PIL import Image

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    PIL_AVAILABLE = False

#: Магические сигнатуры → MIME (без декодирования полного изображения).
_MAGIC_MIME = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

_EXT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".emf": "image/emf",
    ".wmf": "image/wmf",
}

RASTER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")


def detect_mime_from_bytes(data: bytes, fallback_ext: str = "") -> str:
    """Определить MIME по магическим байтам, иначе по расширению."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime in _MAGIC_MIME:
        if data.startswith(magic):
            return mime
    if data[:5] == b"<?xml" or data[:4] == b"<svg":
        return "image/svg+xml"
    ext = (fallback_ext or "").lower()
    if not ext.startswith("."):
        ext = "." + ext if ext else ""
    return _EXT_MIME.get(ext, "application/octet-stream")


def probe_image_size(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """Вернуть (width, height) без полного декодирования, если возможно."""
    if not data:
        return (None, None)
    if PIL_AVAILABLE:
        try:
            with Image.open(io.BytesIO(data)) as img:
                return (int(img.width), int(img.height))
        except Exception:
            pass
    return _probe_size_headers(data)


def _probe_size_headers(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """Минимальный парсер размеров для PNG/GIF/BMP/JPEG (без Pillow)."""
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return (width, height)
        if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
            width = int.from_bytes(data[6:8], "little")
            height = int.from_bytes(data[8:10], "little")
            return (width, height)
        if data.startswith(b"BM") and len(data) >= 26:
            width = int.from_bytes(data[18:22], "little", signed=True)
            height = abs(int.from_bytes(data[22:26], "little", signed=True))
            return (width, height)
    except Exception:
        return (None, None)
    return (None, None)


def is_svg(data: bytes, mime: str = "") -> bool:
    return mime == "image/svg+xml" or data[:5] == b"<?xml" and b"<svg" in data[:1024] or data[:4] == b"<svg"


def is_raster_ext(ext: str) -> bool:
    value = (ext or "").lower()
    return value in RASTER_EXTENSIONS
