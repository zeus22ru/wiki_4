#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Админ-диагностика без раскрытия секретов."""

from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
import time

from flask import Blueprint, jsonify
from flask import request
import chromadb

from api.middleware.auth import require_admin_access
from config import (
    settings,
    get_logger,
    inference_server_reachable,
    fetch_remote_model_ids,
)
from core.chat_history import get_chat_history
from core.retrieval import bm25_index_path

logger = get_logger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
_OVERVIEW_CACHE_TTL_SECONDS = 15
_overview_cache: dict | None = None


@admin_bp.before_request
def require_admin_role():
    """Админ-диагностика доступна только роли admin."""
    return require_admin_access()


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


def _path_size_bytes(path: Path) -> int | None:
    """Best-effort size for files/directories used by admin diagnostics."""
    try:
        if path.is_file():
            return path.stat().st_size
        if not path.exists():
            return None
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    continue
        return total
    except OSError:
        return None


def _storage_sizes() -> dict:
    db_path = Path(settings.DATABASE_PATH)
    chroma_path = Path(settings.CHROMA_PERSIST_DIR)
    bm25_path = bm25_index_path()
    return {
        "sqlite_db_bytes": _path_size_bytes(db_path),
        "chroma_dir_bytes": _path_size_bytes(chroma_path),
        "bm25_index_bytes": _path_size_bytes(bm25_path),
    }


def _document_quality() -> dict:
    data_dir = Path(settings.DATA_DIR)
    allowed = {f".{x.strip().lower()}" for x in settings.ALLOWED_EXTENSIONS}
    if not data_dir.exists():
        return {"total": 0, "stale": [], "by_type": {}, "duplicates": [], "empty": []}

    stale_before = datetime.now() - timedelta(days=180)
    stale = []
    empty = []
    names = Counter()
    paths_by_name = {}
    by_type = {}
    total = 0
    for path in data_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        total += 1
        ext = path.suffix.lower().lstrip(".")
        by_type[ext] = by_type.get(ext, 0) + 1
        names[path.name.lower()] += 1
        paths_by_name.setdefault(path.name.lower(), []).append(str(path.relative_to(data_dir)).replace("\\", "/"))
        if path.stat().st_size == 0:
            empty.append(str(path.relative_to(data_dir)).replace("\\", "/"))
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
    duplicates = [
        {"filename": name, "count": count, "paths": paths_by_name.get(name, [])[:5]}
        for name, count in names.items()
        if count > 1
    ]
    duplicates.sort(key=lambda item: item["count"], reverse=True)
    return {
        "total": total,
        "stale": stale[:10],
        "stale_count": len(stale),
        "by_type": by_type,
        "duplicates": duplicates[:10],
        "empty": empty[:10],
    }


def _quality_risks(feedback: dict, documents: dict, weak_answers: list[dict], knowledge_gaps: list[dict]) -> list[dict]:
    risks = []
    total_feedback = feedback.get("total", 0) or 0
    if total_feedback and (feedback.get("down", 0) / total_feedback) >= 0.25:
        risks.append({
            "level": "high",
            "title": "Много негативных оценок",
            "details": f"{feedback.get('down', 0)} из {total_feedback} оценок отрицательные",
        })
    if documents.get("stale_count", 0):
        risks.append({
            "level": "medium",
            "title": "Есть устаревшие документы",
            "details": f"Не обновлялись больше 180 дней: {documents.get('stale_count', 0)}",
        })
    if documents.get("duplicates"):
        risks.append({
            "level": "medium",
            "title": "Найдены дубли файлов",
            "details": f"Групп дублей: {len(documents.get('duplicates', []))}",
        })
    if weak_answers:
        risks.append({
            "level": "high",
            "title": "Есть слабые RAG-ответы",
            "details": f"Последних проблемных ответов: {len(weak_answers)}",
        })
    if knowledge_gaps:
        risks.append({
            "level": "medium",
            "title": "Есть пробелы в базе знаний",
            "details": f"Тем к пополнению: {len(knowledge_gaps)}",
        })
    return risks


def _overview_window() -> tuple[int, str]:
    window_days = request.args.get("window_days", 30, type=int)
    window_days = max(1, min(window_days or 30, 365))
    created_after = (datetime.now() - timedelta(days=window_days)).isoformat()
    return window_days, created_after


def _cache_key(window_days: int) -> tuple:
    return (
        settings.DATABASE_PATH,
        settings.DATA_DIR,
        settings.CHROMA_PERSIST_DIR,
        settings.CHROMA_COLLECTION_NAME,
        window_days,
    )


def _clear_overview_cache() -> None:
    global _overview_cache
    _overview_cache = None


