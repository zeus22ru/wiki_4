#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API управления базой знаний и задачами индексации."""

from datetime import datetime, timedelta
from pathlib import Path
import difflib
import tempfile
import threading
import time
import traceback
from typing import Callable
from uuid import uuid4

from flask import Blueprint, jsonify, request, send_file

from api.middleware.auth import require_admin_access
from config import settings, get_logger
from utils.filenames import file_extension, safe_filename

logger = get_logger(__name__)
documents_bp = Blueprint("documents", __name__, url_prefix="/api/documents")


@documents_bp.before_request
def require_admin_role():
    """Управление базой знаний доступно только администраторам."""
    if request.endpoint in {
        "documents.open_document",
        "documents.related_documents",
        "documents.get_knowledge_image",
    }:
        return None
    return require_admin_access()

_jobs = {}
_jobs_lock = threading.Lock()
_JOB_STATUSES_ACTIVE = {"pending", "running"}
_JOBS_MAX_ITEMS = 50
_JOBS_TTL = timedelta(hours=12)

# Кэш списка документов для /related (и list): TTL 30 с, инвалидация после upload/reindex.
_DOCS_CACHE_TTL_SEC = 30.0
_docs_cache_lock = threading.Lock()
_docs_cache: dict = {"at": 0.0, "docs": None}

# Хук сброса RAG после успешной переиндексации (регистрирует web_app, контракт K2).
_reindex_callback: Callable[[], None] | None = None


def set_reindex_callback(callback: "Callable[[], None] | None") -> None:
    """Зарегистрировать функцию, вызываемую после успешной переиндексации (сброс RAG в web_app)."""
    global _reindex_callback
    _reindex_callback = callback


def _invoke_reindex_callback() -> None:
    callback = _reindex_callback
    if callback is None:
        return
    try:
        callback()
    except Exception:
        logger.exception("Ошибка callback после переиндексации")


def _invalidate_documents_cache() -> None:
    with _docs_cache_lock:
        _docs_cache["docs"] = None
        _docs_cache["at"] = 0.0


def _allowed_file(filename: str) -> bool:
    ext = file_extension(filename)
    if not ext:
        return False
    return ext in {x.strip().lower().lstrip(".") for x in settings.ALLOWED_EXTENSIONS}


def _upload_size_error(file) -> tuple[str | None, int | None]:
    """Проверить размер загружаемого файла против settings.MAX_FILE_SIZE."""
    stream = getattr(file, "stream", None)
    if stream is None:
        return None, None
    pos = stream.tell()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(pos)
    max_size = int(settings.MAX_FILE_SIZE)
    if size > max_size:
        limit_mb = max_size / (1024 * 1024)
        return f"Файл слишком большой. Максимальный размер: {limit_mb:.1f} МБ", 413
    return None, None


def _file_record(path: Path) -> dict:
    stat = path.stat()
    try:
        rel_path = path.relative_to(settings.DATA_DIR)
    except ValueError:
        rel_path = path
    return {
        "path": str(rel_path).replace("\\", "/"),
        "filename": path.name,
        "file_type": path.suffix.lower().lstrip("."),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "status": "known",
    }


