#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Централизованная конфигурация приложения
Загружает настройки из переменных окружения и .env файла
"""

import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from dotenv import load_dotenv

from .validation import validate_chunk_bounds

# Загружаем переменные окружения из .env файла
load_dotenv()

_logger = logging.getLogger(__name__)

_DEFAULT_SECRET_KEY = "your-secret-key-here-change-in-production"


def _env_bool(name: str, default: bool = False) -> bool:
    """Единый парсер булевых переменных окружения."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_optional_int(name: str) -> Optional[int]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _resolve_inference_modes() -> tuple[str, str, str]:
    """
    Единый переключатель бэкенда и режимов HTTP API.

    Returns:
        (INFERENCE_BACKEND, EMBEDDING_API_MODE, CHAT_API_MODE)
        INFERENCE_BACKEND: \"\", \"ollama\", \"lmstudio\"
    """
    raw = (os.getenv("INFERENCE_BACKEND") or "").strip()
    key = raw.lower().replace("-", "").replace("_", "")
    if key == "lmstudio":
        preset_embed, preset_chat = "openai", "openai"
        backend = "lmstudio"
    elif key == "ollama":
        preset_embed, preset_chat = "ollama", "ollama"
        backend = "ollama"
    else:
        preset_embed, preset_chat = None, None
        backend = ""

    embed_ex = (os.getenv("EMBEDDING_API_MODE") or "").strip().lower()
    chat_ex = (os.getenv("CHAT_API_MODE") or "").strip().lower()

    if preset_embed is not None:
        embedding_mode = embed_ex or preset_embed
        chat_mode = chat_ex or preset_chat
    else:
        embedding_mode = embed_ex or "ollama"
        chat_mode = chat_ex or embedding_mode

    return backend, embedding_mode, chat_mode


_INFERENCE_BACKEND, _EMBEDDING_API_MODE, _CHAT_API_MODE = _resolve_inference_modes()

_FLASK_DEBUG = _env_bool("FLASK_DEBUG", _env_bool("DEBUG", False))


