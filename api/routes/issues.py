#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API для отправки user-reports в GitHub Issues."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from flask import Blueprint, jsonify, request

from api.middleware.auth import (
    can_access_chat,
    current_role,
    ensure_guest_id,
    get_current_user,
)
from config import get_logger, settings
from core.chat_history import get_chat_history
from integrations.github_issues import (
    GitHubIssuesError,
    create_github_issue,
    github_issues_configured,
)
from utils.issue_rate_limit import IssueRateLimiter

logger = get_logger(__name__)

issues_bp = Blueprint("issues", __name__, url_prefix="/api/issues")

_ISSUE_TYPES = {
    "bug": "Ошибка в интерфейсе",
    "wrong_answer": "Неверный ответ",
    "missing_info": "Нет информации в базе",
    "idea": "Идея / улучшение",
    "other": "Другое",
}

_rate_limiter = IssueRateLimiter(settings.GITHUB_ISSUES_RATE_LIMIT_PER_HOUR)


def _clip_text(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _parse_labels(raw: str) -> list[str]:
    labels = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return labels[:10]


def _issue_title(issue_type: str, title: str) -> str:
    prefix = _ISSUE_TYPES.get(issue_type, "Report")
    clean_title = _clip_text(title, 180)
    return _clip_text(f"[{prefix}] {clean_title}", 200)


def _find_message_context(session_id: int | None, message_id: int | None) -> dict[str, Any] | None:
    if session_id is None or message_id is None:
        return None

    chat_history = get_chat_history()
    session = chat_history.get_session(session_id)
    if not can_access_chat(session):
        return None

    messages = chat_history.get_messages(session_id)
    target_idx = next((idx for idx, msg in enumerate(messages) if msg.id == message_id), None)
    if target_idx is None:
        return None

    bot_message = messages[target_idx]
    user_question = None
    for idx in range(target_idx - 1, -1, -1):
        if messages[idx].role == "user":
            user_question = messages[idx].content
            break

    sources = bot_message.sources or []
    source_lines = []
    for source in sources[:8]:
        if isinstance(source, dict):
            title = source.get("title") or source.get("path") or "source"
            path = source.get("path") or source.get("source") or ""
            source_lines.append(f"- {title}" + (f" (`{path}`)" if path else ""))

    return {
        "session_id": session_id,
        "message_id": message_id,
        "user_question": _clip_text(user_question, 4000),
        "bot_answer": _clip_text(bot_message.content, 4000),
        "sources": source_lines,
    }


def _build_issue_body(
    *,
    issue_type: str,
    description: str,
    contact: str | None,
    guest_id: str,
    role: str,
    username: str | None,
    user_agent: str,
    context: dict[str, Any] | None,
) -> str:
    lines = [
        "## Описание",
        description or "_Без описания_",
        "",
        "## Тип",
        _ISSUE_TYPES.get(issue_type, issue_type),
        "",
    ]

    if context:
        lines.extend(["## Контекст диалога", ""])
        if context.get("user_question"):
            lines.extend(["**Вопрос пользователя:**", context["user_question"], ""])
        if context.get("bot_answer"):
            lines.extend(["**Ответ ассистента:**", context["bot_answer"], ""])
        if context.get("sources"):
            lines.extend(["**Источники:**", *context["sources"], ""])

    if contact:
        lines.extend(["## Контакт", contact, ""])

    ip_hash = hashlib.sha256((request.remote_addr or "unknown").encode("utf-8")).hexdigest()[:12]
    meta = [
        "---",
        f"_Reported via БочкарИИ · role `{role}`",
        f"· guest `{guest_id[:8]}...` · ip `{ip_hash}`",
    ]
    if username:
        meta.append(f"· user `{username}`")
    if context:
        meta.append(f"· session `{context.get('session_id')}` · message `{context.get('message_id')}`")
    meta.append(f"· ua `{_clip_text(user_agent, 200)}`_")
    lines.extend(meta)
    return "\n".join(lines)


@issues_bp.route("/status", methods=["GET"])
def issue_status():
    """Публичный статус интеграции (без секретов)."""
    configured = github_issues_configured(settings.GITHUB_TOKEN, settings.GITHUB_REPO)
    return jsonify({
        "enabled": settings.GITHUB_ISSUES_ENABLED,
        "configured": configured,
        "stub": settings.GITHUB_ISSUES_ENABLED and not configured,
        "repo": settings.GITHUB_REPO if configured else None,
        "types": [{"id": key, "label": label} for key, label in _ISSUE_TYPES.items()],
    })


@issues_bp.route("", methods=["POST"])
def create_issue():
    if not settings.GITHUB_ISSUES_ENABLED:
        return jsonify({"error": "Отправка issue отключена"}), 503

    data = request.get_json(silent=True) or {}

    if (data.get("website") or "").strip():
        return jsonify({"error": "Запрос отклонён"}), 400

    issue_type = (data.get("type") or "other").strip().lower()
    if issue_type not in _ISSUE_TYPES:
        return jsonify({"error": "Недопустимый тип issue"}), 400

    title = _clip_text(data.get("title"), 200)
    description = _clip_text(data.get("description"), 4000)
    if not title:
        return jsonify({"error": "Укажите заголовок"}), 400
    if len(description) < 10:
        return jsonify({"error": "Описание должно быть не короче 10 символов"}), 400

    contact = _clip_text(data.get("contact"), 200) or None
    if contact and not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", contact):
        return jsonify({"error": "Некорректный email"}), 400

    session_id = data.get("session_id")
    message_id = data.get("message_id")
    try:
        session_id = int(session_id) if session_id is not None else None
        message_id = int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный идентификатор чата или сообщения"}), 400

    if session_id is not None or message_id is not None:
        chat_history = get_chat_history()
        session = chat_history.get_session(session_id) if session_id is not None else None
        if not can_access_chat(session):
            return jsonify({"error": "Нет доступа к указанному чату"}), 403

    guest_id = ensure_guest_id()
    rate_key = f"{request.remote_addr or 'unknown'}:{guest_id}"
    if not _rate_limiter.allow(rate_key):
        return jsonify({"error": "Слишком много обращений. Попробуйте позже."}), 429

    user = get_current_user()
    context = _find_message_context(session_id, message_id)
    body = _build_issue_body(
        issue_type=issue_type,
        description=description,
        contact=contact,
        guest_id=guest_id,
        role=current_role(),
        username=user.username if user else None,
        user_agent=str(request.user_agent or ""),
        context=context,
    )

    try:
        result = create_github_issue(
            title=_issue_title(issue_type, title),
            body=body,
            token=settings.GITHUB_TOKEN,
            repo=settings.GITHUB_REPO,
            labels=_parse_labels(settings.GITHUB_ISSUE_LABELS),
        )
    except GitHubIssuesError as exc:
        logger.error("Ошибка GitHub Issues: %s", exc)
        return jsonify({"error": str(exc)}), 502

    payload = result.to_dict()
    payload["message"] = (
        "Issue создан (демо-режим, GitHub не настроен)"
        if result.stub
        else "Issue создан на GitHub"
    )
    return jsonify(payload), 201
