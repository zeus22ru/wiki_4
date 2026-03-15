#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Утилиты приложения
"""

from .cache import (
    FileCache,
    CacheEntry,
    CacheStats,
    EmbeddingCache,
    get_embedding_cache,
    cache_embedding,
    get_cached_embedding,
    invalidate_embedding_cache,
    get_cache_stats,
    cleanup_cache
)

from .validators import (
    ChatMessage,
    ChatRequest,
    DocumentUpload,
    SearchRequest,
    sanitize_text,
    validate_message_length,
    ValidationError,
    MessageTooLongError,
    MessageTooShortError,
    InvalidCharactersError,
)

__all__ = [
    # Кэширование
    'FileCache',
    'CacheEntry',
    'CacheStats',
    'EmbeddingCache',
    'get_embedding_cache',
    'cache_embedding',
    'get_cached_embedding',
    'invalidate_embedding_cache',
    'get_cache_stats',
    'cleanup_cache',
    # Валидаторы
    'ChatMessage',
    'ChatRequest',
    'DocumentUpload',
    'SearchRequest',
    'sanitize_text',
    'validate_message_length',
    'ValidationError',
    'MessageTooLongError',
    'MessageTooShortError',
    'InvalidCharactersError',
]
