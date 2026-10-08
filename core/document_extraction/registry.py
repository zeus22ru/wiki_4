#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Реестр адаптеров источников (ТЗ §4, §5).

Каждый адаптер — объект с атрибутами ``name``, ``version``, ``extensions`` и
методом ``extract(path_or_url, *, options) -> ExtractionResult``. Реестр
позволяет регистрировать новые форматы без изменения вызывающего кода.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from .base import ExtractionResult, UnsupportedFormat

#: Сопоставление расширения → имя адаптера (заполняется регистрацией).
_EXTENSION_REGISTRY: Dict[str, str] = {}
_ADAPTERS: Dict[str, "SourceAdapter"] = {}


@runtime_checkable
class SourceAdapter(Protocol):
    """Контракт адаптера источника (ТЗ §5, уровень 1)."""

    name: str
    version: str
    extensions: Sequence[str]

    def extract(self, source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        """Извлечь текст, таблицы, изображения и зависимости источника."""
        ...


def register_adapter(adapter: SourceAdapter, *, extensions: Optional[Sequence[str]] = None) -> SourceAdapter:
    """Зарегистрировать адаптер и связать его с расширениями файлов."""
    name = str(getattr(adapter, "name", "") or "").strip()
    if not name:
        raise ValueError("У адаптера должно быть непустое имя")
    _ADAPTERS[name] = adapter
    exts = extensions if extensions is not None else getattr(adapter, "extensions", ()) or ()
    for ext in exts:
        key = str(ext).lower()
        if not key.startswith("."):
            key = "." + key
        _EXTENSION_REGISTRY[key] = name
    return adapter


def get_adapter(name: str) -> Optional[SourceAdapter]:
    return _ADAPTERS.get(name)


def adapter_for_path(path: Path) -> Optional[SourceAdapter]:
    ext = Path(path).suffix.lower()
    name = _EXTENSION_REGISTRY.get(ext)
    if not name:
        return None
    return _ADAPTERS.get(name)


def supported_extensions() -> List[str]:
    return sorted(_EXTENSION_REGISTRY.keys())


def adapter_registry_snapshot() -> Dict[str, Any]:
    return {
        "adapters": {
            name: {
                "version": str(getattr(adapter, "version", "")),
                "extensions": list(getattr(adapter, "extensions", ()) or ()),
            }
            for name, adapter in _ADAPTERS.items()
        },
        "extensions": dict(sorted(_EXTENSION_REGISTRY.items())),
    }


def extract_source(source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
    """Извлечь источник подходящим адаптером.

    ``source`` — путь к файлу (:class:`pathlib.Path` или str). Для URL/HTML
    используйте адаптер напрямую. Неподдерживаемый формат даёт
    :class:`UnsupportedFormat` с явной диагностикой.
    """
    path = Path(source)
    adapter = adapter_for_path(path)
    if adapter is None:
        raise UnsupportedFormat(f"Формат {path.suffix or '(без расширения)'} не поддерживается")
    return adapter.extract(path, options=options or {})
