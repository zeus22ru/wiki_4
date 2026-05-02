#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Централизованная конфигурация приложения
Загружает настройки из переменных окружения и .env файла
"""

import os
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


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

_FLASK_DEBUG_RAW = (os.getenv("FLASK_DEBUG") or os.getenv("DEBUG") or "false").strip().lower()


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
    # Лимит токенов ответа: OpenAI-совместимый max_tokens, Ollama /api/generate num_predict
    CHAT_MAX_TOKENS: int = int(os.getenv("CHAT_MAX_TOKENS", "2048"))

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
    FLASK_DEBUG: bool = _FLASK_DEBUG_RAW in ("1", "true", "yes", "on")
    # Разрешённые Origin для CORS. Значение "*" — разрешить любые (удобно для локальной разработки).
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # RAG настройка
    # Число чанков, запрашиваемых из Chroma в RAGSystem.retrieve_documents / query
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))
    RAG_MAX_CITATIONS: int = int(os.getenv("RAG_MAX_CITATIONS", "5"))
    # Порог по формуле 1 - distance; 0.5 отсекает типичные попадания (~0.35–0.45)
    RAG_MIN_SCORE: float = float(os.getenv("RAG_MIN_SCORE", "0.0"))
    RAG_MAX_CONTEXT_LENGTH: int = int(os.getenv("RAG_MAX_CONTEXT_LENGTH", "3000"))

    # Logging настройки
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")

    # Security настройки
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-jwt-secret-key-change-in-production")
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
    API_KEY: str = os.getenv("API_KEY", "")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")

    # Database настройки
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/wiki_qa.db")

    # Cache настройки
    CACHE_ENABLED: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "3600"))  # 1 час по умолчанию
    CACHE_DIR: str = os.getenv("CACHE_DIR", "./cache")

    # File upload настройки
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB
    ALLOWED_EXTENSIONS: list = os.getenv(
        "ALLOWED_EXTENSIONS",
        "html,htm,txt,docx,doc,pdf,xlsx,xls,pptx"
    ).split(",")

    def __init__(self):
        """Инициализация настроек и создание необходимых директорий"""
        self._create_directories()

    def _create_directories(self):
        """Создание необходимых директорий"""
        directories = [
            self.CHROMA_PERSIST_DIR,
            self.DATA_DIR,
            self.UPLOAD_DIR,
            self.LOG_DIR,
            self.CACHE_DIR,
        ]

        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)

    def validate(self) -> bool:
        """Валидация настроек"""
        errors = []

        if not self.SECRET_KEY or self.SECRET_KEY == "your-secret-key-here-change-in-production":
            errors.append("SECRET_KEY должен быть установлен в production")

        if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY == "your-jwt-secret-key-change-in-production":
            errors.append("JWT_SECRET_KEY должен быть установлен в production")

        if errors:
            for error in errors:
                print(f"WARNING: {error}")
            return False
        return True

    def get_ollama_api_url(self) -> str:
        """Получить полный URL для Ollama API"""
        return f"{self.OLLAMA_URL}/api"

    def get_database_url(self) -> str:
        """Получить URL для подключения к базе данных"""
        return f"sqlite:///{self.DATABASE_PATH}"


# Глобальный экземпляр настроек
settings = Settings()


def uses_openai_compatible_api() -> bool:
    """Нужны ли эндпоинты OpenAI-совместимого сервера (/v1/*)."""
    return (
        settings.EMBEDDING_API_MODE == "openai"
        or settings.CHAT_API_MODE == "openai"
    )


def inference_server_reachable(timeout: float = 5.0) -> bool:
    """
    Доступность сервера инференса.
    Для OpenAI-совместимого режима — GET /v1/models и непустой список (LM Studio не поддерживает /api/tags).
    Для Ollama — GET /api/tags.
    """
    base = settings.OLLAMA_URL.rstrip("/")
    if uses_openai_compatible_api():
        try:
            r = requests.get(f"{base}/v1/models", timeout=timeout)
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
        r = requests.get(f"{base}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def fetch_remote_model_ids(timeout: float = 5.0) -> List[str]:
    """
    Список имён моделей на сервере: у Ollama поле name, у LM Studio — id.
    """
    base = settings.OLLAMA_URL.rstrip("/")
    if uses_openai_compatible_api():
        r = requests.get(f"{base}/v1/models", timeout=timeout)
        r.raise_for_status()
        data = r.json().get("data") or []
        return [str(m.get("id", "")) for m in data if m.get("id")]
    r = requests.get(f"{base}/api/tags", timeout=timeout)
    r.raise_for_status()
    return [str(m.get("name", "")) for m in r.json().get("models", []) if m.get("name")]
