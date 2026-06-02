#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manifest индекса: подписи исходных файлов и соответствующие chunk ids."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import settings, get_logger

logger = get_logger(__name__)


def manifest_path() -> Path:
    filename = str(getattr(settings, "INDEX_MANIFEST_FILENAME", "index_manifest.json"))
    return Path(settings.CHROMA_PERSIST_DIR) / filename


def _normalize_rel_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("/")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_signature(path: Path, data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Вернуть стабильную подпись файла для будущего incremental reindex."""
    data_root = Path(data_dir or settings.DATA_DIR)
    try:
        rel_path = path.relative_to(data_root)
    except ValueError:
        rel_path = path.name
    stat = path.stat()
    return {
        "path": _normalize_rel_path(str(rel_path)),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256_file(path),
    }


def build_index_manifest(
    documents: Iterable[Dict[str, Any]],
    data_dir: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Собрать manifest из текущего набора чанков полного reindex."""
    data_root = Path(data_dir or settings.DATA_DIR)
    grouped: Dict[str, Dict[str, Any]] = {}

    for doc in documents:
        metadata = doc.get("metadata") or {}
        rel_path = _normalize_rel_path(str(metadata.get("path") or ""))
        chunk_id = str(doc.get("id") or "")
        if not rel_path or not chunk_id:
            continue
        entry = grouped.setdefault(
            rel_path,
            {
                "path": rel_path,
                "title": metadata.get("title") or "",
                "file_type": metadata.get("file_type") or Path(rel_path).suffix.lower(),
                "chunk_ids": [],
            },
        )
        entry["chunk_ids"].append(chunk_id)

    files: Dict[str, Dict[str, Any]] = {}
    for rel_path, entry in sorted(grouped.items()):
        source_path = data_root / rel_path
        if source_path.is_file():
            entry.update(file_signature(source_path, data_root))
            entry["exists"] = True
        else:
            entry.update({
                "size_bytes": None,
                "mtime_ns": None,
                "sha256": None,
                "exists": False,
            })
        files[rel_path] = entry

    return {
        "version": 1,
        "collection": settings.CHROMA_COLLECTION_NAME,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def save_index_manifest(documents: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> Dict[str, Any]:
    """Перезаписать manifest после успешной полной индексации."""
    manifest = build_index_manifest(documents)
    out_path = Path(path or manifest_path())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Сохранён manifest индекса: %s (%s файлов)", out_path, len(manifest["files"]))
    return manifest


def load_index_manifest(path: Optional[Path] = None) -> Dict[str, Any]:
    in_path = Path(path or manifest_path())
    if not in_path.is_file():
        return {"version": 1, "collection": settings.CHROMA_COLLECTION_NAME, "files": {}}
    return json.loads(in_path.read_text(encoding="utf-8"))


def diff_manifest_against_files(
    manifest: Dict[str, Any],
    data_dir: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Определить changed/deleted файлы относительно manifest без изменения индекса."""
    data_root = Path(data_dir or settings.DATA_DIR)
    files = manifest.get("files") or {}
    changed: List[str] = []
    deleted: List[str] = []

    for rel_path, entry in files.items():
        path = data_root / rel_path
        if not path.is_file():
            deleted.append(rel_path)
            continue
        current = file_signature(path, data_root)
        if (
            current.get("size_bytes") != entry.get("size_bytes")
            or current.get("mtime_ns") != entry.get("mtime_ns")
            or current.get("sha256") != entry.get("sha256")
        ):
            changed.append(rel_path)

    return {"changed": changed, "deleted": deleted}
