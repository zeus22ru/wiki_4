#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Подготовка растровых изображений для OCR/vision: растеризация SVG, тайлинг.

Крупные схемы режутся на тайлы с перекрытием, чтобы не разорвать узлы и
стрелки. Для SVG выполняется безопасная растеризация в растр; сетевые и
файловые внешние ссылки при растеризации не разыменовываются.
"""

from __future__ import annotations

import io
from typing import List, Optional, Tuple

from config import settings, get_logger
from core.document_extraction.imaging import probe_image_size

logger = get_logger(__name__)

try:  # pragma: no cover
    from PIL import Image

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    PIL_AVAILABLE = False


def rasterize_svg(data: bytes, *, scale: float = 2.0) -> Optional[bytes]:
    """Растеризовать SVG в PNG. Возвращает None, если нет растеризатора."""
    # cairosvg не разыменовывает внешние ссылки по умолчанию при таком вызове.
    try:  # pragma: no cover
        import cairosvg

        png = cairosvg.svg2png(bytestring=data, scale=scale)
        return png
    except Exception:
        pass
    try:  # pragma: no cover
        import fitz  # PyMuPDF

        doc = fitz.open(stream=data, filetype="svg")
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return pix.tobytes("png")
    except Exception:
        return None


def tile_image_bytes(
    data: bytes,
    *,
    tile_size: Optional[int] = None,
    overlap: Optional[int] = None,
    max_tiles: int = 64,
) -> List[bytes]:
    """Нарезать изображение на тайлы с перекрытием. Мелкое — вернуть целиком."""
    if not PIL_AVAILABLE:
        return [data]
    tile_size = int(tile_size or getattr(settings, "VISUAL_TILE_SIZE", 1600))
    overlap = int(overlap if overlap is not None else getattr(settings, "VISUAL_TILE_OVERLAP", 160))
    overlap = max(0, min(overlap, tile_size // 2))
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width <= tile_size and height <= tile_size:
                return [data]
            step = tile_size - overlap
            tiles: List[bytes] = []
            y = 0
            while y < height and len(tiles) < max_tiles:
                x = 0
                while x < width and len(tiles) < max_tiles:
                    box = (x, y, min(x + tile_size, width), min(y + tile_size, height))
                    tile = img.crop(box)
                    buf = io.BytesIO()
                    tile.save(buf, format="PNG")
                    tiles.append(buf.getvalue())
                    if x + tile_size >= width:
                        break
                    x += step
                if y + tile_size >= height:
                    break
                y += step
            return tiles or [data]
    except Exception as exc:
        logger.warning("Тайлинг не удался: %s", exc)
        return [data]


def rasterize_if_needed(
    data: bytes,
    *,
    mime_type: str = "",
    tile_size: Optional[int] = None,
    overlap: Optional[int] = None,
) -> Tuple[bytes, List[bytes]]:
    """Вернуть (подготовленные байты, список тайлов).

    Для SVG — растеризация (если доступна). Для крупного растра — тайлинг.
    """
    prepared = data
    if mime_type == "image/svg+xml" or data[:5] == b"<?xml":
        raster = rasterize_svg(data)
        if raster:
            prepared = raster
    tiles = tile_image_bytes(prepared, tile_size=tile_size, overlap=overlap)
    return prepared, tiles


def exceeds_pixel_budget(data: bytes) -> bool:
    """Превышает ли изображение лимит пикселей (ТЗ §18, VISUAL_MAX_RASTER_PIXELS)."""
    width, height = probe_image_size(data)
    if width is None or height is None:
        return False
    budget = int(getattr(settings, "VISUAL_MAX_RASTER_PIXELS", 40_000_000))
    return width * height > budget