class Settings:
    """Класс для хранения настроек приложения"""

    # Ollama настройки
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_EMBEDDING_MODEL: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")
    OLLAMA_CHAT_MODEL: str = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
    # ollama | lmstudio — задаёт пресет API; пусто = только EMBEDDING_API_MODE / CHAT_API_MODE
    INFERENCE_BACKEND: str = _INFERENCE_BACKEND
    # ollama: /api/embed и /api/generate. openai: /v1/embeddings и /v1/chat/completions (LM Studio)
    EMBEDDING_API_MODE: str = _EMBEDDING_API_MODE
    CHAT_API_MODE: str = _CHAT_API_MODE
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    # Раздельные серверы для эмбеддингов и чата: пусто = использовать OLLAMA_URL.
    # Нужны, когда эмбеддинги и ответы обслуживают разные провайдеры.
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "")
    CHAT_BASE_URL: str = os.getenv("CHAT_BASE_URL", "")
    # Раздельные ключи: пусто = использовать OPENAI_API_KEY.
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    CHAT_API_KEY: str = os.getenv("CHAT_API_KEY", "")
    # Лимит токенов ответа: OpenAI-совместимый max_tokens, Ollama /api/generate num_predict
    CHAT_MAX_TOKENS: int = int(os.getenv("CHAT_MAX_TOKENS", "2048"))
    # Отключить thinking/reasoning у чат-модели.
    # Qwen/LM Studio: enable_thinking=false + /no_think + prefill.
    # DeepSeek (api.deepseek.com): thinking={"type":"disabled"}.
    CHAT_DISABLE_THINKING: bool = _env_bool("CHAT_DISABLE_THINKING", True)
    # Размерность эмбеддингов для OpenAI-совместимого API; None — не отправлять поле dimensions
    EMBEDDING_DIMENSIONS: Optional[int] = _env_optional_int("EMBEDDING_DIMENSIONS")

    # ChromaDB настройки
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "wiki_knowledge")

    # Data настройки
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./data/uploads")
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "10"))
    DOCUMENT_PROCESS_WORKERS: int = int(os.getenv("DOCUMENT_PROCESS_WORKERS", str(min(4, os.cpu_count() or 1))))
    EMBEDDING_WORKERS: int = int(os.getenv("EMBEDDING_WORKERS", "1"))

    # API настройка
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "5000"))
    # Лимит результатов для utils.embeddings.search_documents и прочих обходов коллекции без RAGSystem
    TOP_K_RESULTS: int = int(os.getenv("TOP_K_RESULTS", "3"))
    # Режим Flask (Werkzeug debug, подробные страницы ошибок). В продакшене держите false.
    FLASK_DEBUG: bool = _FLASK_DEBUG
    # Разрешённые Origin для CORS. Пусто — same-origin; "*" — любые (только явно).
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "")
    # Доверять X-Forwarded-* (ProxyFix) при работе за reverse proxy
    TRUST_PROXY: bool = _env_bool("TRUST_PROXY", False)
    # Заголовки безопасности в after_request
    SECURITY_HEADERS_ENABLED: bool = _env_bool("SECURITY_HEADERS_ENABLED", True)
    # Максимальная длина текста сообщения чата
    CHAT_MESSAGE_MAX_CHARS: int = int(os.getenv("CHAT_MESSAGE_MAX_CHARS", "1000"))

    # RAG настройка
    # Число чанков, запрашиваемых из Chroma в RAGSystem.retrieve_documents / query
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))
    RAG_MAX_CITATIONS: int = int(os.getenv("RAG_MAX_CITATIONS", "5"))
    # Порог по формуле 1 - distance; 0.5 отсекает типичные попадания (~0.35–0.45)
    RAG_MIN_SCORE: float = float(os.getenv("RAG_MIN_SCORE", "0.0"))
    RAG_MAX_CONTEXT_LENGTH: int = int(os.getenv("RAG_MAX_CONTEXT_LENGTH", "90000"))

    # Гибридный поиск (dense + BM25 + RRF + cross-encoder)
    # hybrid | dense | sparse
    RETRIEVAL_MODE: str = os.getenv("RETRIEVAL_MODE", "hybrid")
    BM25_INDEX_FILENAME: str = os.getenv("BM25_INDEX_FILENAME", "bm25_corpus.pkl")
    INDEX_MANIFEST_FILENAME: str = os.getenv("INDEX_MANIFEST_FILENAME", "index_manifest.json")
    RAG_FUSION_CANDIDATES: int = int(os.getenv("RAG_FUSION_CANDIDATES", "24"))
    RRF_K_CONSTANT: int = int(os.getenv("RRF_K_CONSTANT", "60"))
    # Делитель для отображения RRF-скора как «релевантности» до rerank
    RRF_SCORE_NORMALIZER: float = float(os.getenv("RRF_SCORE_NORMALIZER", "0.15"))
    RERANK_ENABLED: bool = _env_bool("RERANK_ENABLED", False)
    RERANK_MODEL: str = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    RERANK_TOP_N: int = int(os.getenv("RERANK_TOP_N", "20"))
    RERANK_MAX_TEXT_CHARS: int = int(os.getenv("RERANK_MAX_TEXT_CHARS", "4000"))
    RERANK_TIMEOUT_SECONDS: float = float(os.getenv("RERANK_TIMEOUT_SECONDS", "15"))

    # Структурные чанки и Contextual Retrieval (при индексации)
    STRUCTURAL_CHUNKING_ENABLED: bool = _env_bool("STRUCTURAL_CHUNKING_ENABLED", True)
    STRUCTURAL_CHUNK_MAX_CHARS: int = int(os.getenv("STRUCTURAL_CHUNK_MAX_CHARS", "1200"))
    STRUCTURAL_CHUNK_MIN_CHARS: int = int(os.getenv("STRUCTURAL_CHUNK_MIN_CHARS", "80"))
    CONTEXTUAL_RETRIEVAL_ENABLED: bool = _env_bool("CONTEXTUAL_RETRIEVAL_ENABLED", False)
    CONTEXTUAL_RETRIEVAL_MAX_CHUNKS: int = int(os.getenv("CONTEXTUAL_RETRIEVAL_MAX_CHUNKS", "80"))

    # Зачёркнутый текст в HTML wiki: mark — [УСТАРЕЛО: …], exclude — не индексировать, keep — как раньше
    STRIKETHROUGH_INDEX_MODE: str = os.getenv("STRIKETHROUGH_INDEX_MODE", "mark").strip().lower()

    # Память диалога: переписывание запроса, HyDE, multi-query
    CONVERSATIONAL_REWRITE_ENABLED: bool = _env_bool("CONVERSATIONAL_REWRITE_ENABLED", True)
    RAG_MULTI_QUERY_ENABLED: bool = _env_bool("RAG_MULTI_QUERY_ENABLED", False)
    RAG_HYDE_ENABLED: bool = _env_bool("RAG_HYDE_ENABLED", False)
    RAG_QUERY_EXPANSION_MAX_MESSAGES: int = int(os.getenv("RAG_QUERY_EXPANSION_MAX_MESSAGES", "6"))
    # Короткие приветствия / small talk — ответ без поиска по Chroma
    RAG_CHITCHAT_SKIP_RETRIEVAL: bool = _env_bool("RAG_CHITCHAT_SKIP_RETRIEVAL", True)

    # Deep retrieval (DeepResearch-подобный многошаговый поиск)
    # Если включено, retrieval может делать несколько итераций поиска с дозапросами.
    DEEP_RETRIEVAL_ENABLED: bool = _env_bool("DEEP_RETRIEVAL_ENABLED", False)
    # Максимум итераций поиска (включая первичную).
    DEEP_RETRIEVAL_MAX_ITERS: int = int(os.getenv("DEEP_RETRIEVAL_MAX_ITERS", "3"))
    # Сколько новых запросов добавлять на каждой итерации (кроме первой).
    DEEP_RETRIEVAL_NEW_QUERIES_PER_ITER: int = int(os.getenv("DEEP_RETRIEVAL_NEW_QUERIES_PER_ITER", "3"))
    # Порог «достаточно хорошо»: если лучший score >= порога, deep-поиск останавливается.
    DEEP_RETRIEVAL_MIN_BEST_SCORE: float = float(os.getenv("DEEP_RETRIEVAL_MIN_BEST_SCORE", "0.55"))
    # Максимум кандидатов в пуле до финального top_k (после дедупликации).
    DEEP_RETRIEVAL_MAX_CANDIDATES: int = int(os.getenv("DEEP_RETRIEVAL_MAX_CANDIDATES", "60"))

    # Mermaid автофикс (после генерации ответа)
    # Включает дополнительный LLM-вызов для попытки исправить Mermaid в ```mermaid``` блоках
    MERMAID_AUTOFIX_ENABLED: bool = _env_bool("MERMAID_AUTOFIX_ENABLED", True)
    # Подробный лог Mermaid-автофикса (включайте временно для отладки)
    MERMAID_AUTOFIX_LOG_ENABLED: bool = _env_bool("MERMAID_AUTOFIX_LOG_ENABLED", False)

    # Визуальный RAG: изображения в базе знаний (ТЗ §18)
    KB_VISUAL_ENABLED: bool = _env_bool("KB_VISUAL_ENABLED", False)
    KB_ASSETS_DIR: str = os.getenv("KB_ASSETS_DIR", "./data/kb_assets")
    KB_CATALOG_FILENAME: str = os.getenv("KB_CATALOG_FILENAME", "catalog.sqlite")
    KB_VISUAL_INDEX_NAMESPACE: str = os.getenv("KB_VISUAL_INDEX_NAMESPACE", "default")
    KB_ASSET_GC_GRACE_HOURS: float = float(os.getenv("KB_ASSET_GC_GRACE_HOURS", "72"))

    # Portable OCR: RapidOCR-json (ТЗ §8, §18)
    OCR_PROVIDER: str = os.getenv("OCR_PROVIDER", "rapidocr_json")
    OCR_EXECUTABLE: str = os.getenv("OCR_EXECUTABLE", "")
    OCR_MODE: str = os.getenv("OCR_MODE", "oneshot")  # oneshot | pipe (RapidOCR-json 0.2.0 поддерживает только oneshot)
    OCR_MODEL_PROFILE: str = os.getenv("OCR_MODEL_PROFILE", "cyrillic")
    # Дополнительный профиль для латиницы/цифр (второй проход, объединение результатов)
    OCR_SECONDARY_PROFILE: str = os.getenv("OCR_SECONDARY_PROFILE", "english")
    OCR_DUAL_PASS: bool = _env_bool("OCR_DUAL_PASS", True)
    OCR_MODEL_FINGERPRINT: str = os.getenv("OCR_MODEL_FINGERPRINT", "")
    OCR_ENGINE_VERSION: str = os.getenv("OCR_ENGINE_VERSION", "1.1.0")
    OCR_STARTUP_TIMEOUT_SEC: float = float(os.getenv("OCR_STARTUP_TIMEOUT_SEC", "30"))
    OCR_TIMEOUT_SEC: float = float(os.getenv("OCR_TIMEOUT_SEC", "60"))
    OCR_WORKERS: int = int(os.getenv("OCR_WORKERS", "1"))
    OCR_THREADS_PER_WORKER: int = int(os.getenv("OCR_THREADS_PER_WORKER", "4"))
    OCR_RETRY_COUNT: int = int(os.getenv("OCR_RETRY_COUNT", "1"))
    OCR_CACHE_ENABLED: bool = _env_bool("OCR_CACHE_ENABLED", True)

    # Vision-анализ изображений (ТЗ §11, §18)
    VISUAL_ANALYSIS_ENABLED: bool = _env_bool("VISUAL_ANALYSIS_ENABLED", True)
    VISUAL_CHAT_BACKEND: str = os.getenv("VISUAL_CHAT_BACKEND", "")
    VISUAL_CHAT_MODEL: str = os.getenv("VISUAL_CHAT_MODEL", "")
    VISUAL_CHAT_BASE_URL: str = os.getenv("VISUAL_CHAT_BASE_URL", "")
    VISUAL_CHAT_API_KEY: str = os.getenv("VISUAL_CHAT_API_KEY", "")
    VISUAL_ANALYSIS_TIMEOUT_SEC: float = float(os.getenv("VISUAL_ANALYSIS_TIMEOUT_SEC", "120"))
    VISUAL_ANALYSIS_WORKERS: int = int(os.getenv("VISUAL_ANALYSIS_WORKERS", "1"))
    # Потоки визуальной индексации: vision-запросы сетевые (~20 с на картинку),
    # поэтому файлы обрабатываются параллельно. 1 — последовательно, как раньше.
    VISUAL_INDEX_WORKERS: int = int(os.getenv("VISUAL_INDEX_WORKERS", "4"))
    VISUAL_SCHEMA_VERSION: str = os.getenv("VISUAL_SCHEMA_VERSION", "1")
    VISUAL_MAX_RASTER_PIXELS: int = int(os.getenv("VISUAL_MAX_RASTER_PIXELS", "40000000"))
    VISUAL_TILE_SIZE: int = int(os.getenv("VISUAL_TILE_SIZE", "1600"))
    VISUAL_TILE_OVERLAP: int = int(os.getenv("VISUAL_TILE_OVERLAP", "160"))
    VISUAL_MAX_PAGES_PER_SOURCE: int = int(os.getenv("VISUAL_MAX_PAGES_PER_SOURCE", "300"))
    VISUAL_MAX_OCCURRENCES_PER_SOURCE: int = int(os.getenv("VISUAL_MAX_OCCURRENCES_PER_SOURCE", "500"))

    # Визуальный контекст ответа (ТЗ §14, §18)
    RAG_VISUAL_CONTEXT_ENABLED: bool = _env_bool("RAG_VISUAL_CONTEXT_ENABLED", True)
    RAG_MAX_VISUAL_GROUPS: int = int(os.getenv("RAG_MAX_VISUAL_GROUPS", "3"))
    RAG_MAX_IMAGE_PARTS: int = int(os.getenv("RAG_MAX_IMAGE_PARTS", "6"))
    RAG_MAX_IMAGE_BYTES: int = int(os.getenv("RAG_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))

    # Рендеринг (ТЗ §9.2, §9.6, §18)
    PDF_RENDER_DPI: int = int(os.getenv("PDF_RENDER_DPI", "200"))
    OFFICE_RENDERER_PATH: str = os.getenv("OFFICE_RENDERER_PATH", "")
    OFFICE_RENDER_TIMEOUT_SEC: int = int(os.getenv("OFFICE_RENDER_TIMEOUT_SEC", "180"))

    # Экспорт XWiki (ТЗ §10, §18)
    XWIKI_DOWNLOAD_ASSETS: bool = _env_bool("XWIKI_DOWNLOAD_ASSETS", False)
    XWIKI_DOWNLOAD_ATTACHMENTS: bool = _env_bool("XWIKI_DOWNLOAD_ATTACHMENTS", False)
    XWIKI_ASSET_ALLOWED_HOSTS: str = os.getenv("XWIKI_ASSET_ALLOWED_HOSTS", "")
    XWIKI_ASSET_MAX_BYTES: int = int(os.getenv("XWIKI_ASSET_MAX_BYTES", str(50 * 1024 * 1024)))
    XWIKI_ASSET_TIMEOUT_SEC: float = float(os.getenv("XWIKI_ASSET_TIMEOUT_SEC", "30"))

    # Logging настройки
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")
    # Отдельный лог обмена с LLM (вопрос/контекст/ответ/метрики) для калибровки
    LLM_EXCHANGE_LOG_ENABLED: bool = _env_bool("LLM_EXCHANGE_LOG_ENABLED", True)
    # Полный промпт в логе обмена (по умолчанию — только превью)
    LLM_EXCHANGE_LOG_FULL: bool = _env_bool("LLM_EXCHANGE_LOG_FULL", False)
    # Обрезка крупных полей в логе (промпт/ответ/контекст)
    LLM_EXCHANGE_LOG_MAX_CHARS: int = int(os.getenv("LLM_EXCHANGE_LOG_MAX_CHARS", "20000"))

    # Security настройки
    SECRET_KEY: str = os.getenv("SECRET_KEY", _DEFAULT_SECRET_KEY)
    # Падать при дефолтном SECRET_KEY в non-debug, вместо генерации на процесс
    REQUIRE_SECRETS: bool = _env_bool("REQUIRE_SECRETS", False)
    API_KEY: str = os.getenv("API_KEY", "")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")

    # GitHub Issues (user-reports из интерфейса; без токена — заглушка)
    GITHUB_ISSUES_ENABLED: bool = _env_bool("GITHUB_ISSUES_ENABLED", True)
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "")
    GITHUB_ISSUE_LABELS: str = os.getenv("GITHUB_ISSUE_LABELS", "user-report")
    GITHUB_ISSUES_RATE_LIMIT_PER_HOUR: int = int(os.getenv("GITHUB_ISSUES_RATE_LIMIT_PER_HOUR", "3"))

    # Bitrix24 chatbot integration
    BITRIX24_ENABLED: bool = _env_bool("BITRIX24_ENABLED", False)
    BITRIX24_WEBHOOK_URL: str = os.getenv("BITRIX24_WEBHOOK_URL", "")
    BITRIX24_BOT_ID: Optional[int] = (
        int(os.getenv("BITRIX24_BOT_ID"))
        if (os.getenv("BITRIX24_BOT_ID") or "").strip().isdigit()
        else None
    )
    BITRIX24_BOT_TOKEN: str = os.getenv("BITRIX24_BOT_TOKEN", "")
    BITRIX24_POLL_INTERVAL_SECONDS: int = int(os.getenv("BITRIX24_POLL_INTERVAL_SECONDS", "10"))
    BITRIX24_EVENT_OFFSET_PATH: str = os.getenv("BITRIX24_EVENT_OFFSET_PATH", "./data/bitrix24_event_offset.json")
    BITRIX24_INTERNAL_API_URL: str = os.getenv("BITRIX24_INTERNAL_API_URL", f"http://127.0.0.1:{API_PORT}")
    BITRIX24_INTERNAL_API_KEY: str = os.getenv("BITRIX24_INTERNAL_API_KEY", os.getenv("API_KEY", ""))

    # Telegram bot integration
    TELEGRAM_ENABLED: bool = _env_bool("TELEGRAM_ENABLED", False)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@")
    TELEGRAM_WEBAPP_ENABLED: bool = _env_bool(
        "TELEGRAM_WEBAPP_ENABLED",
        _env_bool("TELEGRAM_ENABLED", False),
    )
    TELEGRAM_WEBAPP_MAX_AGE_SECONDS: int = int(os.getenv("TELEGRAM_WEBAPP_MAX_AGE_SECONDS", "3600"))
    TELEGRAM_WEBAPP_URL: str = os.getenv("TELEGRAM_WEBAPP_URL", "")
    TELEGRAM_POLL_INTERVAL_SECONDS: int = int(os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", "2"))
    TELEGRAM_OFFSET_PATH: str = os.getenv("TELEGRAM_OFFSET_PATH", "./data/telegram_update_offset.json")
    TELEGRAM_INTERNAL_API_URL: str = os.getenv("TELEGRAM_INTERNAL_API_URL", f"http://127.0.0.1:{API_PORT}")
    TELEGRAM_INTERNAL_API_KEY: str = os.getenv("TELEGRAM_INTERNAL_API_KEY", os.getenv("API_KEY", ""))
    TELEGRAM_LINK_CODE_TTL_SECONDS: int = int(os.getenv("TELEGRAM_LINK_CODE_TTL_SECONDS", "86400"))
    TELEGRAM_STREAM_EDIT_INTERVAL_MS: int = int(os.getenv("TELEGRAM_STREAM_EDIT_INTERVAL_MS", "800"))
    TELEGRAM_MAX_MESSAGE_LENGTH: int = int(os.getenv("TELEGRAM_MAX_MESSAGE_LENGTH", "4096"))
    TELEGRAM_SHOW_SOURCES: bool = _env_bool("TELEGRAM_SHOW_SOURCES", False)
    TELEGRAM_RICH_MESSAGES: bool = _env_bool("TELEGRAM_RICH_MESSAGES", True)
    TELEGRAM_RICH_MAX_CHARS: int = int(os.getenv("TELEGRAM_RICH_MAX_CHARS", "32000"))
    TELEGRAM_MERMAID_IMAGES: bool = _env_bool("TELEGRAM_MERMAID_IMAGES", True)
    TELEGRAM_MMDC_CMD: str = os.getenv("TELEGRAM_MMDC_CMD", "mmdc")
    TELEGRAM_MMDC_TIMEOUT_SECONDS: int = int(os.getenv("TELEGRAM_MMDC_TIMEOUT_SECONDS", "30"))
    TELEGRAM_MERMAID_MAX_DIAGRAMS: int = int(os.getenv("TELEGRAM_MERMAID_MAX_DIAGRAMS", "5"))
    # Chrome/Edge for Puppeteer used by mmdc (auto-detected if empty)
    TELEGRAM_PUPPETEER_EXECUTABLE_PATH: str = os.getenv("TELEGRAM_PUPPETEER_EXECUTABLE_PATH", "")
    TELEGRAM_MMDC_PUPPETEER_CONFIG: str = os.getenv("TELEGRAM_MMDC_PUPPETEER_CONFIG", "")

    # Database настройки
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/wiki_qa.db")

    # Cache настройки
    CACHE_ENABLED: bool = _env_bool("CACHE_ENABLED", True)
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "3600"))  # 1 час по умолчанию
    CACHE_DIR: str = os.getenv("CACHE_DIR", "./cache")

    # File upload настройки
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB
    ALLOWED_EXTENSIONS: list = os.getenv(
        "ALLOWED_EXTENSIONS",
        "html,htm,txt,docx,doc,pdf,xlsx,xls,pptx"
    ).split(",")

    # Вложения к вопросу в чате (скриншоты, текстовые файлы)
    CHAT_ATTACHMENTS_ENABLED: bool = _env_bool("CHAT_ATTACHMENTS_ENABLED", True)
    CHAT_ATTACHMENTS_DIR: str = os.getenv("CHAT_ATTACHMENTS_DIR", "./data/chat_attachments")
    CHAT_ATTACHMENT_MAX_COUNT: int = int(os.getenv("CHAT_ATTACHMENT_MAX_COUNT", "3"))
    CHAT_ATTACHMENT_MAX_BYTES: int = int(os.getenv("CHAT_ATTACHMENT_MAX_BYTES", "5242880"))
    CHAT_ATTACHMENT_TEXT_MAX_CHARS: int = int(os.getenv("CHAT_ATTACHMENT_TEXT_MAX_CHARS", "32000"))
    CHAT_ATTACHMENT_TTL_HOURS: int = int(os.getenv("CHAT_ATTACHMENT_TTL_HOURS", "72"))
    CHAT_ATTACHMENT_ALLOWED_EXTENSIONS: list = os.getenv(
        "CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        "png,jpg,jpeg,webp,gif,txt,log,md,json,xml,csv,yaml,yml,ini,env",
    ).split(",")

    def __init__(self):
        """Инициализация настроек (каталоги создаются через ensure_directories)."""
        validate_chunk_bounds(self.CHUNK_SIZE, self.CHUNK_OVERLAP)
        self._directories_ready = False

    def ensure_directories(self) -> None:
        """Ленивое создание рабочих каталогов (идемпотентно)."""
        if getattr(self, "_directories_ready", False):
            return
        directories = [
            self.CHROMA_PERSIST_DIR,
            self.DATA_DIR,
            self.UPLOAD_DIR,
            self.LOG_DIR,
            self.CACHE_DIR,
            self.CHAT_ATTACHMENTS_DIR,
        ]
        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
        Path(self.BITRIX24_EVENT_OFFSET_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.TELEGRAM_OFFSET_PATH).parent.mkdir(parents=True, exist_ok=True)
        self._directories_ready = True

    def validate(self) -> bool:
        """Валидация секретов для non-debug режима."""
        if self.FLASK_DEBUG:
            return True

        secret_missing = (
            not self.SECRET_KEY
            or self.SECRET_KEY == _DEFAULT_SECRET_KEY
        )
        if not secret_missing:
            return True

        if self.REQUIRE_SECRETS:
            raise ValueError(
                "SECRET_KEY должен быть задан явно при REQUIRE_SECRETS=true "
                "(не используйте значение из .env.example)."
            )

        self.SECRET_KEY = secrets.token_hex(32)
        _logger.warning(
            "SECRET_KEY не задан или использует значение по умолчанию — "
            "сгенерирован случайный ключ на процесс. Задайте SECRET_KEY в .env "
            "для стабильных сессий между перезапусками."
        )
        return True

    def get_ollama_api_url(self) -> str:
        """Получить полный URL для Ollama API"""
        return f"{self.OLLAMA_URL}/api"

    def get_embedding_base_url(self) -> str:
        """Базовый URL сервера эмбеддингов: EMBEDDING_BASE_URL или OLLAMA_URL."""
        return (self.EMBEDDING_BASE_URL or self.OLLAMA_URL).rstrip("/")

    def get_chat_base_url(self) -> str:
        """Базовый URL сервера чата: CHAT_BASE_URL или OLLAMA_URL."""
        return (self.CHAT_BASE_URL or self.OLLAMA_URL).rstrip("/")

    def get_embedding_api_key(self) -> str:
        """Ключ сервера эмбеддингов: EMBEDDING_API_KEY или OPENAI_API_KEY."""
        return self.EMBEDDING_API_KEY or self.OPENAI_API_KEY

    def get_chat_api_key(self) -> str:
        """Ключ сервера чата: CHAT_API_KEY или OPENAI_API_KEY."""
        return self.CHAT_API_KEY or self.OPENAI_API_KEY

    def get_database_url(self) -> str:
        """Получить URL для подключения к базе данных"""
        return f"sqlite:///{self.DATABASE_PATH}"