def _attachments_roots() -> list[Path]:
    """Каталоги приватных вложений чата — не часть базы знаний."""
    roots: list[Path] = []
    raw = getattr(settings, "CHAT_ATTACHMENTS_DIR", None)
    if raw:
        try:
            roots.append(Path(raw).resolve())
        except OSError:
            pass
    try:
        upload_parent = Path(settings.UPLOAD_DIR).resolve().parent
        roots.append((upload_parent / "chat_attachments").resolve())
    except OSError:
        pass
    # Уникальные пути
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _is_under_attachments(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _attachments_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _scan_documents() -> list[dict]:
    """Сканировать DATA_DIR, пропуская каталог вложений чата."""
    data_dir = Path(settings.DATA_DIR)
    allowed = {f".{x.strip().lower().lstrip('.')}" for x in settings.ALLOWED_EXTENSIONS}
    if not data_dir.exists():
        return []
    docs = []
    for path in data_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in allowed:
            continue
        if _is_under_attachments(path):
            continue
        docs.append(_file_record(path))
    docs.sort(key=lambda item: item["modified_at"], reverse=True)
    return docs


def _get_documents_cached() -> list[dict]:
    """Список документов с кэшем на 30 секунд."""
    now = time.monotonic()
    # Ключ кэша: каталог данных и расширения, чтобы смена настроек не отдавала чужой список.
    cache_key = (str(settings.DATA_DIR), tuple(settings.ALLOWED_EXTENSIONS))
    with _docs_cache_lock:
        cached = _docs_cache.get("docs")
        if (
            cached is not None
            and _docs_cache.get("key") == cache_key
            and (now - float(_docs_cache.get("at") or 0.0)) < _DOCS_CACHE_TTL_SEC
        ):
            return list(cached)
    docs = _scan_documents()
    with _docs_cache_lock:
        _docs_cache["docs"] = docs
        _docs_cache["at"] = now
        _docs_cache["key"] = cache_key
    return list(docs)


def _find_existing_document(filename: str) -> Path | None:
    """Найти существующий документ с таким именем только внутри DATA_DIR."""
    safe_name = safe_filename(filename)
    if not safe_name:
        return None
    data_dir = Path(settings.DATA_DIR)
    candidates = [Path(settings.UPLOAD_DIR) / safe_name, data_dir / safe_name]
    if data_dir.exists():
        candidates.extend(path for path in data_dir.rglob(safe_name) if path.is_file())
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(data_dir.resolve())
        except ValueError:
            continue
        if _is_under_attachments(resolved):
            continue
        if resolved.is_file() and _allowed_file(resolved.name):
            return resolved
    return None


def _extract_preview_text(path: Path) -> str:
    from create_vector_db import get_file_handlers

    handler = get_file_handlers().get(path.suffix.lower())
    if not handler:
        return ""
    doc_data = handler(path)
    return (doc_data or {}).get("content") or ""


def _text_version_diff(old_text: str, new_text: str) -> dict:
    old_lines = [line.strip() for line in old_text.splitlines() if line.strip()]
    new_lines = [line.strip() for line in new_text.splitlines() if line.strip()]
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    added = []
    removed = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"insert", "replace"}:
            added.extend(new_lines[j1:j2])
        if tag in {"delete", "replace"}:
            removed.extend(old_lines[i1:i2])
    return {
        "changed": bool(added or removed),
        "similarity": round(matcher.ratio(), 3),
        "old_length": len(old_text),
        "new_length": len(new_text),
        "added": added[:8],
        "removed": removed[:8],
    }


def _related_score(doc: dict, source: dict) -> int:
    doc_path = str(doc.get("path") or "")
    source_path = str(source.get("path") or "")
    source_title = str(source.get("title") or source.get("source") or "")
    if not doc_path or doc_path == source_path:
        return 0

    score = 0
    doc_parent = str(Path(doc_path).parent).replace("\\", "/")
    source_parent = str(Path(source_path).parent).replace("\\", "/")
    if doc_parent and doc_parent == source_parent:
        score += 6
    if source_parent and doc_path.startswith(source_parent + "/"):
        score += 3

    title_words = {word.lower() for word in source_title.replace(".", " ").split() if len(word) > 3}
    doc_words = {word.lower() for word in f"{doc.get('filename', '')} {doc_path}".replace(".", " ").split() if len(word) > 3}
    score += min(len(title_words & doc_words), 4)
    return score


def _find_related_documents(sources: list[dict], limit: int = 5) -> list[dict]:
    documents = _get_documents_cached()
    scored: dict[str, dict] = {}
    for source in sources:
        for doc in documents:
            score = _related_score(doc, source)
            if score <= 0:
                continue
            key = doc["path"]
            existing = scored.get(key)
            if not existing or score > existing["score"]:
                scored[key] = {**doc, "score": score, "reason": "Похожая папка или название источника"}
    return sorted(scored.values(), key=lambda item: item["score"], reverse=True)[:limit]


def _resolve_document_path(raw_path: str | None) -> Path | None:
    """Разрешить путь только внутри DATA_DIR, чтобы не отдавать произвольные файлы."""
    if not raw_path or raw_path == "N/A":
        return None

    data_dir = Path(settings.DATA_DIR).resolve()
    requested = Path(raw_path)
    candidates = [requested] if requested.is_absolute() else [data_dir / requested, requested]

    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(data_dir)
        except ValueError:
            continue
        if _is_under_attachments(resolved):
            continue
        if resolved.is_file() and _allowed_file(resolved.name):
            return resolved
    return None


