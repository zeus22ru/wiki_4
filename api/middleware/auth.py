#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хелперы авторизации и проверки ролей."""

from functools import wraps
from uuid import uuid4

from flask import jsonify, session as flask_session

from core.chat_history import get_chat_history
from models import ChatSession, User


def get_current_user() -> User | None:
    """Вернуть текущего активного пользователя из Flask session."""
    user_id = flask_session.get("user_id")
    if not user_id:
        return None
    user = get_chat_history().get_user(user_id)
    if not user or not user.is_active:
        flask_session.pop("user_id", None)
        flask_session.pop("role", None)
        return None
    if flask_session.get("role") != user.role:
        flask_session["role"] = user.role
    return user


def current_user_id() -> int | None:
    """ID текущего пользователя или None для гостя."""
    user = get_current_user()
    return user.id if user else None


def current_role() -> str:
    """Роль текущего пользователя: guest, user или admin."""
    user = get_current_user()
    return user.role if user else "guest"


def is_authenticated() -> bool:
    return get_current_user() is not None


def is_admin() -> bool:
    return current_role() == "admin"


def require_admin_access():
    """Проверка admin-доступа для before_request."""
    if is_admin():
        return None
    status = 401 if not is_authenticated() else 403
    return jsonify({"error": "Требуется роль admin"}), status


def admin_required(func):
    """Декоратор для маршрутов, доступных только администраторам."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        denial = require_admin_access()
        if denial:
            return denial
        return func(*args, **kwargs)

    return wrapper


def ensure_guest_id() -> str:
    """Создать стабильный ID гостя в подписанной cookie-сессии."""
    guest_id = flask_session.get("guest_id")
    if not guest_id:
        guest_id = str(uuid4())
        flask_session["guest_id"] = guest_id
    return guest_id


def get_guest_chat_ids() -> list[int]:
    """Список временных чатов гостя из cookie-сессии."""
    ensure_guest_id()
    raw_ids = flask_session.get("guest_chat_ids") or []
    result = []
    for value in raw_ids:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def remember_guest_chat(chat_id: int) -> None:
    """Привязать гостевой чат к текущей cookie-сессии."""
    ids = get_guest_chat_ids()
    if chat_id not in ids:
        ids.append(chat_id)
        flask_session["guest_chat_ids"] = ids[-50:]


def forget_guest_chat(chat_id: int) -> None:
    ids = [item for item in get_guest_chat_ids() if item != chat_id]
    flask_session["guest_chat_ids"] = ids


def clear_guest_chats() -> None:
    flask_session["guest_chat_ids"] = []


def can_access_chat(chat_session: ChatSession | None) -> bool:
    """Проверить владение чатом для пользователя или гостевой cookie-сессии."""
    if not chat_session:
        return False
    user = get_current_user()
    if user:
        return chat_session.user_id == user.id
    return chat_session.user_id is None and chat_session.id in get_guest_chat_ids()

