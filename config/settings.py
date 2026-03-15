#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Централизованная конфигурация приложения
Загружает настройки из переменных окружения и .env файла
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


class Settings:
    """Класс для хранения настроек приложения"""

    # Ollama настройки
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_EMBEDDING_MODEL: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")
    OLLAMA_CHAT_MODEL: str = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")

    # ChromaDB настройки
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "wiki_knowledge")

    # Data настройки
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./data/uploads")
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "10"))

    # API настройка
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "5000"))
    TOP_K_RESULTS: int = int(os.getenv("TOP_K_RESULTS", "3"))

    # RAG настройка
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))
    RAG_MAX_CITATIONS: int = int(os.getenv("RAG_MAX_CITATIONS", "5"))
    RAG_MIN_SCORE: float = float(os.getenv("RAG_MIN_SCORE", "0.5"))
    RAG_MAX_CONTEXT_LENGTH: int = int(os.getenv("RAG_MAX_CONTEXT_LENGTH", "3000"))

    # Logging настройки
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")

    # Security настройки
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-jwt-secret-key-change-in-production")
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

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
