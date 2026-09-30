#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Связь runtime-настроек админки с параметрами RAG-чата."""

from __future__ import annotations

from typing import Any

from .settings import settings

# Ключи из settings_catalog, которые отражаются в панели «Дополнительно» чата.
CHAT_TOOLBAR_SETTING_KEYS = frozenset({"RAG_TOP_K", "RAG_MIN_SCORE"})
CHAT_TOP_K_MIN = 1
CHAT_TOP_K_MAX = 50
CHAT_MIN_SCORE_MIN = 0.0
CHAT_MIN_SCORE_MAX = 1.0
CHAT_DEFAULT_ANSWER_MODE = "default"
CHAT_ANSWER_MODES = frozenset({
    CHAT_DEFAULT_ANSWER_MODE,
    "brief",
    "employee_instruction",
})

# Русские режимы Telegram-бота и синонимы -> серверные режимы.
# Новые серверные режимы (detailed / by_sources / step_by_step) появятся вместе
# с ветками в core/rag.py; пока маппим на существующие три.
TELEGRAM_MODE_ALIASES: dict[str, str] = {
    "обычный": CHAT_DEFAULT_ANSWER_MODE,
    "кратко": "brief",
    "подробно": CHAT_DEFAULT_ANSWER_MODE,
    "по_источникам": CHAT_DEFAULT_ANSWER_MODE,
    "по_шагам": CHAT_DEFAULT_ANSWER_MODE,
    "инструкция": "employee_instruction",
    CHAT_DEFAULT_ANSWER_MODE: CHAT_DEFAULT_ANSWER_MODE,
    "brief": "brief",
    "employee_instruction": "employee_instruction",
}


def normalize_answer_mode(value: Any) -> str:
    """Нормализовать режим ответа к одному из CHAT_ANSWER_MODES."""
    if not isinstance(value, str):
        return CHAT_DEFAULT_ANSWER_MODE
    key = value.strip().lower()
    if not key:
        return CHAT_DEFAULT_ANSWER_MODE
    mapped = TELEGRAM_MODE_ALIASES.get(key, key)
    if mapped in CHAT_ANSWER_MODES:
        return mapped
    return CHAT_DEFAULT_ANSWER_MODE


def _clamp(value: int | float, minimum: int | float, maximum: int | float):
    return max(minimum, min(maximum, value))


def rag_chat_defaults() -> dict[str, Any]:
    """Эффективные дефолты RAG для веб-чата (после runtime overrides)."""
    return {
        "top_k": int(_clamp(int(settings.RAG_TOP_K), CHAT_TOP_K_MIN, CHAT_TOP_K_MAX)),
        "min_score": float(_clamp(float(settings.RAG_MIN_SCORE), CHAT_MIN_SCORE_MIN, CHAT_MIN_SCORE_MAX)),
        "max_citations": int(settings.RAG_MAX_CITATIONS),
        "max_context_length": int(settings.RAG_MAX_CONTEXT_LENGTH),
        "query_expansion_max_messages": int(settings.RAG_QUERY_EXPANSION_MAX_MESSAGES),
        "deep_retrieval_enabled": bool(getattr(settings, "DEEP_RETRIEVAL_ENABLED", False)),
        "retrieval_mode": str(getattr(settings, "RETRIEVAL_MODE", "hybrid") or "hybrid"),
        "rerank_enabled": bool(getattr(settings, "RERANK_ENABLED", False)),
    }


def resolve_chat_rag_options(data: dict | None) -> dict[str, Any]:
    """Per-request опции чата с подстановкой дефолтов из settings."""
    payload = data if isinstance(data, dict) else {}
    defaults = rag_chat_defaults()

    top_k = payload.get("top_k")
    min_score = payload.get("min_score")
    try:
        top_k = int(top_k) if top_k is not None else None
    except (TypeError, ValueError):
        top_k = None
    try:
        min_score = float(min_score) if min_score is not None else None
    except (TypeError, ValueError):
        min_score = None

    answer_mode = normalize_answer_mode(payload.get("answer_mode"))

    return {
        "top_k": int(_clamp(top_k, CHAT_TOP_K_MIN, CHAT_TOP_K_MAX)) if top_k is not None else defaults["top_k"],
        "min_score": float(_clamp(min_score, CHAT_MIN_SCORE_MIN, CHAT_MIN_SCORE_MAX)) if min_score is not None else defaults["min_score"],
        "answer_mode": answer_mode,
    }
