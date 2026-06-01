#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Каталог runtime-настроек для админки.

Важно:
- возвращаем только безопасные значения (секреты не раскрываем);
- описания и допустимые значения используются для UI-подсказок.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .settings import settings
from .runtime_overrides import load_overrides, overrides_path

SettingType = Literal["str", "int", "float", "bool", "list"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    env: str
    group: str
    type: SettingType
    description: str
    allowed: str
    secret: bool = False
    ui: dict[str, Any] | None = None
    restart_required: bool = False
    restart_hint: str = ""


_GROUP_LLM = "LLM и инференс"
_GROUP_STORAGE = "Хранилище и файлы"
_GROUP_API = "API и Web"
_GROUP_RAG = "RAG: извлечение и контекст"
_GROUP_HYBRID = "Поиск: hybrid / rerank"
_GROUP_INDEXING = "Индексация и чанкинг"
_GROUP_DEEP = "Deep retrieval"
_GROUP_SECURITY = "Безопасность"
_GROUP_BITRIX = "Интеграции: Bitrix24"
_GROUP_CACHE = "Кэш"
_GROUP_UPLOAD = "Загрузка документов"
_GROUP_LOGS = "Логи"


SPECS: list[SettingSpec] = [
    # LLM / Inference
    SettingSpec(
        key="INFERENCE_BACKEND",
        env="INFERENCE_BACKEND",
        group=_GROUP_LLM,
        type="str",
        description=(
            "Единый пресет для режимов API. Влияет на EMBEDDING_API_MODE и CHAT_API_MODE "
            "(если они не переопределены явно)."
        ),
        allowed='"" (пусто), "ollama", "lmstudio"',
    ),
    SettingSpec(
        key="EMBEDDING_API_MODE",
        env="EMBEDDING_API_MODE",
        group=_GROUP_LLM,
        type="str",
        description="Режим эмбеддингового API: Ollama (/api/embed) или OpenAI-совместимый (/v1/embeddings).",
        allowed='"ollama", "openai"',
    ),
    SettingSpec(
        key="CHAT_API_MODE",
        env="CHAT_API_MODE",
        group=_GROUP_LLM,
        type="str",
        description="Режим чат-API: Ollama (/api/generate) или OpenAI-совместимый (/v1/chat/completions).",
        allowed='"ollama", "openai"',
    ),
    SettingSpec(
        key="OLLAMA_URL",
        env="OLLAMA_URL",
        group=_GROUP_LLM,
        type="str",
        description="Базовый URL сервера инференса (Ollama или LM Studio).",
        allowed='URL, например "http://localhost:11434"',
    ),
    SettingSpec(
        key="OLLAMA_EMBEDDING_MODEL",
        env="OLLAMA_EMBEDDING_MODEL",
        group=_GROUP_LLM,
        type="str",
        description="Имя модели эмбеддингов на сервере инференса.",
        allowed="строка (id/name модели на сервере)",
    ),
    SettingSpec(
        key="OLLAMA_CHAT_MODEL",
        env="OLLAMA_CHAT_MODEL",
        group=_GROUP_LLM,
        type="str",
        description="Имя чат-модели на сервере инференса.",
        allowed="строка (id/name модели на сервере)",
    ),
    SettingSpec(
        key="OPENAI_API_KEY",
        env="OPENAI_API_KEY",
        group=_GROUP_LLM,
        type="str",
        description="Ключ для OpenAI-совместимого сервера (если он требует авторизацию).",
        allowed="строка (секрет)",
        secret=True,
    ),
    SettingSpec(
        key="CHAT_MAX_TOKENS",
        env="CHAT_MAX_TOKENS",
        group=_GROUP_LLM,
        type="int",
        description="Лимит длины ответа: OpenAI max_tokens / Ollama num_predict.",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="CHAT_DISABLE_THINKING",
        env="CHAT_DISABLE_THINKING",
        group=_GROUP_LLM,
        type="bool",
        description=(
            "Отключить внутренние рассуждения модели (режим thinking у Qwen 3/3.5 и аналогов). "
            "В запрос чата передаётся enable_thinking=false; при утечке CoT в ответ — постобработка."
        ),
        allowed="true/false",
    ),
    # Storage / Paths
    SettingSpec(
        key="CHROMA_PERSIST_DIR",
        env="CHROMA_PERSIST_DIR",
        group=_GROUP_STORAGE,
        type="str",
        description="Папка хранения ChromaDB (sqlite + файлы коллекции).",
        allowed="путь к директории",
    ),
    SettingSpec(
        key="CHROMA_COLLECTION_NAME",
        env="CHROMA_COLLECTION_NAME",
        group=_GROUP_STORAGE,
        type="str",
        description="Имя коллекции ChromaDB для базы знаний.",
        allowed="строка (имя коллекции)",
    ),
    SettingSpec(
        key="DATA_DIR",
        env="DATA_DIR",
        group=_GROUP_STORAGE,
        type="str",
        description="Папка с исходными документами базы знаний.",
        allowed="путь к директории",
    ),
    SettingSpec(
        key="UPLOAD_DIR",
        env="UPLOAD_DIR",
        group=_GROUP_STORAGE,
        type="str",
        description="Папка, куда сохраняются загруженные документы перед обработкой.",
        allowed="путь к директории",
    ),
    SettingSpec(
        key="DATABASE_PATH",
        env="DATABASE_PATH",
        group=_GROUP_STORAGE,
        type="str",
        description="Путь к SQLite базе истории/пользователей/фидбэка.",
        allowed="путь к файлу .db",
    ),
    # Indexing / Chunking
    SettingSpec(
        key="CHUNK_SIZE",
        env="CHUNK_SIZE",
        group=_GROUP_INDEXING,
        type="int",
        description="Размер чанка при разбиении текста (в условных “токенах/словах” обработки).",
        allowed="целое число ≥ 50",
    ),
    SettingSpec(
        key="CHUNK_OVERLAP",
        env="CHUNK_OVERLAP",
        group=_GROUP_INDEXING,
        type="int",
        description="Перекрытие чанков для сохранения контекста на границах.",
        allowed="целое число ≥ 0 и < CHUNK_SIZE",
    ),
    SettingSpec(
        key="BATCH_SIZE",
        env="BATCH_SIZE",
        group=_GROUP_INDEXING,
        type="int",
        description="Размер батча при обработке документов/эмбеддингах.",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="DOCUMENT_PROCESS_WORKERS",
        env="DOCUMENT_PROCESS_WORKERS",
        group=_GROUP_INDEXING,
        type="int",
        description="Параллелизм обработки документов (парсинг/подготовка).",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="EMBEDDING_WORKERS",
        env="EMBEDDING_WORKERS",
        group=_GROUP_INDEXING,
        type="int",
        description="Параллелизм получения эмбеддингов (обычно 1, чтобы не перегружать сервер).",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="STRUCTURAL_CHUNKING_ENABLED",
        env="STRUCTURAL_CHUNKING_ENABLED",
        group=_GROUP_INDEXING,
        type="bool",
        description="Структурные чанки (заголовки/разделы) при индексации.",
        allowed="true/false",
    ),
    SettingSpec(
        key="STRUCTURAL_CHUNK_MAX_CHARS",
        env="STRUCTURAL_CHUNK_MAX_CHARS",
        group=_GROUP_INDEXING,
        type="int",
        description="Максимальная длина структурного чанка (символы).",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="STRUCTURAL_CHUNK_MIN_CHARS",
        env="STRUCTURAL_CHUNK_MIN_CHARS",
        group=_GROUP_INDEXING,
        type="int",
        description="Минимальная длина структурного чанка (символы).",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="CONTEXTUAL_RETRIEVAL_ENABLED",
        env="CONTEXTUAL_RETRIEVAL_ENABLED",
        group=_GROUP_INDEXING,
        type="bool",
        description="Contextual Retrieval при индексации (доп. контекст вокруг чанков).",
        allowed="true/false",
    ),
    SettingSpec(
        key="CONTEXTUAL_RETRIEVAL_MAX_CHUNKS",
        env="CONTEXTUAL_RETRIEVAL_MAX_CHUNKS",
        group=_GROUP_INDEXING,
        type="int",
        description="Ограничение на количество чанков для contextual retrieval при индексации.",
        allowed="целое число ≥ 1",
    ),
    # RAG core
    SettingSpec(
        key="RAG_TOP_K",
        env="RAG_TOP_K",
        group=_GROUP_RAG,
        type="int",
        description="Сколько кандидатов документов извлекать из Chroma на один запрос.",
        allowed="целое число ≥ 1",
        ui={"kind": "slider", "min": 1, "max": 50, "step": 1},
    ),
    SettingSpec(
        key="RAG_MAX_CITATIONS",
        env="RAG_MAX_CITATIONS",
        group=_GROUP_RAG,
        type="int",
        description="Максимальное число цитат, возвращаемых пользователю.",
        allowed="целое число ≥ 0",
        ui={"kind": "slider", "min": 0, "max": 20, "step": 1},
    ),
    SettingSpec(
        key="RAG_MIN_SCORE",
        env="RAG_MIN_SCORE",
        group=_GROUP_RAG,
        type="float",
        description="Порог релевантности (примерно 1 - distance). 0 отключает фильтрацию.",
        allowed="число от 0 до 1",
    ),
    SettingSpec(
        key="RAG_MAX_CONTEXT_LENGTH",
        env="RAG_MAX_CONTEXT_LENGTH",
        group=_GROUP_RAG,
        type="int",
        description="Лимит размера контекста, который можно передать модели (символы).",
        allowed="целое число ≥ 1000",
    ),
    # Hybrid / rerank
    SettingSpec(
        key="RETRIEVAL_MODE",
        env="RETRIEVAL_MODE",
        group=_GROUP_HYBRID,
        type="str",
        description="Режим извлечения документов: dense / sparse / hybrid.",
        allowed='"hybrid", "dense", "sparse"',
    ),
    SettingSpec(
        key="BM25_INDEX_FILENAME",
        env="BM25_INDEX_FILENAME",
        group=_GROUP_HYBRID,
        type="str",
        description="Имя файла индекса BM25 (в DATA_DIR или рабочей папке проекта).",
        allowed="имя файла, например bm25_corpus.pkl",
    ),
    SettingSpec(
        key="RAG_FUSION_CANDIDATES",
        env="RAG_FUSION_CANDIDATES",
        group=_GROUP_HYBRID,
        type="int",
        description="Сколько кандидатов брать до fusion/дедупликации в hybrid-режиме.",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="RRF_K_CONSTANT",
        env="RRF_K_CONSTANT",
        group=_GROUP_HYBRID,
        type="int",
        description="Константа k для Reciprocal Rank Fusion (RRF).",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="RRF_SCORE_NORMALIZER",
        env="RRF_SCORE_NORMALIZER",
        group=_GROUP_HYBRID,
        type="float",
        description="Делитель для отображения RRF-скора как “релевантности” до rerank.",
        allowed="число > 0",
    ),
    SettingSpec(
        key="RERANK_ENABLED",
        env="RERANK_ENABLED",
        group=_GROUP_HYBRID,
        type="bool",
        description="Включить rerank cross-encoder’ом (требует модель и ресурсы CPU/GPU).",
        allowed="true/false",
    ),
    SettingSpec(
        key="RERANK_MODEL",
        env="RERANK_MODEL",
        group=_GROUP_HYBRID,
        type="str",
        description="Модель cross-encoder для rerank.",
        allowed='строка, например "cross-encoder/ms-marco-MiniLM-L-6-v2"',
    ),
    SettingSpec(
        key="RERANK_TOP_N",
        env="RERANK_TOP_N",
        group=_GROUP_HYBRID,
        type="int",
        description="Сколько кандидатов rerank’ать (после initial retrieval).",
        allowed="целое число ≥ 1",
    ),
    # Query expansion / conversational
    SettingSpec(
        key="CONVERSATIONAL_REWRITE_ENABLED",
        env="CONVERSATIONAL_REWRITE_ENABLED",
        group=_GROUP_RAG,
        type="bool",
        description="Переписывание запроса с учётом диалога (лучше для уточняющих вопросов).",
        allowed="true/false",
    ),
    SettingSpec(
        key="RAG_MULTI_QUERY_ENABLED",
        env="RAG_MULTI_QUERY_ENABLED",
        group=_GROUP_RAG,
        type="bool",
        description="Multi-query: генерировать несколько вариантов запроса для извлечения документов.",
        allowed="true/false",
    ),
    SettingSpec(
        key="RAG_HYDE_ENABLED",
        env="RAG_HYDE_ENABLED",
        group=_GROUP_RAG,
        type="bool",
        description="HyDE: генерировать гипотетический ответ для улучшения retrieval.",
        allowed="true/false",
    ),
    SettingSpec(
        key="RAG_QUERY_EXPANSION_MAX_MESSAGES",
        env="RAG_QUERY_EXPANSION_MAX_MESSAGES",
        group=_GROUP_RAG,
        type="int",
        description="Сколько последних сообщений учитывать при expansion/переписывании запроса.",
        allowed="целое число ≥ 0",
    ),
    # Deep retrieval
    SettingSpec(
        key="DEEP_RETRIEVAL_ENABLED",
        env="DEEP_RETRIEVAL_ENABLED",
        group=_GROUP_DEEP,
        type="bool",
        description="Многошаговый retrieval с дозапросами (DeepResearch-подобный режим).",
        allowed="true/false",
    ),
    SettingSpec(
        key="DEEP_RETRIEVAL_MAX_ITERS",
        env="DEEP_RETRIEVAL_MAX_ITERS",
        group=_GROUP_DEEP,
        type="int",
        description="Максимум итераций deep-поиска (включая первичную).",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="DEEP_RETRIEVAL_NEW_QUERIES_PER_ITER",
        env="DEEP_RETRIEVAL_NEW_QUERIES_PER_ITER",
        group=_GROUP_DEEP,
        type="int",
        description="Сколько новых запросов добавлять на каждой итерации (кроме первой).",
        allowed="целое число ≥ 0",
    ),
    SettingSpec(
        key="DEEP_RETRIEVAL_MIN_BEST_SCORE",
        env="DEEP_RETRIEVAL_MIN_BEST_SCORE",
        group=_GROUP_DEEP,
        type="float",
        description="Порог “достаточно хорошо”: если лучший score ≥ порога, deep-поиск остановится.",
        allowed="число от 0 до 1",
    ),
    SettingSpec(
        key="DEEP_RETRIEVAL_MAX_CANDIDATES",
        env="DEEP_RETRIEVAL_MAX_CANDIDATES",
        group=_GROUP_DEEP,
        type="int",
        description="Максимум кандидатов в пуле до финального top_k (после дедупликации).",
        allowed="целое число ≥ 1",
    ),
    # API / Web
    SettingSpec(
        key="API_HOST",
        env="API_HOST",
        group=_GROUP_API,
        type="str",
        description="Адрес, на котором слушает Flask приложение.",
        allowed='строка, например "0.0.0.0" или "127.0.0.1"',
        restart_required=True,
        restart_hint="Изменение адреса слушателя требует перезапуска приложения.",
    ),
    SettingSpec(
        key="API_PORT",
        env="API_PORT",
        group=_GROUP_API,
        type="int",
        description="Порт Flask приложения.",
        allowed="целое число 1..65535",
        restart_required=True,
        restart_hint="Изменение порта требует перезапуска приложения.",
    ),
    SettingSpec(
        key="FLASK_DEBUG",
        env="FLASK_DEBUG (или DEBUG)",
        group=_GROUP_API,
        type="bool",
        description="Режим отладки Flask/Werkzeug. В продакшене должен быть выключен.",
        allowed="true/false",
        restart_required=True,
        restart_hint="Режим отладки применяется при старте Flask и требует перезапуска.",
    ),
    SettingSpec(
        key="CORS_ORIGINS",
        env="CORS_ORIGINS",
        group=_GROUP_API,
        type="str",
        description='Разрешённые Origin для CORS. "*" — разрешить любые (удобно для разработки).',
        allowed='"*", либо список через запятую, например "http://localhost:3000,https://example.com"',
        restart_required=True,
        restart_hint="CORS конфигурируется при старте приложения и требует перезапуска.",
    ),
    SettingSpec(
        key="TOP_K_RESULTS",
        env="TOP_K_RESULTS",
        group=_GROUP_API,
        type="int",
        description="Лимит результатов для вспомогательных поисков (вне RAGSystem).",
        allowed="целое число ≥ 1",
    ),
    # Security
    SettingSpec(
        key="SECRET_KEY",
        env="SECRET_KEY",
        group=_GROUP_SECURITY,
        type="str",
        description="Секрет Flask-сессии. Должен быть уникальным в production.",
        allowed="строка (секрет)",
        secret=True,
        restart_required=True,
        restart_hint="Смена SECRET_KEY инвалидирует существующие сессии и обычно требует перезапуска.",
    ),
    SettingSpec(
        key="JWT_SECRET_KEY",
        env="JWT_SECRET_KEY",
        group=_GROUP_SECURITY,
        type="str",
        description="Секрет для подписи JWT (авторизация). Должен быть уникальным в production.",
        allowed="строка (секрет)",
        secret=True,
    ),
    SettingSpec(
        key="JWT_EXPIRATION_HOURS",
        env="JWT_EXPIRATION_HOURS",
        group=_GROUP_SECURITY,
        type="int",
        description="Время жизни JWT в часах.",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="API_KEY",
        env="API_KEY",
        group=_GROUP_SECURITY,
        type="str",
        description="Опциональный ключ доступа ко всем /api/* (кроме /api/auth).",
        allowed="строка (секрет)",
        secret=True,
    ),
    SettingSpec(
        key="ADMIN_API_KEY",
        env="ADMIN_API_KEY",
        group=_GROUP_SECURITY,
        type="str",
        description="Опциональный ключ доступа к /api/admin/* (если включён).",
        allowed="строка (секрет)",
        secret=True,
    ),
    # Logs
    SettingSpec(
        key="LOG_LEVEL",
        env="LOG_LEVEL",
        group=_GROUP_LOGS,
        type="str",
        description="Уровень логирования приложения.",
        allowed='например: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"',
    ),
    SettingSpec(
        key="LOG_DIR",
        env="LOG_DIR",
        group=_GROUP_LOGS,
        type="str",
        description="Папка, куда пишутся лог-файлы.",
        allowed="путь к директории",
    ),
    # Cache
    SettingSpec(
        key="CACHE_ENABLED",
        env="CACHE_ENABLED",
        group=_GROUP_CACHE,
        type="bool",
        description="Включить кэширование некоторых вычислений/ответов.",
        allowed="true/false",
    ),
    SettingSpec(
        key="CACHE_TTL",
        env="CACHE_TTL",
        group=_GROUP_CACHE,
        type="int",
        description="Время жизни кэша (секунды).",
        allowed="целое число ≥ 0",
        ui={"kind": "slider", "min": 0, "max": 86400, "step": 60},
    ),
    SettingSpec(
        key="CACHE_DIR",
        env="CACHE_DIR",
        group=_GROUP_CACHE,
        type="str",
        description="Папка хранения файлового кэша.",
        allowed="путь к директории",
    ),
    # Uploads
    SettingSpec(
        key="MAX_FILE_SIZE",
        env="MAX_FILE_SIZE",
        group=_GROUP_UPLOAD,
        type="int",
        description="Максимальный размер загружаемого файла (байты).",
        allowed="целое число ≥ 1 (например 10485760 = 10MB)",
    ),
    SettingSpec(
        key="ALLOWED_EXTENSIONS",
        env="ALLOWED_EXTENSIONS",
        group=_GROUP_UPLOAD,
        type="list",
        description="Разрешённые расширения документов (через запятую).",
        allowed='список: "html,htm,txt,docx,doc,pdf,xlsx,xls,pptx" (можно расширять)',
    ),
    # Bitrix24
    SettingSpec(
        key="BITRIX24_ENABLED",
        env="BITRIX24_ENABLED",
        group=_GROUP_BITRIX,
        type="bool",
        description="Включить интеграцию Bitrix24 (чат-бот).",
        allowed="true/false",
    ),
    SettingSpec(
        key="BITRIX24_WEBHOOK_URL",
        env="BITRIX24_WEBHOOK_URL",
        group=_GROUP_BITRIX,
        type="str",
        description="Webhook URL Bitrix24 для получения событий/вызовов.",
        allowed="URL (секрет, если содержит токен)",
        secret=True,
    ),
    SettingSpec(
        key="BITRIX24_BOT_ID",
        env="BITRIX24_BOT_ID",
        group=_GROUP_BITRIX,
        type="int",
        description="ID бота Bitrix24 (если используется).",
        allowed="целое число ≥ 1 или пусто",
    ),
    SettingSpec(
        key="BITRIX24_BOT_TOKEN",
        env="BITRIX24_BOT_TOKEN",
        group=_GROUP_BITRIX,
        type="str",
        description="Токен бота Bitrix24.",
        allowed="строка (секрет)",
        secret=True,
    ),
    SettingSpec(
        key="BITRIX24_POLL_INTERVAL_SECONDS",
        env="BITRIX24_POLL_INTERVAL_SECONDS",
        group=_GROUP_BITRIX,
        type="int",
        description="Интервал опроса Bitrix24 (секунды).",
        allowed="целое число ≥ 1",
    ),
    SettingSpec(
        key="BITRIX24_EVENT_OFFSET_PATH",
        env="BITRIX24_EVENT_OFFSET_PATH",
        group=_GROUP_BITRIX,
        type="str",
        description="Файл, где хранится offset последнего обработанного события Bitrix24.",
        allowed="путь к файлу .json",
    ),
    SettingSpec(
        key="BITRIX24_INTERNAL_API_URL",
        env="BITRIX24_INTERNAL_API_URL",
        group=_GROUP_BITRIX,
        type="str",
        description="Внутренний URL вашего API, доступный интеграции Bitrix24.",
        allowed="URL",
    ),
    SettingSpec(
        key="BITRIX24_INTERNAL_API_KEY",
        env="BITRIX24_INTERNAL_API_KEY",
        group=_GROUP_BITRIX,
        type="str",
        description="Ключ доступа к внутреннему API для Bitrix24 (обычно API_KEY).",
        allowed="строка (секрет)",
        secret=True,
    ),
]


def _stringify(value: Any, type_: SettingType) -> str:
    if value is None:
        return ""
    if type_ == "bool":
        return "true" if bool(value) else "false"
    if type_ == "list":
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(x) for x in value)
        return str(value)
    return str(value)


