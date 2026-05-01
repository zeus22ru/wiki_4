#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API управления базой знаний и задачами индексации."""

from datetime import datetime
from pathlib import Path
import difflib
import tempfile
import threading
import traceback
from uuid import uuid4

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from api.middleware.auth import require_admin_access
from config import settings, get_logger

logger = get_logger(__name__)
documents_bp = Blueprint("documents", __name__, url_prefix="/api/documents")


@documents_bp.before_request
def require_admin_role():
    """Управление базой знаний доступно только администраторам."""
    return require_admin_access()

_jobs = {}
_jobs_lock = threading.Lock()


def _allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in {x.strip().lower() for x in settings.ALLOWED_EXTENSIONS}


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


def _scan_documents() -> list[dict]:
    data_dir = Path(settings.DATA_DIR)
    allowed = {f".{x.strip().lower()}" for x in settings.ALLOWED_EXTENSIONS}
    if not data_dir.exists():
        return []
    docs = []
    for path in data_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in allowed:
            docs.append(_file_record(path))
    docs.sort(key=lambda item: item["modified_at"], reverse=True)
    return docs


def _find_existing_document(filename: str) -> Path | None:
    """Найти существующий документ с таким именем только внутри DATA_DIR."""
    safe_name = secure_filename(filename)
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
    documents = _scan_documents()
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
        if resolved.is_file() and _allowed_file(resolved.name):
            return resolved
    return None


def _set_job(job_id: str, **updates) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(updates)


def _run_reindex(job_id: str) -> None:
    _set_job(job_id, status="running", message="Индексация запущена")
    try:
        from create_vector_db import create_vector_db, process_all_files

        documents = process_all_files(settings.DATA_DIR)
        if not documents:
            _set_job(
                job_id,
                status="failed",
                message="Не найдено документов для индексации",
                finished_at=datetime.now().isoformat(),
            )
            return
        create_vector_db(documents)
        _set_job(
            job_id,
            status="done",
            message=f"Индексация завершена: {len(documents)} чанков",
            finished_at=datetime.now().isoformat(),
        )
    except Exception as exc:
        logger.error("Ошибка индексации:\n%s", traceback.format_exc())
        _set_job(
            job_id,
            status="failed",
            message=str(exc),
            finished_at=datetime.now().isoformat(),
        )


@documents_bp.route("", methods=["GET"])
def list_documents():
    """Список документов из DATA_DIR/UPLOAD_DIR."""
    return jsonify({"documents": _scan_documents()})


@documents_bp.route("/open", methods=["GET"])
def open_document():
    """Открыть исходный документ по относительному пути из базы знаний."""
    document_path = _resolve_document_path(request.args.get("path"))
    if not document_path:
        return jsonify({"error": "Документ не найден"}), 404
    return send_file(document_path, as_attachment=False, download_name=document_path.name)


@documents_bp.route("/upload", methods=["POST"])
def upload_document():
    """Загрузить документ в UPLOAD_DIR."""
    if "file" not in request.files:
        return jsonify({"error": "Файл не передан"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Имя файла пустое"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"error": "Формат файла не поддерживается"}), 400

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(file.filename)
    target = upload_dir / filename
    file.save(target)
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

    filename = secure_filename(file.filename)
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
    job_id = str(uuid4())
    now = datetime.now().isoformat()
    _set_job(job_id, id=job_id, status="pending", message="Ожидает запуска", started_at=now, finished_at=None)
    thread = threading.Thread(target=_run_reindex, args=(job_id,), daemon=True)
    thread.start()
    return jsonify({"job": _jobs[job_id]}), 202


@documents_bp.route("/jobs", methods=["GET"])
def list_jobs():
    """Последние задачи индексации."""
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda item: item.get("started_at", ""), reverse=True)
    return jsonify({"jobs": jobs[:20]})
