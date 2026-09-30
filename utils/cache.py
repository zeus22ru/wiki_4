#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система кэширования эмбеддингов и данных
"""

from __future__ import annotations

import atexit
import hashlib
import json
import struct
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading

from config import settings, get_logger

logger = get_logger(__name__)

# Магический заголовок бинарного файла эмбеддинга (array('f'))
_EMB_MAGIC = b"EMBF1"
_INDEX_SAVE_EVERY = 100


@dataclass
class CacheEntry:
    """Метаданные записи в индексе кэша (значение лежит в файле)."""
    key: str
    created_at: float
    expires_at: float
    last_accessed: float = 0.0

    def is_expired(self) -> bool:
        """Проверка истечения срока действия."""
        return time.time() > self.expires_at

    def touch(self) -> None:
        """Обновление времени последнего доступа."""
        self.last_accessed = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        return cls(
            key=str(data.get("key") or ""),
            created_at=float(data.get("created_at") or 0.0),
            expires_at=float(data.get("expires_at") or 0.0),
            last_accessed=float(data.get("last_accessed") or data.get("created_at") or 0.0),
        )


@dataclass
class CacheStats:
    """Статистика кэша"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> Dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "size": self.size,
            "hit_rate": f"{self.hit_rate:.2%}",
        }


def _write_float_array(path: Path, values: List[float]) -> None:
    """Записать список float в бинарный файл (без pickle)."""
    arr = array("f", (float(v) for v in values))
    with open(path, "wb") as f:
        f.write(_EMB_MAGIC)
        f.write(struct.pack("<I", len(arr)))
        arr.tofile(f)


def _read_float_array(path: Path) -> Optional[List[float]]:
    """Прочитать эмбеддинг: новый формат EMBF1 или JSON-массив (миграция)."""
    raw = path.read_bytes()
    if raw.startswith(_EMB_MAGIC):
        if len(raw) < 9:
            return None
        (n,) = struct.unpack_from("<I", raw, 5)
        arr = array("f")
        arr.frombytes(raw[9 : 9 + n * arr.itemsize])
        if len(arr) != n:
            return None
        return list(arr)
    # Миграция: JSON-массив float
    try:
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, list) and data and all(isinstance(x, (int, float)) for x in data):
            return [float(x) for x in data]
    except Exception:
        pass
    return None