def _parse_job_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _prune_jobs_locked(now: datetime | None = None) -> None:
    """Ограничить историю jobs по TTL и размеру. Вызывать только под _jobs_lock."""
    now = now or datetime.now()
    stale_ids = []
    for job_id, job in _jobs.items():
        if job.get("status") in _JOB_STATUSES_ACTIVE:
            continue
        finished_at = _parse_job_dt(job.get("finished_at"))
        started_at = _parse_job_dt(job.get("started_at"))
        marker = finished_at or started_at
        if marker and now - marker > _JOBS_TTL:
            stale_ids.append(job_id)
    for job_id in stale_ids:
        _jobs.pop(job_id, None)

    if len(_jobs) <= _JOBS_MAX_ITEMS:
        return
    ordered = sorted(
        _jobs.items(),
        key=lambda item: item[1].get("started_at", ""),
        reverse=True,
    )
    keep = {job_id for job_id, _job in ordered[:_JOBS_MAX_ITEMS]}
    for job_id, job in list(_jobs.items()):
        if job_id not in keep and job.get("status") not in _JOB_STATUSES_ACTIVE:
            _jobs.pop(job_id, None)


def _active_reindex_job_locked() -> dict | None:
    """Вернуть активную задачу reindex. Вызывать только под _jobs_lock."""
    for job in sorted(_jobs.values(), key=lambda item: item.get("started_at", ""), reverse=True):
        if job.get("status") in _JOB_STATUSES_ACTIVE:
            return dict(job)
    return None


def _create_reindex_job() -> tuple[dict | None, dict | None]:
    """Создать pending job или вернуть текущую активную job для 409."""
    now = datetime.now()
    with _jobs_lock:
        _prune_jobs_locked(now)
        active = _active_reindex_job_locked()
        if active:
            return None, active

        job_id = str(uuid4())
        job = {
            "id": job_id,
            "status": "pending",
            "stage": "pending",
            "progress": 0,
            "message": "Ожидает запуска",
            "started_at": now.isoformat(),
            "finished_at": None,
        }
        _jobs[job_id] = job
        return dict(job), None


def _set_job(job_id: str, **updates) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(updates)


