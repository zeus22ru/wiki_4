#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Оркестрация визуальной индексации (ТЗ §5, §12, §13).

Связывает извлечение (SourceAdapter) с хранилищем ассетов, OCR, vision-анализом
и построением поисковых визуальных чанков. Ошибка отдельной картинки не роняет
обработку источника: результат помечается partial, а неуспех фиксируется в
диагностике (ТЗ §19). Кэш OCR/vision привязан к asset_id и хэшу параметров.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import settings, get_logger
from core.document_extraction.base import ExtractionResult, VisualOccurrence
from core.imaging_utils import rasterize_if_needed, tile_image_bytes
from core.kb_catalog import KnowledgeCatalog, get_catalog
from core.ocr import OCRProvider, OCRResult
from core.visual_analysis import VisualAnalysis, VisualAnalyzer
from core.visual_assets import VisualAssetStore

logger = get_logger(__name__)


@dataclass
class VisualChunk:
    """Визуальный чанк для поиска (ТЗ §12)."""

    chunk_id: str
    text: str          # отображаемый evidence text
    embed_text: str    # текст для эмбеддинга
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualIndexResult:
    source_id: str
    chunks: List[VisualChunk] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "success"
    counters: Dict[str, int] = field(default_factory=dict)

    def add_diagnostic(self, code: str, **extra: Any) -> None:
        entry = {"code": code}
        entry.update(extra)
        self.diagnostics.append(entry)


def _cache_key(*parts: Any) -> str:
    payload = "␟".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_search_text(text: str) -> str:
    """Поисковая нормализация: переменные части только в отдельном поле (ТЗ §11.4)."""
    if not text:
        return ""
    normalized = re.sub(r"\b\d{2}-\d{8}\b", "<номер>", text)
    normalized = re.sub(r"\b\d{6,}\b", "<номер>", normalized)
    return normalized