class FileCache:
    """Файловый кэш с поддержкой TTL и персистентным индексом."""

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        default_ttl: int = 3600,
        max_size: int = 10000,
    ):
        self.cache_dir = Path(cache_dir or settings.CACHE_DIR)
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.stats = CacheStats()
        self._lock = threading.RLock()
        self._sets_since_save = 0
        self._index_dirty = False

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index: Dict[str, CacheEntry] = {}
        self._load_index()
        atexit.register(self._atexit_save)

        logger.info(
            "Файловый кэш инициализирован: %s, TTL: %sс",
            self.cache_dir,
            default_ttl,
        )

    def _get_cache_path(self, key: str) -> Path:
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hash_key}.cache"

    def _atexit_save(self) -> None:
        try:
            with self._lock:
                if self._index_dirty or self._sets_since_save:
                    self._save_index()
        except Exception:
            pass

    def _load_index(self) -> None:
        """Загрузка индекса с сверкой файлов на диске."""
        index_file = self.cache_dir / "index.json"
        loaded: Dict[str, CacheEntry] = {}

        if index_file.exists():
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    index_data = json.load(f)
                for key, entry_data in (index_data or {}).items():
                    try:
                        # Совместимость со старым форматом (value/access_count)
                        if "value" in entry_data:
                            entry_data = {
                                k: v
                                for k, v in entry_data.items()
                                if k in ("key", "created_at", "expires_at", "last_accessed")
                            }
                            entry_data.setdefault("key", key)
                        entry = CacheEntry.from_dict(entry_data)
                        if entry.key != key:
                            entry.key = key
                        if not entry.is_expired():
                            loaded[key] = entry
                    except Exception:
                        continue
                logger.info("Загружен индекс кэша: %s записей (до сверки)", len(loaded))
            except Exception as e:
                logger.error("Ошибка загрузки индекса кэша: %s", e)

        # Сверка с файлами: записи без файла — выкинуть; осиротевшие *.cache — удалить
        indexed_paths = {self._get_cache_path(k) for k in loaded}
        for cache_file in self.cache_dir.glob("*.cache"):
            if cache_file not in indexed_paths:
                try:
                    cache_file.unlink()
                    logger.debug("Удалён осиротевший файл кэша: %s", cache_file.name)
                except OSError as e:
                    logger.warning("Не удалось удалить осиротевший %s: %s", cache_file, e)

        cleaned: Dict[str, CacheEntry] = {}
        for key, entry in loaded.items():
            path = self._get_cache_path(key)
            if path.is_file():
                cleaned[key] = entry
            else:
                logger.debug("Запись без файла удалена из индекса: %s", key[:16])

        self._index = cleaned
        self.stats.size = len(self._index)
        if len(cleaned) != len(loaded):
            self._save_index()

    def _save_index(self) -> None:
        index_file = self.cache_dir / "index.json"
        try:
            index_data = {key: entry.to_dict() for key, entry in self._index.items()}
            tmp = index_file.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False)
            tmp.replace(index_file)
            self._sets_since_save = 0
            self._index_dirty = False
        except Exception as e:
            logger.error("Ошибка сохранения индекса кэша: %s", e)

    def _evict_expired(self) -> None:
        expired_keys = [key for key, entry in self._index.items() if entry.is_expired()]
        for key in expired_keys:
            self.delete(key)
        if expired_keys:
            logger.debug("Удалено %s истёкших записей", len(expired_keys))

    def _evict_lru(self, count: Optional[int] = None) -> None:
        """Пакетная эвикция ~10% при переполнении (без сортировки на каждой вставке)."""
        if not self._index:
            return
        if count is None:
            count = max(1, len(self._index) // 10)
        # Один проход сортировки на пакет
        sorted_entries = sorted(
            self._index.items(),
            key=lambda x: x[1].last_accessed,
        )
        for key, _ in sorted_entries[:count]:
            self.delete(key)
            self.stats.evictions += 1
        logger.debug("LRU эвикция: %s записей", count)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._index:
                self.stats.misses += 1
                return None

            entry = self._index[key]
            if entry.is_expired():
                self.delete(key)
                self.stats.misses += 1
                return None

            cache_path = self._get_cache_path(key)
            if not cache_path.exists():
                del self._index[key]
                self.stats.size = len(self._index)
                self._index_dirty = True
                self.stats.misses += 1
                return None

            try:
                value = _read_float_array(cache_path)
                if value is None:
                    # Неэмбеддинг / битый файл
                    self.delete(key)
                    self.stats.misses += 1
                    return None
                entry.touch()
                self._index_dirty = True
                self.stats.hits += 1
                logger.debug("Кэш hit: %s", key[:16])
                return value
            except Exception as e:
                logger.error("Ошибка чтения кэша %s: %s", key[:16], e)
                self.delete(key)
                self.stats.misses += 1
                return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        with self._lock:
            ttl = ttl or self.default_ttl
            now = time.time()

            if len(self._index) >= self.max_size:
                self._evict_lru()

            entry = CacheEntry(
                key=key,
                created_at=now,
                expires_at=now + ttl,
                last_accessed=now,
            )

            cache_path = self._get_cache_path(key)
            try:
                if isinstance(value, list) and value and all(
                    isinstance(x, (int, float)) for x in value
                ):
                    _write_float_array(cache_path, [float(x) for x in value])
                else:
                    # Универсальный fallback: JSON
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(value, f, ensure_ascii=False)

                self._index[key] = entry
                self.stats.size = len(self._index)
                self._sets_since_save += 1
                self._index_dirty = True

                if self._sets_since_save >= _INDEX_SAVE_EVERY:
                    self._save_index()

                logger.debug("Кэш set: %s, TTL: %sс", key[:16], ttl)
                return True
            except Exception as e:
                logger.error("Ошибка записи в кэш %s: %s", key[:16], e)
                return False

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._index:
                del self._index[key]
                self.stats.size = len(self._index)
                self._index_dirty = True

            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                try:
                    cache_path.unlink()
                    return True
                except Exception as e:
                    logger.error("Ошибка удаления файла кэша %s: %s", key[:16], e)
            return False

    def clear(self) -> None:
        with self._lock:
            for cache_file in self.cache_dir.glob("*.cache"):
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger.error("Ошибка удаления файла %s: %s", cache_file, e)

            self._index.clear()
            self.stats.size = 0
            self._index_dirty = False
            self._sets_since_save = 0

            index_file = self.cache_dir / "index.json"
            if index_file.exists():
                try:
                    index_file.unlink()
                except OSError:
                    pass

            logger.info("Кэш очищен")

    def get_stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self.stats.hits,
                misses=self.stats.misses,
                evictions=self.stats.evictions,
                size=self.stats.size,
            )

    def cleanup(self) -> None:
        with self._lock:
            self._evict_expired()
            self._save_index()


