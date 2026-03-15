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
    HealthCheckResponse,
    sanitize_html,
    sanitize_text,
    validate_message_length,
    validate_url,
    validate_email,
    validate_chat_id,
    validate_top_k,
    validate_file_size,
    validate_content_type,
    ValidationError,
    MessageTooLongError,
    MessageTooShortError,
    InvalidCharactersError,
    InvalidURLError,
    InvalidEmailError,
    InvalidFileError,
    FileTooLargeError
)

from .formatters import (
    format_rag_response,
    format_source_for_display,
    format_sources_list,
    format_chat_message,
    format_chat_history,
    format_error_response,
    get_user_friendly_error,
    format_file_size,
    format_duration,
    format_number,
    format_percentage,
    format_json_pretty,
    format_json_compact,
    format_markdown_table,
    format_markdown_list,
    format_markdown_code,
    format_markdown_quote,
    format_log_message
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
    'HealthCheckResponse',
    'sanitize_html',
    'sanitize_text',
    'validate_message_length',
    'validate_url',
    'validate_email',
    'validate_chat_id',
    'validate_top_k',
    'validate_file_size',
    'validate_content_type',
    'ValidationError',
    'MessageTooLongError',
    'MessageTooShortError',
    'InvalidCharactersError',
    'InvalidURLError',
    'InvalidEmailError',
    'InvalidFileError',
    'FileTooLargeError',
    # Форматировщики
    'format_rag_response',
    'format_source_for_display',
    'format_sources_list',
    'format_chat_message',
    'format_chat_history',
    'format_error_response',
    'get_user_friendly_error',
    'format_file_size',
    'format_duration',
    'format_number',
    'format_percentage',
    'format_json_pretty',
    'format_json_compact',
    'format_markdown_table',
    'format_markdown_list',
    'format_markdown_code',
    'format_markdown_quote',
    'format_log_message'
]
