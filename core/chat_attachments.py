#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хранение и загрузка вложений к вопросам чата."""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from werkzeug.datastructures import FileStorage

from config import settings, get_logger
from utils.filenames import file_extension, safe_filename

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "gif"})
_TEXT_EXTENSIONS = frozenset({
    "txt", "log", "md", "json", "xml", "csv", "yaml", "yml", "ini", "env",
})
# MIME только по расширению (клиентский Content-Type не используется).
_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    # Текстовые, включая xml/json — как text/plain (без исполнения в браузере).
    "txt": "text/plain; charset=utf-8",
    "log": "text/plain; charset=utf-8",
    "md": "text/plain; charset=utf-8",
    "json": "text/plain; charset=utf-8",
    "xml": "text/plain; charset=utf-8",
    "csv": "text/plain; charset=utf-8",
    "yaml": "text/plain; charset=utf-8",
    "yml": "text/plain; charset=utf-8",
    "ini": "text/plain; charset=utf-8",
    "env": "text/plain; charset=utf-8",
}
_ATTACHMENT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Ленивая очистка старых вложений: не чаще раза в час.
_last_cleanup_monotonic: float = 0.0
_CLEANUP_INTERVAL_SEC = 3600.0


@dataclass
class ChatAttachment:
    id: str
    filename: str
    mime: str
    kind: str
    path: Path
    size: int
    text_content: Optional[str] = None

    def to_metadata_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "mime": self.mime,
            "kind": self.kind,
            "size": self.size,
        }


@dataclass
class AttachmentBundle:
    items: List[ChatAttachment] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return any(item.kind == "image" for item in self.items)

    @property
    def has_text_files(self) -> bool:
        return any(item.kind == "text" for item in self.items)

    def metadata_list(self) -> List[dict]:
        return [item.to_metadata_dict() for item in self.items]


class ChatAttachmentError(ValueError):
    """Ошибка валидации или загрузки вложения."""


def attachments_enabled() -> bool:
    return bool(getattr(settings, "CHAT_ATTACHMENTS_ENABLED", True))


def _allowed_extensions() -> set[str]:
    raw = getattr(settings, "CHAT_ATTACHMENT_ALLOWED_EXTENSIONS", []) or []
    return {x.strip().lower().lstrip(".") for x in raw if str(x).strip()}


def mime_for_filename(filename: str) -> str:
    """MIME по расширению из белого списка; иначе octet-stream."""
    ext = file_extension(filename)
    if ext in _MIME_BY_EXT:
        return _MIME_BY_EXT[ext]
    if ext in _IMAGE_EXTENSIONS:
        return "application/octet-stream"
    if ext in _TEXT_EXTENSIONS:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def classify_attachment(filename: str, mime: str = "") -> str:
    """Классифицировать вложение только по расширению (mime игнорируется)."""
    ext = file_extension(filename)
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext in _TEXT_EXTENSIONS:
        return "text"
    raise ChatAttachmentError(f"Неподдерживаемый тип файла: {filename}")


