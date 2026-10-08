#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Единая подсистема извлечения контента из документов (текст + визуальные блоки).

Публичный контракт описан в :mod:`core.document_extraction.base`. Конкретные
адаптеры регистрируются через :func:`core.document_extraction.registry.extract_source`.
"""

from __future__ import annotations

from .base import (
    ANALYSIS_STATUSES,
    BLOCK_KINDS,
    SOURCE_STATUSES,
    ExtractionBlock,
    ExtractionResult,
    Locator,
    VisualOccurrence,
)
from .registry import (
    get_adapter,
    register_adapter,
    extract_source,
    supported_extensions,
    adapter_registry_snapshot,
)

__all__ = [
    "ANALYSIS_STATUSES",
    "BLOCK_KINDS",
    "SOURCE_STATUSES",
    "ExtractionBlock",
    "ExtractionResult",
    "Locator",
    "VisualOccurrence",
    "get_adapter",
    "register_adapter",
    "extract_source",
    "supported_extensions",
    "adapter_registry_snapshot",
]

EXTRACTION_SCHEMA_VERSION = "1"
