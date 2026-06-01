#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Связь runtime-настроек админки с параметрами RAG-чата."""

from __future__ import annotations

from typing import Any

from .settings import settings

# Ключи из settings_catalog, которые отражаются в панели «Дополнительно» чата.
CHAT_TOOLBAR_SETTING_KEYS = frozenset({"RAG_TOP_K", "RAG_MIN_SCORE"})


def rag_chat_defaults() -> dict[str, Any]:
    """Эффективные дефолты RAG для веб-чата (после runtime overrides)."""
    return {
        "top_k": int(settings.RAG_TOP_K),
        "min_score": float(settings.RAG_MIN_SCORE),
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

    return {
        "top_k": top_k if top_k is not None else defaults["top_k"],
        "min_score": min_score if min_score is not None else defaults["min_score"],
        "answer_mode": payload.get("answer_mode") or "default",
    }
