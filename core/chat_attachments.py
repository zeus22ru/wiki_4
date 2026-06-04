#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хранение и загрузка вложений к вопросам чата."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from config import settings, get_logger

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "gif"})
_TEXT_EXTENSIONS = frozenset({
    "txt", "log", "md", "json", "xml", "csv", "yaml", "yml", "ini", "env",
})
_ATTACHMENT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


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


def _extension_for(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def classify_attachment(filename: str, mime: str = "") -> str:
    ext = _extension_for(filename)
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext in _TEXT_EXTENSIONS:
        return "text"
    guessed, _ = mimetypes.guess_type(filename)
    mime = (mime or guessed or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/") or mime in ("application/json", "application/xml"):
        return "text"
    raise ChatAttachmentError(f"Неподдерживаемый тип файла: {filename}")


def _guess_mime(filename: str, kind: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    if kind == "image":
        ext = _extension_for(filename)
        return {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
        }.get(ext, "application/octet-stream")
    return "text/plain"


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


def save_uploaded_file(file: FileStorage) -> ChatAttachment:
    if not attachments_enabled():
        raise ChatAttachmentError("Вложения к чату отключены")

    filename = secure_filename(file.filename or "") or "file"
    ext = _extension_for(filename)
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

    kind = classify_attachment(filename, file.mimetype or "")
    attachment_id = str(uuid4())
    target = _storage_path(attachment_id, ext)
    file.save(str(target))
    meta_path = _attachments_dir() / f"{attachment_id}.meta.json"
    meta_path.write_text(
        json.dumps({"filename": filename, "mime": file.mimetype or ""}, ensure_ascii=False),
        encoding="utf-8",
    )
    actual_size = target.stat().st_size
    mime = _guess_mime(filename, kind)

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
    mime_override = ""
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            display_name = str(meta.get("filename") or display_name)
            mime_override = str(meta.get("mime") or "")
        except (OSError, json.JSONDecodeError):
            pass
    ext = _extension_for(display_name)
    kind = classify_attachment(display_name if ext else f"file.{path.suffix.lstrip('.')}")
    mime = mime_override or _guess_mime(display_name, kind)
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
    return f"data:{attachment.mime};base64,{data}"


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