# Глобальный экземпляр настроек
settings = Settings()

# Применяем runtime-override (админка) поверх env-настроек.
try:
    from .runtime_overrides import load_overrides, apply_overrides

    apply_overrides(settings, load_overrides())
except Exception:
    # Overrides не должны ломать старт приложения.
    pass


def uses_openai_compatible_api() -> bool:
    """Нужны ли эндпоинты OpenAI-совместимого сервера (/v1/*)."""
    return (
        settings.EMBEDDING_API_MODE == "openai"
        or settings.CHAT_API_MODE == "openai"
    )


def inference_servers_are_split() -> bool:
    """Разнесены ли серверы эмбеддингов и чата (по URL или режиму API)."""
    return (
        settings.get_embedding_base_url() != settings.get_chat_base_url()
        or settings.EMBEDDING_API_MODE != settings.CHAT_API_MODE
    )


def _auth_headers(api_mode: str, api_key: str) -> dict:
    """Заголовок авторизации для OpenAI-совместимого сервера (при наличии ключа)."""
    if api_mode == "openai" and api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _endpoint_reachable(base: str, api_mode: str, timeout: float, api_key: str = "") -> bool:
    """Доступен ли конкретный сервер инференса в указанном режиме API."""
    base = (base or "").rstrip("/")
    if not base:
        return False
    headers = _auth_headers(api_mode, api_key)
    if api_mode == "openai":
        try:
            r = requests.get(f"{base}/v1/models", timeout=timeout, headers=headers)
            if r.status_code != 200:
                return False
            payload = r.json()
            models = payload.get("data")
            if models is None:
                models = payload.get("models")
            return bool(models)
        except Exception:
            return False
    try:
        r = requests.get(f"{base}/api/tags", timeout=timeout, headers=headers)
        return r.status_code == 200
    except Exception:
        return False