def _truthy_flag(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _run_reindex(job_id: str) -> None:
    _set_job(job_id, status="running", stage="scan", progress=1, message="Сканирование документов")
    try:
        from create_vector_db import reindex_vector_db

        diagnostics = reindex_vector_db(progress_callback=lambda updates: _set_job(job_id, **updates))
        _invoke_reindex_callback()
        _invalidate_documents_cache()
        indexed_chunks = diagnostics.get("chunks_added") or diagnostics.get("chunks") or 0
        mode = diagnostics.get("index_mode") or "unknown"
        _set_job(
            job_id,
            status="done",
            stage="done",
            progress=100,
            message=f"Индексация завершена ({mode}): {indexed_chunks} чанков обновлено",
            diagnostics=diagnostics,
            finished_at=datetime.now().isoformat(),
        )
    except Exception as exc:
        logger.error("Ошибка индексации:\n%s", traceback.format_exc())
        _set_job(
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            message=str(exc),
            finished_at=datetime.now().isoformat(),
        )


@documents_bp.route("", methods=["GET"])
def list_documents():
    """Список документов из DATA_DIR/UPLOAD_DIR."""
    return jsonify({"documents": _get_documents_cached()})


@documents_bp.route("/open", methods=["GET"])
def open_document():
    """Открыть исходный документ по относительному пути из базы знаний.

    Файлы `.html`/`.htm` отдаются как `text/plain` с `Content-Disposition: attachment`,
    чтобы браузер не исполнял разметку. Остальные типы — inline с `nosniff`.
    Файлы из каталога вложений чата не отдаются.
    """
    document_path = _resolve_document_path(request.args.get("path"))
    if not document_path:
        return jsonify({"error": "Документ не найден"}), 404

    ext = file_extension(document_path.name)
    if ext in {"html", "htm"}:
        response = send_file(
            document_path,
            mimetype="text/plain; charset=utf-8",
            as_attachment=True,
            download_name=document_path.name,
        )
    else:
        response = send_file(
            document_path,
            as_attachment=False,
            download_name=document_path.name,
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@documents_bp.route("/upload", methods=["POST"])
def upload_document():
    """Загрузить документ в UPLOAD_DIR.

    При конфликте имени отвечает 409 с полем ``existing``, если не передан
    ``overwrite=true`` (query или form).
    """
    if "file" not in request.files:
        return jsonify({"error": "Файл не передан"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Имя файла пустое"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"error": "Формат файла не поддерживается"}), 400
    size_error, size_status = _upload_size_error(file)
    if size_error:
        return jsonify({"error": size_error}), size_status

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(file.filename)
    if not _allowed_file(filename):
        return jsonify({"error": "Формат файла не поддерживается"}), 400
    target = upload_dir / filename

    overwrite = _truthy_flag(request.args.get("overwrite")) or _truthy_flag(
        request.form.get("overwrite")
    )
    if target.exists() and not overwrite:
        return jsonify({
            "error": "exists",
            "message": "Файл с таким именем уже есть",
            "existing": _file_record(target),
        }), 409

    file.save(target)
    _invalidate_documents_cache()
    logger.info("Загружен документ: %s", target)
    return jsonify({"document": _file_record(target)}), 201


@documents_bp.route("/preview", methods=["POST"])
def preview_document_upload():
    """Предпросмотр индексации без сохранения файла в базу знаний."""
    if "file" not in request.files:
        return jsonify({"error": "Файл не передан"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Имя файла пустое"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"error": "Формат файла не поддерживается"}), 400
    size_error, size_status = _upload_size_error(file)
    if size_error:
        return jsonify({"error": size_error}), size_status

    filename = safe_filename(file.filename)
    existing_document = _find_existing_document(filename)
    duplicate_exists = existing_document is not None
    try:
        from create_vector_db import preview_document

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / filename
            file.save(temp_path)
            preview = preview_document(temp_path, duplicate_exists=duplicate_exists)
            if existing_document and preview.get("supported"):
                old_text = _extract_preview_text(existing_document)
                new_text = _extract_preview_text(temp_path)
                preview["version_diff"] = {
                    "existing_path": str(existing_document.relative_to(Path(settings.DATA_DIR))).replace("\\", "/"),
                    **_text_version_diff(old_text, new_text),
                }
    except Exception:
        logger.error("Ошибка предпросмотра документа:\n%s", traceback.format_exc())
        return jsonify({"error": "Ошибка предпросмотра документа"}), 500

    return jsonify({"preview": preview})


@documents_bp.route("/related", methods=["POST"])
def related_documents():
    """Подобрать соседние документы по источникам ответа."""
    data = request.get_json(silent=True) or {}
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        return jsonify({"error": "sources должен быть списком"}), 400
    limit = data.get("limit") or 5
    try:
        limit = max(1, min(int(limit), 10))
    except (TypeError, ValueError):
        limit = 5
    return jsonify({"documents": _find_related_documents(sources, limit=limit)})


@documents_bp.route("/reindex", methods=["POST"])
def reindex_documents():
    """Запустить переиндексацию в фоновом потоке."""
    job, active = _create_reindex_job()
    if active:
        return jsonify({
            "error": "reindex_already_running",
            "message": "Переиндексация уже выполняется",
            "active_job": active,
        }), 409

    thread = threading.Thread(target=_run_reindex, args=(job["id"],), daemon=True)
    thread.start()
    return jsonify({"job": job}), 202


@documents_bp.route("/jobs", methods=["GET"])
def list_jobs():
    """Последние задачи индексации."""
    with _jobs_lock:
        _prune_jobs_locked()
        jobs = sorted(_jobs.values(), key=lambda item: item.get("started_at", ""), reverse=True)
    return jsonify({"jobs": [dict(job) for job in jobs[:20]]})


@documents_bp.route("/images/<occurrence_id>", methods=["GET"])
def get_knowledge_image(occurrence_id):
    """Выдать изображение визуального источника (ТЗ §16.2).

    ID разрешается через каталог; путь файловой системы из запроса не принимается.
    """
    from core.visual_serving import KnowledgeImageService

    variant = (request.args.get("variant") or "original").strip().lower()
    if variant not in {"original", "preview", "thumbnail"}:
        return jsonify({"error": "invalid_variant"}), 400
    try:
        service = KnowledgeImageService()
        response = service.resolve(occurrence_id, variant=variant)
    except Exception as exc:
        logger.exception("Ошибка выдачи изображения %s", occurrence_id)
        return jsonify({"error": "image_error", "message": str(exc)}), 500

    if response.error_code:
        status = 404 if response.error_code in ("not_found", "no_asset") else 410
        return jsonify({"error": response.error_code}), status

    if request.headers.get("If-None-Match") == response.etag:
        return ("", 304, {"ETag": response.etag})

    import io as _io

    payload = _io.BytesIO(response.data)
    resp = send_file(
        payload,
        mimetype=response.mime_type,
        as_attachment=response.download_only,
        download_name=f"{occurrence_id.replace(':', '_')}",
        max_age=3600,
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["ETag"] = response.etag
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp
