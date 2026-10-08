#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Базовые типы и контракты подсистемы извлечения документов.

Модель данных (ТЗ §6) различает четыре сущности:

* ``Source`` — логический документ/страница (см. :class:`ExtractionResult`);
* ``Asset`` — физические байты изображения (см. :mod:`core.kb_catalog`);
* ``Occurrence`` — появление ассета в документе (см. :class:`VisualOccurrence`);
* ``Analysis`` — OCR/vision разбор версии изображения (см. :mod:`core.visual_analysis`).

Модуль намеренно не импортирует тяжёлых библиотек и не зависит от Chroma/RAG:
всё это делает вызывающий код.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --- Допустимые перечисления (строковые константы контракта) -------------------

#: Виды блоков содержимого (ТЗ §5).
BLOCK_KINDS: Tuple[str, ...] = (
    "heading",
    "paragraph",
    "table",
    "visual",
    "page_fallback",
)

#: Итоговые статусы источника (ТЗ §6).
SOURCE_STATUSES: Tuple[str, ...] = (
    "success",
    "partial",
    "failed",
    "unsupported",
    "empty",
)

#: Статусы OCR/vision-анализа (ТЗ §6).
ANALYSIS_STATUSES: Tuple[str, ...] = (
    "pending",
    "success",
    "no_text",
    "failed",
    "unavailable",
    "skipped_decorative",
)

#: Системы координат bbox (ТЗ §6).
COORDINATE_SPACES: Tuple[str, ...] = (
    "pixels",
    "pdf_points",
    "ooxml_emu",
    "normalized",
)

_SLUG_RE = re.compile(r"[^0-9a-zA-Zа-яА-ЯёЁ_./-]+")


def _canonicalize(value: str) -> str:
    """Нормализовать строку идентификатора: прямые слэши, без ведущего слэша."""
    return str(value or "").replace("\\", "/").strip().lstrip("/")


def slugify(value: str, *, max_len: int = 200) -> str:
    """Безопасный детерминированный слаг для идентификаторов."""
    text = _SLUG_RE.sub("_", str(value or "").strip())
    text = re.sub(r"_{2,}", "_", text).strip("_")
    return text[:max_len]


def stable_hash(*parts: Any, length: int = 16) -> str:
    """Детерминированный короткий хэш из произвольных частей."""
    payload = "␟".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def make_source_id(relative_path: str, *, prefix: str = "src") -> str:
    """source_id из канонического относительного пути (ТЗ §6)."""
    return f"{prefix}:{_canonicalize(relative_path)}"


def make_occurrence_id(source_id: str, revision: str, locator_key: str) -> str:
    """occurrence_id из source_id + ревизии + детерминированного locator (ТЗ §6)."""
    digest = stable_hash(source_id, revision, locator_key)
    return f"occ:{digest}"


def make_asset_id(sha256_hex: str, *, prefix: str = "sha256") -> str:
    """asset_id из SHA-256 оригинальных байтов (ТЗ §6)."""
    return f"{prefix}:{sha256_hex}"


@dataclass
class Locator:
    """Позиция фрагмента в источнике (ТЗ §6).

    Номера страниц/слайдов/кадров — с 1. Для неизвестного номера — ``None``,
    а не выдуманное значение. ``bbox`` всегда сопровождается ``coordinate_space``.
    """

    page: Optional[int] = None
    slide: Optional[int] = None
    sheet: Optional[str] = None
    cell_range: Optional[str] = None
    block_order: Optional[int] = None
    object_path: Optional[str] = None
    bbox: Optional[Sequence[float]] = None
    coordinate_space: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "slide": self.slide,
            "sheet": self.sheet,
            "cell_range": self.cell_range,
            "block_order": self.block_order,
            "object_path": self.object_path,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "coordinate_space": self.coordinate_space,
        }

    def key(self) -> str:
        """Детерминированный строковый ключ для occurrence_id."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, default=str)


@dataclass
class ExtractionBlock:
    """Упорядоченный блок содержимого источника (ТЗ §5)."""

    block_id: str
    kind: str
    order: int
    text: str = ""
    section_path: str = ""
    locator: Optional[Locator] = None
    occurrence_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in BLOCK_KINDS:
            raise ValueError(f"Недопустимый вид блока: {self.kind!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kind": self.kind,
            "order": self.order,
            "text": self.text,
            "section_path": self.section_path,
            "locator": self.locator.to_dict() if self.locator else None,
            "occurrence_ids": list(self.occurrence_ids),
            "metadata": dict(self.metadata),
        }


@dataclass
class VisualOccurrence:
    """Появление изображения в документе (ТЗ §6).

    Содержит либо ``image_bytes`` (для последующей записи в Asset Store), либо
    ``asset_id`` (если изображение уже сохранено). Ровно одно из двух должно
    быть задано; при ``image_bytes`` asset_id вычисляется по SHA-256 байтов.
    """

    occurrence_id: str
    source_id: str
    locator: Locator
    image_bytes: Optional[bytes] = None
    asset_id: Optional[str] = None
    mime_type: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    caption: str = ""
    alt: str = ""
    visual_type: str = "unknown"
    visual_group_id: Optional[str] = None
    context_before: str = ""
    context_after: str = ""
    section_path: str = ""
    is_stale: bool = False
    extraction_quality: str = "native"  # native | rendered | page_fallback | degraded
    parent_asset_id: Optional[str] = None
    derived_params: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)

    def ensure_asset_id(self) -> str:
        """Вернуть asset_id, вычислив его из байтов при необходимости."""
        if self.asset_id:
            return self.asset_id
        if not self.image_bytes:
            raise ValueError("У occurrence нет ни asset_id, ни image_bytes")
        return make_asset_id(hashlib.sha256(self.image_bytes).hexdigest())

    def to_dict(self, *, include_bytes: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "occurrence_id": self.occurrence_id,
            "source_id": self.source_id,
            "asset_id": self.asset_id,
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "caption": self.caption,
            "alt": self.alt,
            "visual_type": self.visual_type,
            "visual_group_id": self.visual_group_id,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "section_path": self.section_path,
            "is_stale": self.is_stale,
            "extraction_quality": self.extraction_quality,
            "parent_asset_id": self.parent_asset_id,
            "derived_params": dict(self.derived_params or {}) or None,
            "locator": self.locator.to_dict(),
            "warnings": list(self.warnings),
        }
        if include_bytes and self.image_bytes is not None:
            data["image_bytes_len"] = len(self.image_bytes)
        return data


@dataclass
class ExtractionResult:
    """Единый результат извлечения текстового и визуального содержимого (ТЗ §5)."""

    source_id: str
    title: str
    source_type: str
    source_path: str
    source_revision: str = ""
    source_url: Optional[str] = None
    blocks: List[ExtractionBlock] = field(default_factory=list)
    visual_occurrences: List[VisualOccurrence] = field(default_factory=list)
    dependencies: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "success"
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    adapter_version: str = "1"
    schema_version: str = "1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"Недопустимый статус источника: {self.status!r}")

    def add_diagnostic(self, code: str, message: str = "", **extra: Any) -> None:
        entry = {"code": code, "message": message}
        entry.update({k: v for k, v in extra.items() if v is not None})
        self.diagnostics.append(entry)

    def text_blocks(self) -> List[ExtractionBlock]:
        return [b for b in self.blocks if b.kind != "visual"]

    def visual_blocks(self) -> List[ExtractionBlock]:
        return [b for b in self.blocks if b.kind == "visual"]

    @property
    def text_length(self) -> int:
        return sum(len(b.text) for b in self.blocks if b.text)

    def flat_text(self) -> str:
        """Склеить текст блоков в порядке следования (для обратной совместимости)."""
        parts = [b.text for b in sorted(self.blocks, key=lambda x: x.order) if b.text]
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "source_url": self.source_url,
            "source_revision": self.source_revision,
            "status": self.status,
            "blocks": [b.to_dict() for b in self.blocks],
            "visual_occurrences": [o.to_dict() for o in self.visual_occurrences],
            "dependencies": list(self.dependencies),
            "diagnostics": list(self.diagnostics),
            "adapter_version": self.adapter_version,
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
        }


class ExtractionError(Exception):
    """Ошибка извлечения с диагностическим кодом."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class UnsupportedFormat(ExtractionError):
    """Формат не поддержан зарегистрированными адаптерами."""

    def __init__(self, message: str = "") -> None:
        super().__init__("unsupported_format", message)