_INFERENCE_REACHABLE_CACHE: Optional[Tuple[bool, float]] = None
_INFERENCE_REACHABLE_LOCK = threading.Lock()
INFERENCE_REACHABLE_CACHE_TTL: float = float(
    os.getenv("INFERENCE_REACHABLE_CACHE_TTL", "45")
)


def _inference_server_reachable_uncached(timeout: float = 5.0) -> bool:
    """
    Проверка доступности серверов инференса без кэша.

    При раздельных провайдерах проверяются оба сервера (эмбеддинги и чат);
    одинаковые пары (URL, режим) опрашиваются один раз.
    """
    checks = [
        (settings.get_embedding_base_url(), settings.EMBEDDING_API_MODE, settings.get_embedding_api_key()),
        (settings.get_chat_base_url(), settings.CHAT_API_MODE, settings.get_chat_api_key()),
    ]
    seen: dict[Tuple[str, str, str], bool] = {}
    for base, api_mode, api_key in checks:
        key = (base, api_mode, api_key)
        if key not in seen:
            seen[key] = _endpoint_reachable(base, api_mode, timeout, api_key)
    return bool(seen) and all(seen.values())


def inference_server_reachable(timeout: float = 5.0, *, use_cache: bool = True) -> bool:
    """
    Доступность сервера инференса.
    Для OpenAI-совместимого режима — GET /v1/models и непустой список (LM Studio не поддерживает /api/tags).
    Для Ollama — GET /api/tags.

    Результат кэшируется на INFERENCE_REACHABLE_CACHE_TTL секунд (по умолчанию 45), чтобы не
    дергать /v1/models на каждый health-check во время длинной генерации.
    """
    global _INFERENCE_REACHABLE_CACHE
    if use_cache and INFERENCE_REACHABLE_CACHE_TTL > 0:
        with _INFERENCE_REACHABLE_LOCK:
            if _INFERENCE_REACHABLE_CACHE is not None:
                cached_ok, cached_at = _INFERENCE_REACHABLE_CACHE
                if time.monotonic() - cached_at < INFERENCE_REACHABLE_CACHE_TTL:
                    return cached_ok
    ok = _inference_server_reachable_uncached(timeout)
    if use_cache and INFERENCE_REACHABLE_CACHE_TTL > 0:
        with _INFERENCE_REACHABLE_LOCK:
            _INFERENCE_REACHABLE_CACHE = (ok, time.monotonic())
    return ok


