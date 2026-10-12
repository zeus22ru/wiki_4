#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Управление пользователями из админки.

Все маршруты доступны только роли ``admin``. Пароли не раскрываются.
"""

from __future__ import annotations

import sqlite3

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from api.middleware.auth import get_current_user, require_admin_access
from api.user_validation import (
    VALID_ROLES,
    validate_email,
    validate_password,
    validate_username,
)
from config import get_logger
from core.chat_history import get_chat_history

logger = get_logger(__name__)

admin_users_bp = Blueprint("admin_users", __name__, url_prefix="/api/admin/users")

_DEFAULT_PER_PAGE = 25
_MAX_PER_PAGE = 100


@admin_users_bp.before_request
def require_admin_role():
    """Управление пользователями доступно только роли admin."""
    return require_admin_access()


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _serialize_user(user, stats: dict | None = None) -> dict:
    payload = user.to_dict()
    payload["stats"] = stats or {}
    return payload


def _parse_bool(value):
    """Разобрать boolean из JSON/строки. ``None`` — значение не передано."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ValueError("Некорректное значение активности")


def _is_last_active_admin(history, target) -> bool:
    """True, если target — последний активный администратор."""
    if not target or target.role != "admin" or not target.is_active:
        return False
    return history.count_active_admins() <= 1


@admin_users_bp.route("", methods=["GET"])
def list_users():
    """Список пользователей с фильтрами и пагинацией."""
    query = (request.args.get("query") or "").strip()
    role = (request.args.get("role") or "").strip()
    status = (request.args.get("status") or "").strip().lower()

    is_active = None
    if status in ("active", "1", "true"):
        is_active = True
    elif status in ("blocked", "inactive", "0", "false"):
        is_active = False

    if role and role not in VALID_ROLES:
        return jsonify({"error": "Неизвестная роль"}), 400

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", _DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = _DEFAULT_PER_PAGE
    per_page = max(1, min(per_page, _MAX_PER_PAGE))

    history = get_chat_history()
    users, total = history.list_users(
        query=query or None,
        role=role or None,
        is_active=is_active,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    stats_map = history.get_user_stats_map([u.id for u in users])
    return jsonify({
        "users": [_serialize_user(u, stats_map.get(u.id, {})) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@admin_users_bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id: int):
    """Карточка пользователя: профиль, статистика, последние чаты."""
    history = get_chat_history()
    user = history.get_user(user_id)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404

    stats = history.get_user_stats(user_id)
    recent = [
        {
            "id": session.id,
            "title": session.title,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        }
        for session in history.get_sessions(user_id=user_id, limit=5)
    ]
    return jsonify({"user": _serialize_user(user, stats), "recent_chats": recent})


@admin_users_bp.route("", methods=["POST"])
def create_user():
    """Создать пользователя (логин, email, пароль, роль, активность)."""
    data = _json_body()
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or "user").strip()

    error = validate_username(username) or validate_email(email)
    if error:
        return jsonify({"error": error}), 400
    error = validate_password(password, username)
    if error:
        return jsonify({"error": error}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": "Неизвестная роль"}), 400

    try:
        is_active = _parse_bool(data.get("is_active"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    is_active = True if is_active is None else is_active

    history = get_chat_history()
    try:
        user = history.create_user(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            is_active=is_active,
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "Пользователь с таким email или именем уже существует"}), 409

    logger.info("Админ создал пользователя id=%s role=%s", user.id, user.role)
    return jsonify({"user": _serialize_user(user, history.get_user_stats(user.id))}), 201


@admin_users_bp.route("/<int:user_id>", methods=["PATCH"])
def update_user(user_id: int):
    """Изменить логин, email, роль и/или активность пользователя."""
    data = _json_body()
    history = get_chat_history()
    target = history.get_user(user_id)
    if not target:
        return jsonify({"error": "Пользователь не найден"}), 404

    current = get_current_user()
    is_self = bool(current and current.id == target.id)

    username = data.get("username") if "username" in data else None
    email = data.get("email") if "email" in data else None
    role = data.get("role") if "role" in data else None
    raw_active = data.get("is_active") if "is_active" in data else None

    try:
        is_active = _parse_bool(raw_active)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if username is not None:
        username = str(username).strip()
        error = validate_username(username)
        if error:
            return jsonify({"error": error}), 400
    if email is not None:
        email = str(email).strip().lower()
        error = validate_email(email)
        if error:
            return jsonify({"error": error}), 400
    if role is not None:
        role = str(role).strip()
        if role not in VALID_ROLES:
            return jsonify({"error": "Неизвестная роль"}), 400

    demoting = role is not None and role != "admin"
    deactivating = is_active is False

    if is_self and (demoting or deactivating):
        return jsonify({"error": "Нельзя снять роль admin или заблокировать самого себя"}), 400

    if (demoting or deactivating) and _is_last_active_admin(history, target):
        return jsonify({"error": "Нельзя снять роль или заблокировать последнего администратора"}), 400

    # Ничего не меняем, если новых значений нет.
    if username is None and email is None and role is None and is_active is None:
        return jsonify({"error": "Нет данных для обновления"}), 400

    try:
        history.update_user(
            user_id,
            username=username,
            email=email,
            role=role,
            is_active=is_active,
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "Пользователь с таким email или именем уже существует"}), 409

    updated = history.get_user(user_id)
    logger.info("Админ обновил пользователя id=%s", user_id)
    return jsonify({"user": _serialize_user(updated, history.get_user_stats(user_id))})


@admin_users_bp.route("/<int:user_id>/password", methods=["POST"])
def reset_password(user_id: int):
    """Сбросить пароль пользователя (задаёт новый администратор)."""
    data = _json_body()
    new_password = data.get("new_password") or ""

    history = get_chat_history()
    target = history.get_user(user_id)
    if not target:
        return jsonify({"error": "Пользователь не найден"}), 404

    error = validate_password(new_password, target.username)
    if error:
        return jsonify({"error": error}), 400

    if not history.update_user_password(user_id, generate_password_hash(new_password)):
        return jsonify({"error": "Не удалось сохранить пароль"}), 500

    logger.info("Админ сбросил пароль пользователю id=%s", user_id)
    return jsonify({"ok": True})
