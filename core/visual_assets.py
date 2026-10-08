#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хранилище визуальных ассетов (ТЗ §7).

Структура каталогов:
``originals/`` — оригиналы по SHA-256, ``derived/`` — рендеры/crop/tiles,
``analysis/`` — кэш OCR/vision, ``staging/`` — неопубликованные результаты.

Оригинал не подменяется thumbnail или улучшенной копией. Публикация — через
временный файл и атомарное переименование. Имя файла пользователя не является
единственным ключом хранения.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from config import settings, get_logger
from core.kb_catalog import KnowledgeCatalog, get_catalog

logger = get_logger(__name__)


def assets_root() -> Path:
    return Path(getattr(settings, "KB_ASSETS_DIR", "./data/kb_assets"))


class VisualAssetStore:
    """Файловое хранилище ассетов + запись в каталог."""

    def __init__(self, root: Optional[Path] = None, catalog: Optional[KnowledgeCatalog] = None) -> None:
        self.root = Path(root or assets_root())
        self.catalog = catalog or get_catalog()
        self.originals_dir = self.root / "originals"
        self.derived_dir = self.root / "derived"
        self.analysis_dir = self.root / "analysis"
        self.staging_dir = self.root / "staging"

    def ensure_dirs(self) -> None:
        for d in (self.originals_dir, self.derived_dir, self.analysis_dir, self.staging_dir):
            d.mkdir(parents=True, exist_ok=True)

    # --- Ключи и пути ---------------------------------------------------------

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def make_asset_id(sha256_hex: str) -> str:
        return f"sha256:{sha256_hex}"

    def _shard_path(self, sha256_hex: str) -> Path:
        return self.originals_dir / sha256_hex[:2] / sha256_hex[2:4] / sha256_hex

    def asset_path(self, asset_id: str) -> Path:
        return self._shard_path(asset_id.split(":", 1)[-1])

    # --- Запись ---------------------------------------------------------------

    def store_original(
        self,
        data: bytes,
        *,
        mime_type: str = "",
        width: Optional[int] = None,
        height: Optional[int] = None,
        parent_asset_id: Optional[str] = None,
        derived_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Сохранить оригинал и вернуть asset_id. Повторная запись идемпотентна."""
        self.ensure_dirs()
        sha = self.sha256(data)
        asset_id = self.make_asset_id(sha)
        target = self._shard_path(sha)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(target, data)
        self.catalog.upsert_asset(
            asset_id=asset_id, sha256=sha, mime_type=mime_type, bytes_len=len(data),
            stored_path=str(target.relative_to(self.root).as_posix()),
            width=width, height=height,
            parent_asset_id=parent_asset_id, derived_params=derived_params,
        )
        return asset_id

    def store_derived(
        self,
        data: bytes,
        *,
        parent_asset_id: str,
        params: Dict[str, Any],
        mime_type: str = "",
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> str:
        """Сохранить производное изображение (crop, tile, raster) с привязкой к родителю."""
        self.ensure_dirs()
        sha = self.sha256(data)
        asset_id = self.make_asset_id(sha)
        target = self._shard_path(sha)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(target, data)
        self.catalog.upsert_asset(
            asset_id=asset_id, sha256=sha, mime_type=mime_type, bytes_len=len(data),
            stored_path=str(target.relative_to(self.root).as_posix()),
            width=width, height=height, parent_asset_id=parent_asset_id,
            derived_params=params,
        )
        return asset_id

    def read(self, asset_id: str) -> Optional[bytes]:
        """Прочитать байты ассета с проверкой, что путь внутри хранилища."""
        asset = self.catalog.get_asset(asset_id)
        if not asset:
            return None
        rel = asset.get("stored_path") or ""
        if not rel:
            return None
        path = (self.root / rel).resolve()
        if not self._is_safe_path(path):
            logger.warning("Попытка доступа вне хранилища ассетов: %s", rel)
            return None
        if not path.is_file():
            return None
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.warning("Ошибка чтения ассета %s: %s", asset_id, exc)
            return None

    def _is_safe_path(self, path: Path) -> bool:
        try:
            path.relative_to(self.root.resolve())
            return True
        except ValueError:
            return False

    def write_analysis_cache(self, key: str, payload: Dict[str, Any]) -> Path:
        """Записать кэш анализа по ключу (sha256→шардинг)."""
        self.ensure_dirs()
        target = self.analysis_dir / key[:2] / f"{key}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        return target

    def read_analysis_cache(self, key: str) -> Optional[Dict[str, Any]]:
        target = self.analysis_dir / key[:2] / f"{key}.json"
        if not target.is_file():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_", suffix=target.suffix)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # --- Очистка --------------------------------------------------------------

    def gc_orphans(self, *, grace_hours: float = 72.0, dry_run: bool = True) -> Dict[str, Any]:
        """Собрать/удалить неиспользуемые ассеты (по умолчанию — только отчёт)."""
        orphans = self.catalog.list_orphan_assets(grace_hours=grace_hours)
        removed = 0
        freed = 0
        for asset in orphans:
            path = (self.root / (asset.get("stored_path") or "")).resolve()
            if not self._is_safe_path(path):
                continue
            size = path.stat().st_size if path.is_file() else 0
            if not dry_run and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    continue
            removed += 1
            freed += size
        return {
            "dry_run": dry_run,
            "orphan_candidates": len(orphans),
            "removed": removed,
            "freed_bytes": freed,
            "asset_ids": [a.get("asset_id") for a in orphans],
        }

    def staging_dir_for(self, generation_id: str) -> Path:
        path = self.staging_dir / generation_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def discard_staging(self, generation_id: str) -> None:
        path = self.staging_dir / generation_id
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
