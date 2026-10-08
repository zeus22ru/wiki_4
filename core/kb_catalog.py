#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальный каталог знаний: Source / Asset / Occurrence / Analysis (ТЗ §6, §7).

SQLite обеспечивает транзакции и конкурентную запись без внешнего сервера БД.
Каталог хранит связи между источниками, физическими файлами изображений,
их появлениями в документах и результатами OCR/vision. Публикация изменений
выполняется явными транзакциями с поддержкой staging-набора (generation).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import settings, get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT '',
    source_path     TEXT NOT NULL,
    source_url      TEXT,
    revision        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    index_namespace TEXT NOT NULL DEFAULT 'default',
    is_stale        INTEGER NOT NULL DEFAULT 0,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id        TEXT PRIMARY KEY,
    sha256          TEXT NOT NULL,
    mime_type       TEXT NOT NULL DEFAULT '',
    bytes_len       INTEGER NOT NULL DEFAULT 0,
    width           INTEGER,
    height          INTEGER,
    stored_path     TEXT NOT NULL DEFAULT '',
    parent_asset_id TEXT,
    derived_params_json TEXT,
    indexed_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_sha ON assets(sha256);

CREATE TABLE IF NOT EXISTS occurrences (
    occurrence_id   TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    asset_id        TEXT,
    locator_json    TEXT NOT NULL DEFAULT '{}',
    caption         TEXT NOT NULL DEFAULT '',
    alt             TEXT NOT NULL DEFAULT '',
    visual_type     TEXT NOT NULL DEFAULT 'unknown',
    visual_group_id TEXT,
    section_path    TEXT NOT NULL DEFAULT '',
    is_stale        INTEGER NOT NULL DEFAULT 0,
    extraction_quality TEXT NOT NULL DEFAULT 'native',
    context_before  TEXT NOT NULL DEFAULT '',
    context_after   TEXT NOT NULL DEFAULT '',
    index_namespace TEXT NOT NULL DEFAULT 'default',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    updated_at      REAL NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(source_id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);
CREATE INDEX IF NOT EXISTS idx_occ_source ON occurrences(source_id);
CREATE INDEX IF NOT EXISTS idx_occ_asset ON occurrences(asset_id);
CREATE INDEX IF NOT EXISTS idx_occ_ns ON occurrences(index_namespace);

CREATE TABLE IF NOT EXISTS analyses (
    analysis_id     TEXT PRIMARY KEY,
    asset_id        TEXT NOT NULL,
    kind            TEXT NOT NULL,              -- ocr | vision | classification
    status          TEXT NOT NULL DEFAULT 'pending',
    engine          TEXT NOT NULL DEFAULT '',
    engine_version  TEXT NOT NULL DEFAULT '',
    model_fingerprint TEXT NOT NULL DEFAULT '',
    profile         TEXT NOT NULL DEFAULT '',
    params_hash     TEXT NOT NULL DEFAULT '',
    result_json     TEXT NOT NULL DEFAULT '{}',
    error_code      TEXT,
    created_at      REAL NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);
CREATE INDEX IF NOT EXISTS idx_analyses_asset ON analyses(asset_id, kind, params_hash);

CREATE TABLE IF NOT EXISTS source_dependencies (
    source_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    ref         TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(source_id, kind, ref),
    FOREIGN KEY(source_id) REFERENCES sources(source_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generations (
    namespace     TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'building',  -- building | published | failed
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at    REAL NOT NULL,
    published_at  REAL,
    PRIMARY KEY(namespace, generation_id)
);
"""


def catalog_path() -> Path:
    base = Path(getattr(settings, "KB_ASSETS_DIR", "./data/kb_assets"))
    filename = str(getattr(settings, "KB_CATALOG_FILENAME", "catalog.sqlite"))
    return base / filename


class KnowledgeCatalog:
    """Потокобезопасный доступ к SQLite-каталогу знаний."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or catalog_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # --- Sources --------------------------------------------------------------

    def upsert_source(self, *, source_id: str, title: str, source_type: str, source_path: str,
                      source_url: Optional[str] = None, revision: str = "", status: str = "success",
                      index_namespace: str = "default", is_stale: bool = False,
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sources (source_id, title, source_type, source_path, source_url,
                    revision, status, index_namespace, is_stale, metadata_json, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title=excluded.title, source_type=excluded.source_type,
                    source_path=excluded.source_path, source_url=excluded.source_url,
                    revision=excluded.revision, status=excluded.status,
                    index_namespace=excluded.index_namespace, is_stale=excluded.is_stale,
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                (source_id, title, source_type, source_path, source_url, revision, status,
                 index_namespace, 1 if is_stale else 0,
                 json.dumps(metadata or {}, ensure_ascii=False), time.time()),
            )

    def mark_source_stale(self, source_id: str, is_stale: bool = True, status: Optional[str] = None) -> None:
        with self._lock, self._connect() as conn:
            if status:
                conn.execute(
                    "UPDATE sources SET is_stale=?, status=?, updated_at=? WHERE source_id=?",
                    (1 if is_stale else 0, status, time.time(), source_id),
                )
            else:
                conn.execute(
                    "UPDATE sources SET is_stale=?, updated_at=? WHERE source_id=?",
                    (1 if is_stale else 0, time.time(), source_id),
                )

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
        return dict(row) if row else None

    def delete_source(self, source_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM occurrences WHERE source_id=?", (source_id,))
            conn.execute("DELETE FROM source_dependencies WHERE source_id=?", (source_id,))
            conn.execute("DELETE FROM sources WHERE source_id=?", (source_id,))

    # --- Assets ---------------------------------------------------------------

    def upsert_asset(self, *, asset_id: str, sha256: str, mime_type: str, bytes_len: int,
                     stored_path: str, width: Optional[int] = None, height: Optional[int] = None,
                     parent_asset_id: Optional[str] = None,
                     derived_params: Optional[Dict[str, Any]] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO assets (asset_id, sha256, mime_type, bytes_len, width, height,
                    stored_path, parent_asset_id, derived_params_json, indexed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    stored_path=excluded.stored_path, bytes_len=excluded.bytes_len,
                    width=excluded.width, height=excluded.height, indexed_at=excluded.indexed_at
                """,
                (asset_id, sha256, mime_type, bytes_len, width, height, stored_path,
                 parent_asset_id, json.dumps(derived_params, ensure_ascii=False) if derived_params else None,
                 time.time()),
            )

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        return dict(row) if row else None

    def asset_reference_count(self, asset_id: str, *, index_namespace: Optional[str] = None) -> int:
        with self._lock, self._connect() as conn:
            if index_namespace:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM occurrences WHERE asset_id=? AND index_namespace=?",
                    (asset_id, index_namespace),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM occurrences WHERE asset_id=?", (asset_id,)
                ).fetchone()
        return int(row["c"]) if row else 0

    # --- Occurrences ----------------------------------------------------------

    def upsert_occurrence(self, *, occurrence_id: str, source_id: str, asset_id: Optional[str],
                          locator: Dict[str, Any], caption: str = "", alt: str = "",
                          visual_type: str = "unknown", visual_group_id: Optional[str] = None,
                          section_path: str = "", is_stale: bool = False,
                          extraction_quality: str = "native", context_before: str = "",
                          context_after: str = "", index_namespace: str = "default",
                          metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO occurrences (occurrence_id, source_id, asset_id, locator_json,
                    caption, alt, visual_type, visual_group_id, section_path, is_stale,
                    extraction_quality, context_before, context_after, index_namespace,
                    metadata_json, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(occurrence_id) DO UPDATE SET
                    asset_id=excluded.asset_id, locator_json=excluded.locator_json,
                    caption=excluded.caption, alt=excluded.alt, visual_type=excluded.visual_type,
                    visual_group_id=excluded.visual_group_id, section_path=excluded.section_path,
                    is_stale=excluded.is_stale, extraction_quality=excluded.extraction_quality,
                    context_before=excluded.context_before, context_after=excluded.context_after,
                    index_namespace=excluded.index_namespace, metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (occurrence_id, source_id, asset_id, json.dumps(locator, ensure_ascii=False),
                 caption, alt, visual_type, visual_group_id, section_path, 1 if is_stale else 0,
                 extraction_quality, context_before[:2000], context_after[:2000],
                 index_namespace, json.dumps(metadata or {}, ensure_ascii=False), time.time()),
            )

    def get_occurrence(self, occurrence_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM occurrences WHERE occurrence_id=?", (occurrence_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_occurrences_for_source(self, source_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM occurrences WHERE source_id=? ORDER BY rowid", (source_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_occurrences_for_source(self, source_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM occurrences WHERE source_id=?", (source_id,))

    def list_orphan_assets(self, *, grace_hours: float = 72.0) -> List[Dict[str, Any]]:
        """Ассеты без активных ссылок, старше grace-периода (для GC dry-run)."""
        cutoff = time.time() - grace_hours * 3600
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.* FROM assets a
                LEFT JOIN occurrences o ON o.asset_id = a.asset_id
                WHERE o.occurrence_id IS NULL AND a.indexed_at < ?
                """,
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Analyses -------------------------------------------------------------

    def upsert_analysis(self, *, analysis_id: str, asset_id: str, kind: str, status: str,
                        engine: str = "", engine_version: str = "", model_fingerprint: str = "",
                        profile: str = "", params_hash: str = "",
                        result: Optional[Dict[str, Any]] = None, error_code: Optional[str] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analyses (analysis_id, asset_id, kind, status, engine, engine_version,
                    model_fingerprint, profile, params_hash, result_json, error_code, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(analysis_id) DO UPDATE SET
                    status=excluded.status, engine=excluded.engine,
                    engine_version=excluded.engine_version,
                    model_fingerprint=excluded.model_fingerprint, profile=excluded.profile,
                    result_json=excluded.result_json, error_code=excluded.error_code,
                    created_at=excluded.created_at
                """,
                (analysis_id, asset_id, kind, status, engine, engine_version, model_fingerprint,
                 profile, params_hash, json.dumps(result or {}, ensure_ascii=False), error_code, time.time()),
            )

    def get_analysis(self, asset_id: str, kind: str, params_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analyses WHERE asset_id=? AND kind=? AND params_hash=? "
                "ORDER BY created_at DESC LIMIT 1",
                (asset_id, kind, params_hash),
            ).fetchone()
        return dict(row) if row else None

    def delete_failed_analyses(self, asset_id: Optional[str] = None) -> int:
        """Удалить неуспешные анализы, чтобы следующий запуск повторил их."""
        with self._lock, self._connect() as conn:
            if asset_id:
                cur = conn.execute(
                    "DELETE FROM analyses WHERE status IN ('failed','unavailable','pending') AND asset_id=?",
                    (asset_id,),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM analyses WHERE status IN ('failed','unavailable','pending')"
                )
        return cur.rowcount

    # --- Dependencies ---------------------------------------------------------

    def replace_dependencies(self, source_id: str, deps: Iterable[Dict[str, Any]]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM source_dependencies WHERE source_id=?", (source_id,))
            for dep in deps:
                conn.execute(
                    "INSERT OR REPLACE INTO source_dependencies (source_id, kind, ref, content_hash) "
                    "VALUES (?,?,?,?)",
                    (source_id, str(dep.get("kind", "")), str(dep.get("ref", "")),
                     str(dep.get("content_hash", ""))),
                )

    # --- Generations ----------------------------------------------------------

    def begin_generation(self, namespace: str, generation_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO generations (namespace, generation_id, state, metadata_json, created_at) "
                "VALUES (?,?,'building',?,?)",
                (namespace, generation_id, json.dumps(metadata or {}, ensure_ascii=False), time.time()),
            )

    def publish_generation(self, namespace: str, generation_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE generations SET state='published', published_at=? "
                "WHERE namespace=? AND generation_id=?",
                (time.time(), namespace, generation_id),
            )

    def fail_generation(self, namespace: str, generation_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE generations SET state='failed' WHERE namespace=? AND generation_id=?",
                (namespace, generation_id),
            )

    def published_generation(self, namespace: str) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT generation_id FROM generations WHERE namespace=? AND state='published' "
                "ORDER BY published_at DESC LIMIT 1",
                (namespace,),
            ).fetchone()
        return row["generation_id"] if row else None

    def stats(self, index_namespace: Optional[str] = None) -> Dict[str, int]:
        with self._lock, self._connect() as conn:
            def count(sql: str, args: tuple = ()) -> int:
                return int(conn.execute(sql, args).fetchone()[0])

            if index_namespace:
                return {
                    "sources": count("SELECT COUNT(*) FROM sources WHERE index_namespace=?", (index_namespace,)),
                    "occurrences": count("SELECT COUNT(*) FROM occurrences WHERE index_namespace=?", (index_namespace,)),
                    "assets": count("SELECT COUNT(*) FROM assets"),
                    "analyses": count("SELECT COUNT(*) FROM analyses"),
                }
            return {
                "sources": count("SELECT COUNT(*) FROM sources"),
                "occurrences": count("SELECT COUNT(*) FROM occurrences"),
                "assets": count("SELECT COUNT(*) FROM assets"),
                "analyses": count("SELECT COUNT(*) FROM analyses"),
            }


_CATALOG: Optional[KnowledgeCatalog] = None
_CATALOG_LOCK = threading.Lock()


def get_catalog(path: Optional[Path] = None) -> KnowledgeCatalog:
    """Вернуть общий экземпляр каталога (ленивая инициализация)."""
    global _CATALOG
    if _CATALOG is None or path is not None:
        with _CATALOG_LOCK:
            if _CATALOG is None or path is not None:
                _CATALOG = KnowledgeCatalog(path)
    return _CATALOG
