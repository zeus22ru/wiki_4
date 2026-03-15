#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система кэширования эмбеддингов и данных
"""

import hashlib
import json
import pickle
import time
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import threading

from config import settings, get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """Запись в кэше"""
    key: str
    value: Any
    created_at: float
    expires_at: float
    access_count: int = 0
    last_accessed: float = 0.0
    
    def is_expired(self) -> bool:
        """Проверка истечения срока действия"""
        return time.time() > self.expires_at
    
    def touch(self):
        """Обновление времени последнего доступа"""
        self.last_accessed = time.time()
        self.access_count += 1
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь"""
        return asdict(self)


@dataclass
class CacheStats:
    """Статистика кэша"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Коэффициент попадания"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь"""
        return {
            'hits': self.hits,
            'misses': self.misses,
            'evictions': self.evictions,
            'size': self.size,
            'hit_rate': f"{self.hit_rate:.2%}"
        }


class FileCache:
    """Файловый кэш с поддержкой TTL"""
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        default_ttl: int = 3600,
        max_size: int = 10000
    ):
        """
        Инициализация файлового кэша
        
        Args:
            cache_dir: Директория для хранения кэша
            default_ttl: Время жизни по умолчанию (секунды)
            max_size: Максимальное количество записей
        """
        self.cache_dir = Path(cache_dir or settings.CACHE_DIR)
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.stats = CacheStats()
        self._lock = threading.RLock()
        
        # Создаём директорию кэша
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Индекс кэша в памяти
        self._index: Dict[str, CacheEntry] = {}
        
        # Загружаем индекс при инициализации
        self._load_index()
        
        logger.info(f"Файловый кэш инициализирован: {self.cache_dir}, TTL: {default_ttl}с")
    
    def _get_cache_path(self, key: str) -> Path:
        """Получить путь к файлу кэша"""
        # Используем хеш ключа для имени файла
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hash_key}.cache"
    
    def _load_index(self):
        """Загрузка индекса кэша"""
        index_file = self.cache_dir / "index.json"
        
        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                
                for key, entry_data in index_data.items():
                    entry = CacheEntry(**entry_data)
                    if not entry.is_expired():
                        self._index[key] = entry
                        self.stats.size += 1
                
                logger.info(f"Загружен индекс кэша: {len(self._index)} записей")
            except Exception as e:
                logger.error(f"Ошибка загрузки индекса кэша: {e}")
    
    def _save_index(self):
        """Сохранение индекса кэша"""
        index_file = self.cache_dir / "index.json"
        
        try:
            index_data = {
                key: entry.to_dict()
                for key, entry in self._index.items()
            }
            
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения индекса кэша: {e}")
    
    def _evict_expired(self):
        """Удаление истёкших записей"""
        expired_keys = [
            key for key, entry in self._index.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            self.delete(key)
        
        if expired_keys:
            logger.debug(f"Удалено {len(expired_keys)} истёкших записей")
    
    def _evict_lru(self, count: int = 1):
        """Удаление наименее используемых записей"""
        if not self._index:
            return
        
        # Сортируем по времени последнего доступа
        sorted_entries = sorted(
            self._index.items(),
            key=lambda x: x[1].last_accessed
        )
        
        for key, _ in sorted_entries[:count]:
            self.delete(key)
            self.stats.evictions += 1
        
        logger.debug(f"LRU эвикция: {count} записей")
    
    def get(self, key: str) -> Optional[Any]:
        """
        Получение значения из кэша
        
        Args:
            key: Ключ кэша
            
        Returns:
            Значение или None если не найдено или истёк
        """
        with self._lock:
            # Проверяем индекс
            if key not in self._index:
                self.stats.misses += 1
                return None
            
            entry = self._index[key]
            
            # Проверяем срок действия
            if entry.is_expired():
                self.delete(key)
                self.stats.misses += 1
                return None
            
            # Загружаем значение из файла
            cache_path = self._get_cache_path(key)
            if not cache_path.exists():
                del self._index[key]
                self.stats.misses += 1
                return None
            
            try:
                with open(cache_path, 'rb') as f:
                    value = pickle.load(f)
                
                entry.touch()
                self.stats.hits += 1
                logger.debug(f"Кэш hit: {key}")
                return value
            except Exception as e:
                logger.error(f"Ошибка чтения кэша {key}: {e}")
                self.delete(key)
                self.stats.misses += 1
                return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Сохранение значения в кэш
        
        Args:
            key: Ключ кэша
            value: Значение для кэширования
            ttl: Время жизни в секундах (используется default_ttl если None)
            
        Returns:
            True если успешно
        """
        with self._lock:
            ttl = ttl or self.default_ttl
            now = time.time()
            
            # Проверяем размер кэша
            if len(self._index) >= self.max_size:
                self._evict_lru()
            
            # Создаём запись
            entry = CacheEntry(
                key=key,
                value=None,  # Значение хранится в файле
                created_at=now,
                expires_at=now + ttl,
                last_accessed=now
            )
            
            # Сохраняем значение в файл
            cache_path = self._get_cache_path(key)
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump(value, f)
                
                self._index[key] = entry
                self.stats.size = len(self._index)
                
                # Периодически сохраняем индекс
                if self.stats.size % 100 == 0:
                    self._save_index()
                
                logger.debug(f"Кэш set: {key}, TTL: {ttl}с")
                return True
            except Exception as e:
                logger.error(f"Ошибка записи в кэш {key}: {e}")
                return False
    
    def delete(self, key: str) -> bool:
        """
        Удаление записи из кэша
        
        Args:
            key: Ключ кэша
            
        Returns:
            True если успешно
        """
        with self._lock:
            if key in self._index:
                del self._index[key]
                self.stats.size = len(self._index)
            
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                try:
                    cache_path.unlink()
                    return True
                except Exception as e:
                    logger.error(f"Ошибка удаления файла кэша {key}: {e}")
            
            return False
    
    def clear(self):
        """Очистка всего кэша"""
        with self._lock:
            # Удаляем все файлы кэша
            for cache_file in self.cache_dir.glob("*.cache"):
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger.error(f"Ошибка удаления файла {cache_file}: {e}")
            
            # Очищаем индекс
            self._index.clear()
            self.stats.size = 0
            
            # Удаляем индекс
            index_file = self.cache_dir / "index.json"
            if index_file.exists():
                index_file.unlink()
            
            logger.info("Кэш очищен")
    
    def get_stats(self) -> CacheStats:
        """Получение статистики кэша"""
        with self._lock:
            return CacheStats(
                hits=self.stats.hits,
                misses=self.stats.misses,
                evictions=self.stats.evictions,
                size=self.stats.size
            )
    
    def cleanup(self):
        """Очистка истёкших записей"""
        with self._lock:
            self._evict_expired()
            self._save_index()


class EmbeddingCache:
    """Кэш для эмбеддингов"""
    
    def __init__(self, cache_dir: Optional[str] = None, ttl: int = 3600):
        """
        Инициализация кэша эмбеддингов
        
        Args:
            cache_dir: Директория для хранения кэша
            ttl: Время жизни эмбеддингов (секунды)
        """
        self.cache = FileCache(
            cache_dir=cache_dir or settings.CACHE_DIR,
            default_ttl=ttl,
            max_size=10000
        )
        logger.info("Кэш эмбеддингов инициализирован")
    
    def _generate_key(self, text: str, model: str) -> str:
        """Генерация ключа для эмбеддинга"""
        # Используем хеш текста и модели
        content = f"{model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get(self, text: str, model: str) -> Optional[List[float]]:
        """
        Получение эмбеддинга из кэша
        
        Args:
            text: Текст для которого нужен эмбеддинг
            model: Модель эмбеддингов
            
        Returns:
            Эмбеддинг или None
        """
        key = self._generate_key(text, model)
        return self.cache.get(key)
    
    def set(self, text: str, model: str, embedding: List[float], ttl: Optional[int] = None) -> bool:
        """
        Сохранение эмбеддинга в кэш
        
        Args:
            text: Текст
            model: Модель эмбеддингов
            embedding: Эмбеддинг
            ttl: Время жизни (секунды)
            
        Returns:
            True если успешно
        """
        key = self._generate_key(text, model)
        return self.cache.set(key, embedding, ttl)
    
    def invalidate(self, text: Optional[str] = None, model: Optional[str] = None):
        """
        Инвалидация кэша эмбеддингов
        
        Args:
            text: Текст для инвалидации (опционально)
            model: Модель для инвалидации (опционально)
        """
        if text and model:
            # Инвалидируем конкретный эмбеддинг
            key = self._generate_key(text, model)
            self.cache.delete(key)
            logger.debug(f"Инвалидирован эмбеддинг для текста: {text[:50]}...")
        elif model:
            # Инвалидируем все эмбеддинги модели
            # Для файлового кэша это требует перебора всех ключей
            logger.warning("Инвалидация по модели не реализована для файлового кэша")
        else:
            # Очищаем весь кэш
            self.cache.clear()
            logger.info("Кэш эмбеддингов очищен")
    
    def get_stats(self) -> Dict:
        """Получение статистики кэша"""
        stats = self.cache.get_stats()
        return stats.to_dict()
    
    def cleanup(self):
        """Очистка истёкших записей"""
        self.cache.cleanup()


# ============================================
# Глобальные экземпляры кэша
# ============================================

# Кэш эмбеддингов (создаётся при первом использовании)
_embedding_cache: Optional[EmbeddingCache] = None


def get_embedding_cache() -> EmbeddingCache:
    """
    Получение глобального экземпляра кэша эмбеддингов
    
    Returns:
        Экземпляр EmbeddingCache
    """
    global _embedding_cache
    
    if _embedding_cache is None:
        if settings.CACHE_ENABLED:
            _embedding_cache = EmbeddingCache(
                ttl=settings.CACHE_TTL
            )
            logger.info("Кэш эмбеддингов включён")
        else:
            logger.info("Кэш эмбеддингов отключён")
    
    return _embedding_cache


def cache_embedding(text: str, model: str, embedding: List[float]) -> bool:
    """
    Кэширование эмбеддинга
    
    Args:
        text: Текст
        model: Модель
        embedding: Эмбеддинг
        
    Returns:
        True если успешно
    """
    if not settings.CACHE_ENABLED:
        return False
    
    cache = get_embedding_cache()
    return cache.set(text, model, embedding)


def get_cached_embedding(text: str, model: str) -> Optional[List[float]]:
    """
    Получение кэшированного эмбеддинга
    
    Args:
        text: Текст
        model: Модель
        
    Returns:
        Эмбеддинг или None
    """
    if not settings.CACHE_ENABLED:
        return None
    
    cache = get_embedding_cache()
    return cache.get(text, model)


def invalidate_embedding_cache(text: Optional[str] = None, model: Optional[str] = None):
    """
    Инвалидация кэша эмбеддингов
    
    Args:
        text: Текст для инвалидации (опционально)
        model: Модель для инвалидации (опционально)
    """
    if not settings.CACHE_ENABLED:
        return
    
    cache = get_embedding_cache()
    cache.invalidate(text, model)


def get_cache_stats() -> Dict:
    """
    Получение статистики кэша
    
    Returns:
        Словарь со статистикой
    """
    if not settings.CACHE_ENABLED:
        return {'enabled': False}
    
    cache = get_embedding_cache()
    stats = cache.get_stats()
    stats['enabled'] = True
    return stats


def cleanup_cache():
    """Очистка истёкших записей кэша"""
    if not settings.CACHE_ENABLED:
        return
    
    cache = get_embedding_cache()
    cache.cleanup()
