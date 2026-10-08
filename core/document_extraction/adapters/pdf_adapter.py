#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Адаптер PDF: текстовый слой + рендеринг страниц для сканов и векторных схем.

Текст берётся существующим/совместимым адаптером (pdfplumber). Страницы, где
содержательный объект может быть только в пикселях (скан, векторная схема,
график), рендерятся через ``pypdfium2`` (PDFium), если он доступен. Пустая
страница не превращается в «полное извлечение» — ставится ``page_fallback``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import (
    ExtractionBlock,
    ExtractionResult,
    Locator,
    VisualOccurrence,
    make_occurrence_id,
    make_source_id,
    stable_hash,
)
from ..imaging import detect_mime_from_bytes, probe_image_size

try:  # pragma: no cover
    import pdfplumber

    PDFPLUMBER_AVAILABLE = True
except Exception:  # pragma: no cover
    pdfplumber = None  # type: ignore
    PDFPLUMBER_AVAILABLE = False

try:  # pragma: no cover
    import pypdfium2 as pdfium

    PDFIUM_AVAILABLE = True
except Exception:  # pragma: no cover
    pdfium = None  # type: ignore
    PDFIUM_AVAILABLE = False


class PdfSourceAdapter:
    name = "pdf"
    version = "1"
    extensions = (".pdf",)

    #: Страница ниже этого порога символов считается «без текстового слоя».
    text_layer_min_chars = 12

    def extract(self, source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        path = Path(source)
        options = options or {}
        rel_path = str(options.get("relative_path") or path.name)
        source_id = make_source_id(rel_path)
        result = ExtractionResult(
            source_id=source_id, title=path.stem, source_type="pdf",
            source_path=rel_path, adapter_version=self.version,
        )
        if not PDFPLUMBER_AVAILABLE:
            result.status = "unsupported"
            result.add_diagnostic("pdf_lib_missing", "Не установлен pdfplumber")
            return result

        render_dpi = int(options.get("pdf_render_dpi", 200) or 200)
        max_pages = int(options.get("max_pages", 300) or 300)
        want_render = bool(options.get("render_pages", True))
        renderer = PdfPageRenderer(dpi=render_dpi) if (want_render and PDFIUM_AVAILABLE) else None

        blocks: List[ExtractionBlock] = []
        occurrences: List[VisualOccurrence] = []
        order = 0
        page_texts: List[str] = []
        processed = 0
        try:
            with pdfplumber.open(path) as pdf:
                total = len(pdf.pages)
                if total > max_pages:
                    result.add_diagnostic(
                        "page_limit", f"Обнаружено {total} стр., обработано {max_pages}",
                        detected=total, processed=max_pages,
                    )
                title = ""
                for page_index, page in enumerate(pdf.pages, 1):
                    if page_index > max_pages:
                        break
                    processed = page_index
                    try:
                        text = page.extract_text() or ""
                    except Exception as exc:  # pragma: no cover
                        result.add_diagnostic("page_error", f"Стр. {page_index}: {exc}", page=page_index)
                        text = ""
                    text = text.strip()
                    page_texts.append(text)
                    if text:
                        blocks.append(ExtractionBlock(
                            block_id=f"b{order}", kind="paragraph", order=order, text=text,
                            section_path=title, locator=Locator(page=page_index, block_order=order),
                        ))
                        order += 1
                        if not title:
                            title = text.splitlines()[0][:100]
                    needs_visual = len(text) < self.text_layer_min_chars or bool(
                        getattr(page, "images", None)
                    ) or self._has_vector_drawings(page)
                    if needs_visual and renderer is not None:
                        rendered = renderer.render_page(path, page_index)
                        if rendered is not None:
                            data, width, height = rendered
                            occ = VisualOccurrence(
                                occurrence_id="", source_id=source_id,
                                locator=Locator(page=page_index, block_order=order, coordinate_space="pixels"),
                                image_bytes=data, mime_type=detect_mime_from_bytes(data, ".png"),
                                width=width, height=height,
                                visual_type="unknown",
                                extraction_quality="rendered" if text else "page_fallback",
                            )
                            occurrences.append(occ)
                            blocks.append(ExtractionBlock(
                                block_id=f"b{order}", kind="page_fallback" if not text else "visual",
                                order=order, section_path=title,
                                locator=Locator(page=page_index, block_order=order),
                            ))
                            order += 1
                    if renderer is None and needs_visual and not text:
                        result.add_diagnostic("renderer_unavailable", f"Стр. {page_index} без текста", page=page_index)
                if title:
                    result.title = title
        except Exception as exc:
            result.status = "failed"
            result.add_diagnostic("pdf_error", str(exc))
            return result

        revision = stable_hash("|".join(page_texts), length=32)
        for occ in occurrences:
            occ.occurrence_id = make_occurrence_id(source_id, revision, occ.locator.key())
        result.blocks = blocks
        result.visual_occurrences = occurrences
        result.source_revision = revision
        if not blocks and not occurrences:
            result.status = "empty"
        elif renderer is None and any(b.kind == "page_fallback" for b in blocks):
            result.status = "partial"
        else:
            result.status = "success"
        return result

    @staticmethod
    def _has_vector_drawings(page: Any) -> bool:
        try:
            rects = getattr(page, "rects", None) or []
            curves = getattr(page, "curves", None) or []
            lines = getattr(page, "lines", None) or []
            return len(rects) + len(curves) + len(lines) > 25
        except Exception:
            return False


class PdfPageRenderer:
    """Рендеринг страниц PDF в PNG через pypdfium2 (PDFium)."""

    def __init__(self, *, dpi: int = 200) -> None:
        self.dpi = max(72, int(dpi))
        self._doc = None

    def render_page(self, path: Path, page_number: int) -> Optional[tuple]:
        if not PDFIUM_AVAILABLE:
            return None
        try:
            if self._doc is None:
                self._doc = pdfium.PdfDocument(str(path))
            page = self._doc[page_number - 1]
            scale = self.dpi / 72.0
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            import io

            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            data = buf.getvalue()
            width, height = probe_image_size(data)
            return (data, width, height)
        except Exception:
            return None