def build_admin_settings_payload() -> dict:
    """
    Формат для UI:
    {
      "groups": [
        {"title": "...", "items": [{key, env, type, value, masked, description, allowed}]}
      ]
    }
    """
    overrides = load_overrides()
    by_group: dict[str, list[dict]] = {}
    for spec in SPECS:
        raw = getattr(settings, spec.key, None)
        value = _stringify(raw, spec.type)
        masked_value = "••••••••" if spec.secret and value else ""
        # Короткий “читаемый” заголовок для списка (без открытия tooltip).
        short = (spec.description or "").strip()
        if "." in short:
            short = short.split(".", 1)[0].strip()
        by_group.setdefault(spec.group, []).append({
            "key": spec.key,
            "env": spec.env,
            "type": spec.type,
            "label": short,
            "value": "" if spec.secret else value,
            "masked": masked_value,
            "secret": spec.secret,
            "description": spec.description,
            "allowed": spec.allowed,
            "ui": spec.ui or {},
            "is_overridden": spec.key in overrides,
            "restart_required": bool(spec.restart_required),
            "restart_hint": spec.restart_hint or "",
        })

    groups = [{"title": title, "items": items} for title, items in by_group.items()]
    # Стабильный порядок групп/ключей.
    groups.sort(key=lambda g: g["title"])
    for g in groups:
        g["items"].sort(key=lambda item: item["key"])
    return {"groups": groups, "overrides_path": str(overrides_path()).replace("\\", "/")}

