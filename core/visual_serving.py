#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Безопасная выдача изображений базы знаний (ТЗ §16.2).

Модуль не зависит от Flask: возвращает байты, MIME и ETag, а маршрут лишь
оборачивает это в HTTP-ответ. Не принимает пути файловой системы из запроса —
ID разрешается исключительно через каталог.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Optional

from config import settings, get_logger
from core.document_extraction.imaging import detect_mime_from_bytes
from core.kb_catalog import KnowledgeCatalog, get_catalog
from core.visual_assets import VisualAssetStore

logger = get_logger(__name__)

#: Допустимые варианты выдачи.
VARIANTS = ("original", "preview", "thumbnail")

_THUMB_MAX = 320
_PREVIEW_MAX = 1280


@dataclass
class ImageResponse:
    data: bytes
    mime_type: str
    etag: str
    error_code: Optional[str] = None
    download_only: bool = False  # для активного SVG и др. исполняемых форматов


class KnowledgeImageService:
    def __init__(
        self,
        *,
        catalog: Optional[KnowledgeCatalog] = None,
        assets: Optional[VisualAssetStore] = None,
    ) -> None:
        self.assets = assets or VisualAssetStore()
        self.catalog = catalog or self.assets.catalog

    def resolve(self, occurrence_id: str, variant: str = "original") -> ImageResponse:
        if variant not in VARIANTS:
            variant = "original"
        occ = self.catalog.get_occurrence(occurrence_id)
        if not occ:
            return ImageResponse(b"", "text/plain", "none", error_code="not_found")
        asset_id = occ.get("asset_id")
        if not asset_id:
            return ImageResponse(b"", "text/plain", "none", error_code="no_asset")
        data = self.assets.read(asset_id)
        if data is None:
            return ImageResponse(b"", "text/plain", "none", error_code="asset_unavailable")

        mime = detect_mime_from_bytes(data)
        etag = '"' + hashlib.sha256(data).hexdigest()[:32] + f'-{variant}"'

        # SVG и другие исполняемые форматы не отдаём inline: конвертируем в растр,
        # оригинал доступен только на скачивание.
        download_only = mime in ("image/svg+xml",)
        if mime == "image/svg+xml" or variant != "original":
            rendered = self._render_variant(data, mime, variant)
            if rendered is not None:
                return ImageResponse(rendered, "image/png", etag)
            if variant != "original":
                # не смогли уменьшить — отдаём оригинал
                return ImageResponse(data, mime, etag, download_only=download_only)
            return ImageResponse(data, mime, etag, download_only=True)
        return ImageResponse(data, mime, etag)

    def _render_variant(self, data: bytes, mime: str, variant: str) -> Optional[bytes]:
        if variant == "original":
            # Нужен только растр для SVG.
            if mime != "image/svg+xml":
                return None
            from core.imaging_utils import rasterize_svg

            return rasterize_svg(data)
        max_side = _THUMB_MAX if variant == "thumbnail" else _PREVIEW_MAX
        try:
            from PIL import Image

            if mime == "image/svg+xml":
                from core.imaging_utils import rasterize_svg

                raster = rasterize_svg(data)
                if raster is None:
                    return None
                data = raster
            with Image.open(io.BytesIO(data)) as img:
                img = img.convert("RGBA")
                img.thumbnail((max_side, max_side))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
        except Exception as exc:
            logger.warning("Не удалось построить вариант %s: %s", variant, exc)
            return None