class VisualIndexer:
    """Преобразует ExtractionResult в визуальные ассеты и поисковые чанки."""

    def __init__(
        self,
        *,
        ocr: Optional[OCRProvider] = None,
        analyzer: Optional[VisualAnalyzer] = None,
        assets: Optional[VisualAssetStore] = None,
        catalog: Optional[KnowledgeCatalog] = None,
        index_namespace: Optional[str] = None,
    ) -> None:
        self.ocr = ocr
        self.analyzer = analyzer
        self.assets = assets or VisualAssetStore()
        self.catalog = catalog or self.assets.catalog
        self.index_namespace = index_namespace or getattr(settings, "KB_VISUAL_INDEX_NAMESPACE", "default")
        self.ocr_enabled = bool(getattr(settings, "OCR_CACHE_ENABLED", True))

    # --- публичный API --------------------------------------------------------

    def process(
        self,
        result: ExtractionResult,
        *,
        options: Optional[Dict[str, Any]] = None,
    ) -> VisualIndexResult:
        options = options or {}
        out = VisualIndexResult(source_id=result.source_id)
        self.catalog.upsert_source(
            source_id=result.source_id, title=result.title, source_type=result.source_type,
            source_path=result.source_path, source_url=result.source_url,
            revision=result.source_revision, status=result.status,
            index_namespace=self.index_namespace, metadata=result.metadata,
        )
        if result.dependencies:
            self.catalog.replace_dependencies(result.source_id, result.dependencies)

        max_occ = int(options.get("max_occurrences", getattr(settings, "VISUAL_MAX_OCCURRENCES_PER_SOURCE", 500)))
        max_ocr = int(options.get("max_ocr", 0))  # 0 = без лимита

        counters = {"occurrences": 0, "assets_stored": 0, "ocr_calls": 0, "ocr_cache_hits": 0,
                    "vision_calls": 0, "vision_cache_hits": 0, "no_text": 0, "failures": 0}
        occurrences = result.visual_occurrences
        if len(occurrences) > max_occ:
            out.add_diagnostic("occurrence_limit", detected=len(occurrences), processed=max_occ)
            out.status = "partial"
            occurrences = occurrences[:max_occ]

        for occ in occurrences:
            counters["occurrences"] += 1
            try:
                chunk = self._process_occurrence(occ, result, counters, out, options)
            except Exception as exc:  # изоляция ошибки одной картинки
                counters["failures"] += 1
                out.add_diagnostic("visual_processing_failed",
                                   occurrence_id=occ.occurrence_id, error=str(exc))
                out.status = "partial"
                continue
            if chunk is not None:
                out.chunks.append(chunk)

        out.counters = counters
        if result.status == "partial" and out.status == "success":
            out.status = "partial"
        return out

    # --- внутренняя логика ----------------------------------------------------

    def _process_occurrence(
        self,
        occ: VisualOccurrence,
        result: ExtractionResult,
        counters: Dict[str, int],
        out: VisualIndexResult,
        options: Dict[str, Any],
    ) -> Optional[VisualChunk]:
        # 1. Сохранить ассет (если есть байты).
        asset_id = occ.asset_id
        if occ.image_bytes:
            from core.document_extraction.imaging import detect_mime_from_bytes, probe_image_size

            mime = occ.mime_type or detect_mime_from_bytes(occ.image_bytes)
            w, h = probe_image_size(occ.image_bytes)
            asset_id = self.assets.store_original(
                occ.image_bytes, mime_type=mime, width=w, height=h,
            )
            occ.asset_id = asset_id
            counters["assets_stored"] += 1

        # 2. Occurrence в каталог.
        self.catalog.upsert_occurrence(
            occurrence_id=occ.occurrence_id, source_id=occ.source_id, asset_id=asset_id,
            locator=occ.locator.to_dict(), caption=occ.caption, alt=occ.alt,
            visual_type=occ.visual_type, visual_group_id=occ.visual_group_id,
            section_path=occ.section_path, is_stale=occ.is_stale,
            extraction_quality=occ.extraction_quality,
            context_before=occ.context_before, context_after=occ.context_after,
            index_namespace=self.index_namespace,
        )
        if asset_id is None:
            out.add_diagnostic("occurrence_without_asset", occurrence_id=occ.occurrence_id)
            return None

        # 3. OCR (с кэшем).
        ocr_result = self._run_ocr(asset_id, occ, counters, out)

        # 4. Vision-анализ (с кэшем).
        analysis = self._run_vision(asset_id, occ, counters, out)

        # 5. Поисковый визуальный чанк.
        return self._build_chunk(result, occ, asset_id, ocr_result, analysis, out)

    def _run_ocr(
        self, asset_id: str, occ: VisualOccurrence, counters: Dict[str, int], out: VisualIndexResult,
    ) -> OCRResult:
        data = self.assets.read(asset_id)
        if data is None:
            return OCRResult(status="unavailable", warnings=["asset_unreadable"])
        profile = getattr(settings, "OCR_MODEL_PROFILE", "cyrillic")
        fingerprint = self._ocr_fingerprint()
        params_hash = _cache_key(fingerprint, profile, "tile", getattr(settings, "VISUAL_TILE_SIZE", 1600),
                                 getattr(settings, "VISUAL_TILE_OVERLAP", 160))
        cached = self.catalog.get_analysis(asset_id, "ocr", params_hash) if self.ocr_enabled else None
        if cached and cached.get("status") in ("success", "no_text"):
            counters["ocr_cache_hits"] += 1
            return OCRResult.from_dict(json.loads(cached["result_json"]))

        if self.ocr is None:
            return OCRResult(status="unavailable", warnings=["ocr_not_configured"])

        # Растеризация SVG и тайлинг крупных изображений.
        prepared, tiles = rasterize_if_needed(data, mime_type=occ.mime_type)
        if len(tiles) <= 1:
            result = self.ocr.recognize(prepared)
            counters["ocr_calls"] += 1
        else:
            result = self._ocr_tiles(tiles, counters)

        if result.status == "no_text":
            counters["no_text"] += 1
        elif result.status in ("failed", "unavailable"):
            counters["failures"] += 1
            out.add_diagnostic("ocr_" + result.status, occurrence_id=occ.occurrence_id,
                               warnings=result.warnings)
        if self.ocr_enabled and result.status in ("success", "no_text"):
            analysis_id = _cache_key(asset_id, "ocr", params_hash)
            self.catalog.upsert_analysis(
                analysis_id=analysis_id, asset_id=asset_id, kind="ocr", status=result.status,
                engine=result.engine, engine_version=result.engine_version,
                model_fingerprint=result.model_fingerprint, profile=result.profile,
                params_hash=params_hash, result=result.to_dict(),
            )
        return result

    def _ocr_tiles(self, tiles: List[bytes], counters: Dict[str, int]) -> OCRResult:
        assert self.ocr is not None
        merged_text: List[str] = []
        all_blocks = []
        for tile in tiles:
            res = self.ocr.recognize(tile)
            counters["ocr_calls"] += 1
            if res.status == "success":
                for block in res.blocks:
                    merged_text.append(block.text)
                    all_blocks.append(block)
        if not all_blocks:
            return OCRResult(status="no_text")
        # Дедупликация одинаковых строк из зон перекрытия (ТЗ §8.4).
        seen: set = set()
        deduped = []
        for block in all_blocks:
            key = block.text.strip()
            if key and key not in seen:
                seen.add(key)
                deduped.append(block)
        text_raw = "\n".join(b.text for b in deduped)
        return OCRResult(status="success", engine=self.ocr.name, text_raw=text_raw, blocks=deduped)

    def _run_vision(
        self, asset_id: str, occ: VisualOccurrence, counters: Dict[str, int], out: VisualIndexResult,
    ) -> Optional[VisualAnalysis]:
        if self.analyzer is None or not bool(getattr(settings, "VISUAL_ANALYSIS_ENABLED", True)):
            return None
        data = self.assets.read(asset_id)
        if data is None:
            return None
        params_hash = self.analyzer.params_hash(mime_type=occ.mime_type or "image/png")
        cached = self.catalog.get_analysis(asset_id, "vision", params_hash)
        if cached and cached.get("status") == "success":
            counters["vision_cache_hits"] += 1
            return VisualAnalysis.from_dict(json.loads(cached["result_json"]))

        context = self._context_text(occ)
        analysis = self.analyzer.analyze(
            asset_id, data, mime_type=occ.mime_type or "image/png", context=context,
        )
        if analysis.status == "success":
            counters["vision_calls"] += 1
            self.catalog.upsert_analysis(
                analysis_id=_cache_key(asset_id, "vision", params_hash), asset_id=asset_id,
                kind="vision", status="success", engine="vision", model_fingerprint=self.analyzer.model,
                params_hash=params_hash, result=analysis.to_dict(),
            )
            if analysis.visual_type != "unknown":
                self.catalog.upsert_occurrence(
                    occurrence_id=occ.occurrence_id, source_id=occ.source_id, asset_id=asset_id,
                    locator=occ.locator.to_dict(), caption=occ.caption, alt=occ.alt,
                    visual_type=analysis.visual_type, visual_group_id=occ.visual_group_id,
                    section_path=occ.section_path, is_stale=occ.is_stale,
                    extraction_quality=occ.extraction_quality,
                    context_before=occ.context_before, context_after=occ.context_after,
                    index_namespace=self.index_namespace,
                )
        else:
            counters["failures"] += 1
            out.add_diagnostic("vision_" + analysis.status, occurrence_id=occ.occurrence_id,
                               warnings=analysis.warnings)
        return analysis

    def _build_chunk(
        self,
        result: ExtractionResult,
        occ: VisualOccurrence,
        asset_id: str,
        ocr: OCRResult,
        analysis: Optional[VisualAnalysis],
        out: VisualIndexResult,
    ) -> VisualChunk:
        section = occ.section_path or ""
        visual_type = (analysis.visual_type if analysis and analysis.visual_type != "unknown"
                       else occ.visual_type)
        parts: List[str] = []
        if result.title:
            parts.append(f"Источник: {result.title}")
        if section:
            parts.append(f"Раздел: {section}")
        if occ.caption:
            parts.append(f"Подпись: {occ.caption}")
        if occ.alt:
            parts.append(f"Alt: {occ.alt}")
        if visual_type and visual_type != "unknown":
            parts.append(f"Вид: {visual_type}")
        if ocr.text_raw:
            parts.append(f"Распознанный текст:\n{ocr.text_raw}")
        if getattr(ocr, "text_raw_alt", ""):
            parts.append(f"Второй проход (латиница/цифры):\n{ocr.text_raw_alt}")
        if analysis and analysis.summary:
            parts.append(f"Описание изображения:\n{analysis.summary}")
        if analysis:
            links = analysis.as_search_text()
            if links:
                parts.append(links)
        nearest = (occ.context_before or occ.context_after or "").strip()
        if nearest:
            parts.append(f"Ближайший контекст: {nearest[:300]}")

        text = "\n".join(parts).strip()
        embed_text = text
        if analysis and analysis.is_decorative and not ocr.text_raw:
            embed_text = f"Декоративный элемент. {analysis.summary}"

        chunk_id = "vc_" + _cache_key(occ.occurrence_id, result.source_revision)[:32]
        metadata = {
            "title": result.title,
            "source": result.title or result.source_path,
            "path": result.source_path,
            "file_type": (("." + result.source_type) if result.source_type else ""),
            "chunk_kind": "visual",
            "source_id": result.source_id,
            "source_revision": result.source_revision,
            "block_id": occ.occurrence_id,
            "occurrence_ids_json": json.dumps([occ.occurrence_id], ensure_ascii=False),
            "asset_ids_json": json.dumps([asset_id], ensure_ascii=False),
            "visual_type": visual_type,
            "visual_group_id": occ.visual_group_id or "",
            "section_path": section,
            "locator_json": json.dumps(occ.locator.to_dict(), ensure_ascii=False),
            "evidence_kind": "visual",
            "extraction_status": result.status,
            "ocr_status": ocr.status,
            "text_raw": ocr.text_raw,
            "text_raw_alt": getattr(ocr, "text_raw_alt", ""),
            "text_normalized": _normalize_search_text(ocr.text_raw),
            "analysis_summary": (analysis.summary if analysis else ""),
            "analysis_params_hash": (analysis.params_hash if analysis else ""),
            "visual_schema_version": (analysis.schema_version if analysis else ""),
            # Совместимость с существующим полем.
            "index_namespace": self.index_namespace,
        }
        return VisualChunk(chunk_id=chunk_id, text=text, embed_text=embed_text, metadata=metadata)

    def _context_text(self, occ: VisualOccurrence) -> str:
        parts = [occ.context_before, occ.context_after]
        return "\n".join(p for p in parts if p)

    def _ocr_fingerprint(self) -> str:
        if self.ocr is None:
            return ""
        health = {}
        try:
            health = self.ocr.health_check() or {}
        except Exception:
            health = {}
        return str(health.get("fingerprint") or getattr(self.ocr, "model_fingerprint", "") or self.ocr.name)


def build_visual_chunks_for_result(
    result: ExtractionResult,
    *,
    ocr: Optional[OCRProvider] = None,
    analyzer: Optional[VisualAnalyzer] = None,
    assets: Optional[VisualAssetStore] = None,
    catalog: Optional[KnowledgeCatalog] = None,
    options: Optional[Dict[str, Any]] = None,
) -> VisualIndexResult:
    """Удобная точка входа: извлечение → визуальные чанки."""
    indexer = VisualIndexer(ocr=ocr, analyzer=analyzer, assets=assets, catalog=catalog)
    return indexer.process(result, options=options)
