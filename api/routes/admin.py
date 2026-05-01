#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Админ-диагностика без раскрытия секретов."""

from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify
import chromadb

from config import (
    settings,
    get_logger,
    inference_server_reachable,
    fetch_remote_model_ids,
)
from core.chat_history import get_chat_history

logger = get_logger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _public_settings() -> dict:
    return {
        "inference_backend": settings.INFERENCE_BACKEND,
        "embedding_api_mode": settings.EMBEDDING_API_MODE,
        "chat_api_mode": settings.CHAT_API_MODE,
        "ollama_url": settings.OLLAMA_URL,
        "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
        "chat_model": settings.OLLAMA_CHAT_MODEL,
        "chroma_persist_dir": settings.CHROMA_PERSIST_DIR,
        "chroma_collection_name": settings.CHROMA_COLLECTION_NAME,
        "data_dir": settings.DATA_DIR,
        "upload_dir": settings.UPLOAD_DIR,
        "rag_top_k": settings.RAG_TOP_K,
        "rag_min_score": settings.RAG_MIN_SCORE,
        "rag_max_citations": settings.RAG_MAX_CITATIONS,
        "rag_max_context_length": settings.RAG_MAX_CONTEXT_LENGTH,
        "api_host": settings.API_HOST,
        "api_port": settings.API_PORT,
        "cors_origins": settings.CORS_ORIGINS,
    }


def _chroma_status() -> dict:
    try:
        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        collection = client.get_collection(name=settings.CHROMA_COLLECTION_NAME)
        return {
            "ok": True,
            "collection": settings.CHROMA_COLLECTION_NAME,
            "count": collection.count(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "collection": settings.CHROMA_COLLECTION_NAME,
            "error": str(exc),
        }


def _document_quality() -> dict:
    data_dir = Path(settings.DATA_DIR)
    allowed = {f".{x.strip().lower()}" for x in settings.ALLOWED_EXTENSIONS}
    if not data_dir.exists():
        return {"total": 0, "stale": [], "by_type": {}}

    stale_before = datetime.now() - timedelta(days=180)
    stale = []
    by_type = {}
    total = 0
    for path in data_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        total += 1
        ext = path.suffix.lower().lstrip(".")
        by_type[ext] = by_type.get(ext, 0) + 1
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if modified < stale_before:
            try:
                rel_path = path.relative_to(data_dir)
            except ValueError:
                rel_path = path
            stale.append({
                "path": str(rel_path).replace("\\", "/"),
                "modified_at": modified.isoformat(),
            })

    stale.sort(key=lambda item: item["modified_at"])
    return {"total": total, "stale": stale[:10], "by_type": by_type}


@admin_bp.route("/overview", methods=["GET"])
def overview():
    """Сводное состояние приложения, Chroma, LLM и истории."""
    models = []
    models_error = None
    try:
        models = fetch_remote_model_ids()
    except Exception as exc:
        models_error = str(exc)
        logger.warning("Не удалось получить модели: %s", exc)

    history = get_chat_history()
    feedback_summary = history.get_feedback_summary()
    return jsonify({
        "health": {
            "llm": inference_server_reachable(),
            "chroma": _chroma_status(),
        },
        "settings": _public_settings(),
        "models": {
            "available": models,
            "error": models_error,
            "current_embedding_model_present": settings.OLLAMA_EMBEDDING_MODEL in models,
            "current_chat_model_present": settings.OLLAMA_CHAT_MODEL in models,
        },
        "usage": {
            "chat_count": history.get_session_count(),
            "message_count": history.get_total_message_count(),
        },
        "quality": {
            "feedback": feedback_summary,
            "recent_feedback": history.get_feedback(limit=10),
            "top_sources": history.get_top_sources(limit=8),
            "negative_feedback": history.get_negative_feedback_context(limit=5),
            "documents": _document_quality(),
        },
    })


@admin_bp.route("/settings", methods=["GET"])
def public_settings():
    """Безопасная выдача runtime-настроек для UI."""
    return jsonify({"settings": _public_settings()})