def _fetch_model_ids(base: str, api_mode: str, timeout: float, api_key: str = "") -> List[str]:
    """Список id/имён моделей с одного сервера в заданном режиме API."""
    base = (base or "").rstrip("/")
    headers = _auth_headers(api_mode, api_key)
    if api_mode == "openai":
        r = requests.get(f"{base}/v1/models", timeout=timeout, headers=headers)
        r.raise_for_status()
        data = r.json().get("data") or []
        return [str(m.get("id", "")) for m in data if m.get("id")]
    r = requests.get(f"{base}/api/tags", timeout=timeout, headers=headers)
    r.raise_for_status()
    return [str(m.get("name", "")) for m in r.json().get("models", []) if m.get("name")]


def fetch_remote_model_ids(timeout: float = 5.0, *, role: str = "chat") -> List[str]:
    """
    Список имён моделей на сервере: у Ollama поле name, у LM Studio — id.

    role="chat" (по умолчанию) — сервер чата, role="embedding" — сервер эмбеддингов.
    """
    if role == "embedding":
        return _fetch_model_ids(
            settings.get_embedding_base_url(),
            settings.EMBEDDING_API_MODE,
            timeout,
            settings.get_embedding_api_key(),
        )
    return _fetch_model_ids(
        settings.get_chat_base_url(),
        settings.CHAT_API_MODE,
        timeout,
        settings.get_chat_api_key(),
    )
