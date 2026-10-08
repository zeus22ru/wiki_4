#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отбор визуальных источников и сборка EvidenceBundle (ТЗ §14).

После hybrid retrieval находит связанные Occurrence, проверяет актуальность и
лимиты, выбирает ограниченный набор визуальных групп и формирует данные для
передачи в vision-модель: реальные байты изображений (data URL) и текстовую
маркировку ``Визуальный источник V1`` рядом с каждой частью.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import settings, get_logger
from core.kb_catalog import KnowledgeCatalog, get_catalog
from core.visual_assets import VisualAssetStore

logger = get_logger(__name__)


@dataclass
class VisualEvidence:
    """Один визуальный источник в ответе (ТЗ §16.1)."""

    occurrence_id: str
    asset_id: str
    source_id: str
    source_title: str
    source_path: str
    section_path: str
    visual_type: str
    evidence_label: str
    caption: str = ""
    page: Optional[int] = None
    slide: Optional[int] = None
    sheet: Optional[str] = None
    visual_group_id: Optional[str] = None
    extraction_status: str = "success"
    used_for_answer: bool = False
    score: float = 0.0
    source_url: Optional[str] = None
    source_revision: str = ""

    def to_dict(self) -> Dict[str, Any]:
        oc = self.occurrence_id
        return {
            "asset_id": self.asset_id,
            "occurrence_id": oc,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "visual_group_id": self.visual_group_id,
            "url": f"/api/documents/images/{oc}",
            "thumbnail_url": f"/api/documents/images/{oc}?variant=thumbnail",
            "title": self.caption or self.source_title,
            "caption": self.caption,
            "source_title": self.source_title,
            "source_path": self.source_path,
            "source_url": self.source_url,
            "section_path": self.section_path,
            "page": self.page,
            "slide": self.slide,
            "sheet": self.sheet,
            "visual_type": self.visual_type,
            "used_for_answer": self.used_for_answer,
            "evidence_label": self.evidence_label,
            "extraction_status": self.extraction_status,
        }


@dataclass
class VisualEvidenceBundle:
    evidence: List[VisualEvidence] = field(default_factory=list)
    image_data_urls: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def labels_text(self) -> str:
        """Текстовая маркировка перед изображениями (ТЗ §14)."""
        lines: List[str] = []
        for ev in self.evidence:
            loc = []
            if ev.page is not None:
                loc.append(f"стр. {ev.page}")
            if ev.slide is not None:
                loc.append(f"слайд {ev.slide}")
            if ev.sheet:
                loc.append(f"лист {ev.sheet}")
            loc_str = f" ({', '.join(loc)})" if loc else ""
            lines.append(
                f"{ev.evidence_label}: {ev.source_title} → {ev.section_path}{loc_str} "
                f"[{ev.visual_type}] occurrence={ev.occurrence_id}"
            )
        return "\n".join(lines)


def _parse_occurrence_ids(chunk: Dict[str, Any]) -> List[str]:
    meta = chunk.get("metadata") or {}
    raw = meta.get("occurrence_ids_json")
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except json.JSONDecodeError:
            pass
    single = meta.get("block_id")
    return [str(single)] if single else []


def _is_visual_chunk(chunk: Dict[str, Any]) -> bool:
    meta = chunk.get("metadata") or {}
    return str(meta.get("chunk_kind") or "") == "visual" or bool(meta.get("occurrence_ids_json"))


class VisualContextResolver:
    """Разрешает визуальные источники из найденных чанков и собирает bundle."""

    def __init__(
        self,
        *,
        catalog: Optional[KnowledgeCatalog] = None,
        assets: Optional[VisualAssetStore] = None,
    ) -> None:
        self.assets = assets or VisualAssetStore()
        self.catalog = catalog or self.assets.catalog

    def resolve(
        self,
        documents: List[Dict[str, Any]],
        *,
        max_groups: Optional[int] = None,
        max_parts: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> VisualEvidenceBundle:
        bundle = VisualEvidenceBundle()
        if not bool(getattr(settings, "RAG_VISUAL_CONTEXT_ENABLED", True)):
            bundle.diagnostics = {"visual_context": "disabled"}
            return bundle

        max_groups = int(max_groups if max_groups is not None else getattr(settings, "RAG_MAX_VISUAL_GROUPS", 3))
        max_parts = int(max_parts if max_parts is not None else getattr(settings, "RAG_MAX_IMAGE_PARTS", 6))
        max_bytes = int(max_bytes if max_bytes is not None else getattr(settings, "RAG_MAX_IMAGE_BYTES", 20 * 1024 * 1024))

        seen_occurrences: set = set()
        seen_groups: set = set()
        used_bytes = 0
        skipped_budget = 0
        selected: List[Tuple[VisualEvidence, bytes, str]] = []

        for chunk in documents:
            if len(selected) >= max_parts:
                break
            if not _is_visual_chunk(chunk):
                continue
            score = float(chunk.get("score") or 0.0)
            for occ_id in _parse_occurrence_ids(chunk):
                if occ_id in seen_occurrences:
                    continue
                occ = self.catalog.get_occurrence(occ_id)
                if not occ:
                    continue
                group = occ.get("visual_group_id")
                if group and group in seen_groups:
                    continue
                if len(seen_groups) >= max_groups and group:
                    skipped_budget += 1
                    continue
                asset_id = occ.get("asset_id")
                if not asset_id:
                    continue
                data = self.assets.read(asset_id)
                if data is None:
                    continue
                if used_bytes + len(data) > max_bytes:
                    skipped_budget += 1
                    continue
                locator = {}
                try:
                    locator = json.loads(occ.get("locator_json") or "{}")
                except json.JSONDecodeError:
                    locator = {}
                label = f"Визуальный источник V{len(selected) + 1}"
                ev = VisualEvidence(
                    occurrence_id=occ_id,
                    asset_id=asset_id,
                    source_id=str(occ.get("source_id") or ""),
                    source_title=str(chunk.get("metadata", {}).get("title") or ""),
                    source_path=str(chunk.get("metadata", {}).get("path") or ""),
                    section_path=str(occ.get("section_path") or ""),
                    visual_type=str(occ.get("visual_type") or "unknown"),
                    evidence_label=label,
                    caption=str(occ.get("caption") or ""),
                    page=locator.get("page"),
                    slide=locator.get("slide"),
                    sheet=locator.get("sheet"),
                    visual_group_id=group,
                    extraction_status=str(occ.get("extraction_quality") or "success"),
                    used_for_answer=True,
                    score=score,
                    source_revision=str(chunk.get("metadata", {}).get("source_revision") or ""),
                )
                mime = "image/png"
                data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
                selected.append((ev, data, data_url))
                used_bytes += len(data)
                seen_occurrences.add(occ_id)
                if group:
                    seen_groups.add(group)

        bundle.evidence = [ev for ev, _, _ in selected]
        bundle.image_data_urls = [url for _, _, url in selected]
        bundle.diagnostics = {
            "visual_context": "ok" if bundle.evidence else "none",
            "selected_occurrences": len(bundle.evidence),
            "image_parts_sent": len(bundle.image_data_urls),
            "bytes_sent": used_bytes,
            "skipped_budget": skipped_budget,
            "max_groups": max_groups,
            "max_parts": max_parts,
            "max_bytes": max_bytes,
        }
        return bundle


def resolve_visual_evidence(
    documents: List[Dict[str, Any]],
    **kwargs: Any,
) -> VisualEvidenceBundle:
    return VisualContextResolver().resolve(documents, **kwargs)