class EmbeddingCache:
    """Кэш для эмбеддингов"""

    def __init__(self, cache_dir: Optional[str] = None, ttl: int = 3600):
        self.cache = FileCache(
            cache_dir=cache_dir or settings.CACHE_DIR,
            default_ttl=ttl,
            max_size=10000,
        )
        logger.info("Кэш эмбеддингов инициализирован")

    def _generate_key(self, text: str, model: str) -> str:
        """Ключ включает модель, API-режим и размерность эмбеддинга."""
        mode = str(getattr(settings, "EMBEDDING_API_MODE", "ollama") or "ollama")
        dims = getattr(settings, "EMBEDDING_DIMENSIONS", None)
        dims_part = str(dims) if dims is not None else "auto"
        content = f"{mode}:{dims_part}:{model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, text: str, model: str) -> Optional[List[float]]:
        key = self._generate_key(text, model)
        value = self.cache.get(key)
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return None

    def set(
        self,
        text: str,
        model: str,
        embedding: List[float],
        ttl: Optional[int] = None,
    ) -> bool:
        key = self._generate_key(text, model)
        return self.cache.set(key, embedding, ttl)

    def invalidate(self, text: Optional[str] = None, model: Optional[str] = None) -> None:
        if text and model:
            key = self._generate_key(text, model)
            self.cache.delete(key)
            logger.debug("Инвалидирован эмбеддинг для текста: %s...", text[:50])
        elif model:
            logger.warning("Инвалидация по модели не реализована для файлового кэша")
        else:
            self.cache.clear()
            logger.info("Кэш эмбеддингов очищен")

    def get_stats(self) -> Dict:
        return self.cache.get_stats().to_dict()

    def cleanup(self) -> None:
        self.cache.cleanup()


_embedding_cache: Optional[EmbeddingCache] = None


def get_embedding_cache() -> EmbeddingCache:
    """Глобальный экземпляр кэша эмбеддингов (лениво)."""
    global _embedding_cache

    if _embedding_cache is None:
        if settings.CACHE_ENABLED:
            _embedding_cache = EmbeddingCache(ttl=settings.CACHE_TTL)
            logger.info("Кэш эмбеддингов включён")
        else:
            logger.info("Кэш эмбеддингов отключён")

    return _embedding_cache


def cache_embedding(text: str, model: str, embedding: List[float]) -> bool:
    if not settings.CACHE_ENABLED:
        return False
    cache = get_embedding_cache()
    if cache is None:
        return False
    return cache.set(text, model, embedding)


def get_cached_embedding(text: str, model: str) -> Optional[List[float]]:
    if not settings.CACHE_ENABLED:
        return None
    cache = get_embedding_cache()
    if cache is None:
        return None
    return cache.get(text, model)


def invalidate_embedding_cache(
    text: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    if not settings.CACHE_ENABLED:
        return
    cache = get_embedding_cache()
    if cache is None:
        return
    cache.invalidate(text, model)


def get_cache_stats() -> Dict:
    if not settings.CACHE_ENABLED:
        return {"enabled": False}
    cache = get_embedding_cache()
    if cache is None:
        return {"enabled": False}
    stats = cache.get_stats()
    stats["enabled"] = True
    return stats


def cleanup_cache() -> None:
    if not settings.CACHE_ENABLED:
        return
    cache = get_embedding_cache()
    if cache is None:
        return
    cache.cleanup()