@admin_bp.route("/overview", methods=["GET"])
def overview():
    """Сводное состояние приложения, Chroma, LLM и истории."""
    global _overview_cache
    overview_started = time.perf_counter()
    timings_ms: dict[str, int] = {}

    def mark_timing(name: str, stage_started: float) -> None:
        timings_ms[name] = int((time.perf_counter() - stage_started) * 1000)

    window_days, created_after = _overview_window()
    key = _cache_key(window_days)
    now = time.monotonic()
    force_refresh = request.args.get("refresh") in {"1", "true", "yes"}
    if (
        not force_refresh
        and _overview_cache
        and _overview_cache.get("key") == key
        and _overview_cache.get("expires_at", 0) > now
    ):
        return jsonify(_overview_cache["payload"])

    models = []
    models_error = None
    stage_started = time.perf_counter()
    try:
        models = fetch_remote_model_ids()
    except Exception as exc:
        models_error = str(exc)
        logger.warning("Не удалось получить модели: %s", exc)
    mark_timing("models_ms", stage_started)

    stage_started = time.perf_counter()
    history = get_chat_history()
    mark_timing("history_init_ms", stage_started)
    stage_started = time.perf_counter()
    feedback_summary = history.get_feedback_summary(created_after=created_after)
    mark_timing("feedback_summary_ms", stage_started)
    stage_started = time.perf_counter()
    documents_quality = _document_quality()
    mark_timing("document_quality_ms", stage_started)
    stage_started = time.perf_counter()
    weak_answers = history.get_weak_answers(limit=10, created_after=created_after, scan_limit=1000)
    mark_timing("weak_answers_ms", stage_started)
    stage_started = time.perf_counter()
    knowledge_gaps = history.get_knowledge_gaps(limit=10, created_after=created_after, scan_limit=2000)
    mark_timing("knowledge_gaps_ms", stage_started)
    stage_started = time.perf_counter()
    storage_sizes = _storage_sizes()
    mark_timing("storage_sizes_ms", stage_started)
    stage_started = time.perf_counter()
    chroma_status = _chroma_status()
    mark_timing("chroma_status_ms", stage_started)
    stage_started = time.perf_counter()
    llm_status = inference_server_reachable()
    mark_timing("llm_health_ms", stage_started)
    timings_ms["total_ms"] = int((time.perf_counter() - overview_started) * 1000)

    payload = {
        "health": {
            "llm": llm_status,
            "chroma": chroma_status,
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
            "window_days": window_days,
            "feedback": feedback_summary,
            "recent_feedback": history.get_feedback(limit=10),
            "top_sources": history.get_top_sources(limit=8, created_after=created_after, scan_limit=2000),
            "negative_feedback": history.get_negative_feedback_context(limit=5),
            "negative_sources": history.get_source_feedback(limit=8, created_after=created_after, scan_limit=1000),
            "weak_answers": weak_answers,
            "knowledge_gaps": knowledge_gaps,
            "documents": documents_quality,
            "risks": _quality_risks(feedback_summary, documents_quality, weak_answers, knowledge_gaps),
        },
        "diagnostics": {
            "cache_ttl_seconds": _OVERVIEW_CACHE_TTL_SECONDS,
            "timings_ms": timings_ms,
            "sizes": storage_sizes,
        },
    }
    _overview_cache = {
        "key": key,
        "expires_at": now + _OVERVIEW_CACHE_TTL_SECONDS,
        "payload": payload,
    }
    return jsonify(payload)


@admin_bp.route("/settings", methods=["GET"])
def public_settings():
    """Безопасная выдача runtime-настроек для UI."""
    return jsonify({"settings": _public_settings()})


@admin_bp.route("/settings/schema", methods=["GET"])
def settings_schema():
    """Каталог настроек для админки: группы, расшифровки, допустимые значения."""
    from config.settings_catalog import build_admin_settings_payload

    return jsonify(build_admin_settings_payload())


def _coerce_value(type_name: str, value):
    if type_name == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
        raise ValueError("Некорректное булево значение")
    if type_name == "int":
        if value is None or value == "":
            raise ValueError("Пустое значение")
        return int(value)
    if type_name == "float":
        if value is None or value == "":
            raise ValueError("Пустое значение")
        return float(value)
    if type_name == "list":
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        s = str(value)
        return [part.strip() for part in s.split(",") if part.strip()]
    return "" if value is None else str(value)


@admin_bp.route("/settings", methods=["POST"])
def update_setting():
    """Обновить одну настройку через overrides JSON и применить в runtime."""
    from config.settings_catalog import SPECS
    from config.runtime_overrides import load_overrides, save_overrides, apply_overrides

    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key") or "").strip()
    value = payload.get("value")
    action = str(payload.get("action") or "set").strip().lower()  # set | clear

    spec = next((s for s in SPECS if s.key == key), None)
    if not spec:
        return jsonify({"error": "Неизвестная настройка"}), 400

    overrides = load_overrides()
    if action == "clear":
        updated_overrides = dict(overrides)
        updated_overrides.pop(key, None)
        try:
            apply_overrides(settings, updated_overrides)
        except ValueError as exc:
            return jsonify({"error": f"Некорректное значение: {exc}"}), 400
        save_overrides(updated_overrides)
        _clear_overview_cache()
        if key == "MAX_FILE_SIZE":
            from flask import current_app
            current_app.config["MAX_CONTENT_LENGTH"] = int(settings.MAX_FILE_SIZE)
        return jsonify({"ok": True, "key": key, "action": "clear"})

    try:
        coerced = _coerce_value(spec.type, value)
    except Exception as exc:
        return jsonify({"error": f"Некорректное значение: {exc}"}), 400

    ui = spec.ui or {}
    if spec.type in ("int", "float") and ui.get("kind") == "slider":
        min_v = ui.get("min")
        max_v = ui.get("max")
        if min_v is not None and coerced < min_v:
            return jsonify({"error": f"Значение меньше минимума ({min_v})"}), 400
        if max_v is not None and coerced > max_v:
            return jsonify({"error": f"Значение больше максимума ({max_v})"}), 400

    updated_overrides = dict(overrides)
    updated_overrides[key] = coerced
    try:
        apply_overrides(settings, updated_overrides)
    except ValueError as exc:
        return jsonify({"error": f"Некорректное значение: {exc}"}), 400
    save_overrides(updated_overrides)
    _clear_overview_cache()
    if key == "MAX_FILE_SIZE":
        from flask import current_app
        current_app.config["MAX_CONTENT_LENGTH"] = int(settings.MAX_FILE_SIZE)
    return jsonify({"ok": True, "key": key, "value": ("••••••••" if spec.secret else coerced), "overridden": True})