def _attachments_dir() -> Path:
    path = Path(getattr(settings, "CHAT_ATTACHMENTS_DIR", "./data/chat_attachments"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _storage_path(attachment_id: str, ext: str) -> Path:
    safe_ext = re.sub(r"[^a-zA-Z0-9]", "", ext)[:10]
    suffix = f".{safe_ext}" if safe_ext else ""
    return _attachments_dir() / f"{attachment_id}{suffix}"


def _read_upload_size(file: FileStorage) -> int:
    stream = getattr(file, "stream", None)
    if stream is None:
        return 0
    pos = stream.tell()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(pos)
    return int(size)


def cleanup_old_attachments(max_age_hours: float) -> int:
    """Удалить вложения и sidecar ``*.meta.json`` старше ``max_age_hours``.

    Возвращает число удалённых файлов данных (без учёта meta).
    """
    if max_age_hours <= 0:
        return 0
    base = _attachments_dir()
    cutoff = time.time() - (float(max_age_hours) * 3600.0)
    removed = 0
    for path in list(base.iterdir()) if base.exists() else []:
        if not path.is_file():
            continue
        if path.name.endswith(".meta.json"):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue
        # Имя вида <uuid>.<ext>
        stem = path.name
        attachment_id = stem.split(".", 1)[0] if "." in stem else stem
        meta_path = base / f"{attachment_id}.meta.json"
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning("Не удалось удалить старое вложение %s: %s", path, exc)
            continue
        try:
            meta_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Не удалось удалить meta вложения %s: %s", meta_path, exc)
    if removed:
        logger.info("Очистка вложений: удалено %s файлов старше %s ч", removed, max_age_hours)
    return removed


def _maybe_cleanup_old_attachments() -> None:
    """Ленивая очистка не чаще раза в час (без фоновых потоков)."""
    global _last_cleanup_monotonic
    now = time.monotonic()
    if (now - _last_cleanup_monotonic) < _CLEANUP_INTERVAL_SEC:
        return
    _last_cleanup_monotonic = now
    ttl = float(getattr(settings, "CHAT_ATTACHMENT_TTL_HOURS", 72))
    try:
        cleanup_old_attachments(ttl)
    except Exception:
        logger.exception("Ошибка очистки старых вложений")


def save_uploaded_file(file: FileStorage) -> ChatAttachment:
    if not attachments_enabled():
        raise ChatAttachmentError("Вложения к чату отключены")

    _maybe_cleanup_old_attachments()

    filename = safe_filename(file.filename or "", default="file")
    ext = file_extension(filename)
    if ext not in _allowed_extensions():
        raise ChatAttachmentError(
            f"Недопустимое расширение «{ext or '(нет)'}». "
            f"Разрешены: {', '.join(sorted(_allowed_extensions()))}"
        )

    size = _read_upload_size(file)
    max_bytes = int(getattr(settings, "CHAT_ATTACHMENT_MAX_BYTES", 5_242_880))
    if size > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise ChatAttachmentError(f"Файл слишком большой. Максимум: {limit_mb:.1f} МБ")

    kind = classify_attachment(filename)
    attachment_id = str(uuid4())
    target = _storage_path(attachment_id, ext)
    file.save(str(target))
    meta_path = _attachments_dir() / f"{attachment_id}.meta.json"
    # Клиентский MIME не сохраняем — тип определяется только по расширению.
    meta_path.write_text(
        json.dumps({"filename": filename}, ensure_ascii=False),
        encoding="utf-8",
    )
    actual_size = target.stat().st_size
    mime = mime_for_filename(filename)

    text_content = None
    if kind == "text":
        text_content = read_text_from_path(target, filename)

    logger.info("Сохранено вложение чата %s (%s, %s байт)", attachment_id, kind, actual_size)
    return ChatAttachment(
        id=attachment_id,
        filename=filename,
        mime=mime,
        kind=kind,
        path=target,
        size=actual_size,
        text_content=text_content,
    )


def read_text_from_path(path: Path, filename: str = "") -> str:
    max_chars = int(getattr(settings, "CHAT_ATTACHMENT_TEXT_MAX_CHARS", 32_000))
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ChatAttachmentError(f"Не удалось прочитать файл {filename or path.name}: {e}") from e
    if len(raw) > max_chars:
        return raw[: max_chars - 20] + "\n… [обрезано]"
    return raw


def _data_paths_for_id(base: Path, attachment_id: str) -> List[Path]:
    """Файлы вложения на диске (без sidecar *.meta.json)."""
    return sorted(
        (
            p
            for p in base.glob(f"{attachment_id}.*")
            if p.is_file() and not p.name.endswith(".meta.json")
        ),
        key=lambda p: p.name,
    )


def load_attachment(attachment_id: str) -> Optional[ChatAttachment]:
    if not _ATTACHMENT_ID_RE.match(attachment_id or ""):
        return None
    base = _attachments_dir()
    matches = _data_paths_for_id(base, attachment_id)
    if not matches:
        return None
    path = matches[0]
    meta_path = base / f"{attachment_id}.meta.json"
    display_name = path.name
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            display_name = str(meta.get("filename") or display_name)
        except (OSError, json.JSONDecodeError):
            pass
    ext = file_extension(display_name)
    kind = classify_attachment(display_name if ext else f"file.{path.suffix.lstrip('.')}")
    mime = mime_for_filename(display_name if ext else f"file.{path.suffix.lstrip('.')}")
    text_content = read_text_from_path(path, display_name) if kind == "text" else None
    return ChatAttachment(
        id=attachment_id,
        filename=display_name,
        mime=mime,
        kind=kind,
        path=path,
        size=path.stat().st_size,
        text_content=text_content,
    )


def load_attachments(attachment_ids: List[str]) -> AttachmentBundle:
    if not attachment_ids:
        return AttachmentBundle()
    max_count = int(getattr(settings, "CHAT_ATTACHMENT_MAX_COUNT", 3))
    if len(attachment_ids) > max_count:
        raise ChatAttachmentError(f"Слишком много вложений. Максимум: {max_count}")

    items: List[ChatAttachment] = []
    seen = set()
    for raw_id in attachment_ids:
        aid = str(raw_id or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        item = load_attachment(aid)
        if item is None:
            raise ChatAttachmentError(f"Вложение не найдено: {aid}")
        items.append(item)
    if not items:
        raise ChatAttachmentError("Не указаны корректные вложения")
    return AttachmentBundle(items=items)


def image_to_data_url(attachment: ChatAttachment) -> str:
    if attachment.kind != "image":
        raise ChatAttachmentError("Не изображение")
    data = base64.b64encode(attachment.path.read_bytes()).decode("ascii")
    # Для data URL берём базовый тип без параметров charset.
    mime = attachment.mime.split(";", 1)[0].strip() or "application/octet-stream"
    return f"data:{mime};base64,{data}"


def format_text_excerpts(bundle: AttachmentBundle) -> str:
    parts: List[str] = []
    for item in bundle.items:
        if item.kind != "text" or not item.text_content:
            continue
        parts.append(f"--- Файл: {item.filename} ---\n{item.text_content}")
    return "\n\n".join(parts)


def user_message_display_text(query: str, bundle: Optional[AttachmentBundle]) -> str:
    text = (query or "").strip()
    if text:
        return text
    if bundle and bundle.items:
        names = ", ".join(item.filename for item in bundle.items)
        return f"(вложения: {names})"
    return ""
