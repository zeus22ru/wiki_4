#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Адаптер старых офисных форматов (.doc/.xls) через portable-конвертацию копии.

Текст извлекается существующим fallback (docx2txt / xlrd), визуальные объекты —
через конвертацию копии в DOCX/XLSX/PDF и последующее извлечение/рендеринг.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from ..base import ExtractionResult, make_source_id, stable_hash
from ..office_renderer import OfficeRenderer, OfficeRendererError


class ConvertSourceAdapter:
    name = "convert"
    version = "1"
    extensions = (".doc", ".xls")

    def __init__(self, renderer: Optional[OfficeRenderer] = None) -> None:
        self.renderer = renderer or OfficeRenderer()

    def extract(self, source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        path = Path(source)
        options = options or {}
        rel_path = str(options.get("relative_path") or path.name)
        source_id = make_source_id(rel_path)
        result = ExtractionResult(
            source_id=source_id, title=path.stem, source_type="office_legacy",
            source_path=rel_path, adapter_version=self.version,
        )

        # 1. Сначала текстовый fallback, он работает и без renderer.
        text = self._text_fallback(path)
        if text:
            from ..base import ExtractionBlock, Locator

            result.blocks.append(ExtractionBlock(
                block_id="b0", kind="paragraph", order=0, text=text,
                locator=Locator(block_order=0),
            ))

        # 2. Конвертация копии для визуальных объектов.
        if not self.renderer.available():
            result.add_diagnostic("renderer_unavailable", "LibreOffice portable не найден")
            result.status = "partial" if text else "unsupported"
            result.source_revision = stable_hash(str(path.stat().st_size if path.exists() else 0), length=32)
            return result

        target_ext = "docx" if path.suffix.lower() == ".doc" else "xlsx"
        try:
            with tempfile.TemporaryDirectory(prefix="kb_convert_") as tmp:
                converted = self.renderer.convert(path, target_ext, out_dir=Path(tmp))
                nested = self._extract_converted(converted, rel_path, options)
        except OfficeRendererError as exc:
            result.add_diagnostic(exc.code, exc.message)
            result.status = "partial" if text else "failed"
            return result

        # Объединяем: текстовые блоки из fallback + визуальные из конвертации.
        offset = len(result.blocks)
        for blk in nested.blocks:
            if blk.kind == "visual" or not blk.text:
                continue
            blk.order += offset
            blk.block_id = f"b{blk.order}"
            result.blocks.append(blk)
        result.visual_occurrences.extend(nested.visual_occurrences)
        result.dependencies.append({"kind": "converted_copy", "source": rel_path, "target": target_ext})
        result.status = "partial" if nested.status == "partial" else ("success" if result.blocks or result.visual_occurrences else "empty")
        result.source_revision = stable_hash(str(path.stat().st_size), length=32)
        return result

    def _extract_converted(self, converted: Path, rel_path: str, options: Dict[str, Any]) -> ExtractionResult:
        if converted.suffix.lower() == ".docx":
            from .docx_adapter import DocxSourceAdapter

            return DocxSourceAdapter().extract(converted, options=options)
        from .xlsx_adapter import XlsxSourceAdapter

        return XlsxSourceAdapter().extract(converted, options=options)

    @staticmethod
    def _text_fallback(path: Path) -> str:
        # DOCX-в-ZIP с неверным расширением .doc.
        import zipfile

        if zipfile.is_zipfile(path):
            try:
                from docx import Document

                doc = Document(path)
                parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                return "\n".join(parts)
            except Exception:
                pass
        try:
            import docx2txt

            return (docx2txt.process(str(path)) or "").strip()
        except Exception:
            return ""
