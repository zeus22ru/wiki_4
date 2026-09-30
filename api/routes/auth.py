#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регистрация, вход и текущий пользователь."""

from __future__ import annotations

import re
import sqlite3
import threading
import time

from flask import Blueprint, jsonify, request, session as flask_session
from werkzeug.security import check_password_hash, generate_password_hash

from api.middleware.auth import ensure_guest_id, get_current_user
from core.chat_history import get_chat_history

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

_USERNAME_RE = re.compile(r"^[A-Za-zА-Яа-я0-9_.-]{3,50}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MIN_PASSWORD_LENGTH = 8


class LoginAttemptLimiter:
    """Лимит неудачных входов: 10 за 15 минут на пару (IP, identifier)."""

    def __init__(
        self,
        max_attempts: int = 10,
        window_seconds: float = 900.0,
        max_keys: int = 10_000,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = float(window_seconds)
        self.max_keys = max(100, int(max_keys))
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        window_start = now - self.window_seconds
        empty: list[str] = []
        for key, events in self._events.items():
            kept = [ts for ts in events if ts >= window_start]
            if kept:
                self._events[key] = kept
            else:
                empty.append(key)
        for key in empty:
            self._events.pop(key, None)
        while len(self._events) > self.max_keys:
            oldest = min(self._events, key=lambda k: self._events[k][0])
            self._events.pop(oldest, None)

    def is_blocked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            self._purge(now)
            events = self._events.get(key, [])
            return len(events) >= self.max_attempts

    def register_failure(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            self._purge(now)
            events = self._events.setdefault(key, [])
            events.append(now)
            return len(events) >= self.max_attempts

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_login_limiter = LoginAttemptLimiter()


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _user_payload(user=None) -> dict:
    if not user:
        ensure_guest_id()
        return {"authenticated": False, "role": "guest", "user": None}
    return {"authenticated": True, "role": user.role, "user": user.to_dict()}


def _validate_registration(data: dict) -> tuple[str, str, str] | tuple[None, None, None]:
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not _USERNAME_RE.match(username):
        return None, None, "Имя пользователя: 3-50 символов, буквы, цифры, точка, дефис или подчёркивание"
    if not _EMAIL_RE.match(email) or len(email) > 255:
        return None, None, "Укажите корректный email"
    if len(password) < _MIN_PASSWORD_LENGTH:
        return None, None, f"Пароль должен быть не короче {_MIN_PASSWORD_LENGTH} символов"
    if password.lower() == username.lower():
        return None, None, "Пароль не должен совпадать с именем пользователя"
    return username, email, password


def _login_user(user) -> None:
    flask_session.pop("telegram_user_id", None)
    flask_session.pop("auth_type", None)
    flask_session["user_id"] = user.id
    flask_session["role"] = user.role
    flask_session.permanent = True


def _login_rate_key(identifier: str) -> str:
    ip = (request.remote_addr or "unknown").strip() or "unknown"
    return f"{ip}:{identifier.strip().lower()}"


@auth_bp.route("/me", methods=["GET"])
def me():
    """Текущий пользователь или гостевой режим."""
    return jsonify(_user_payload(get_current_user()))


@auth_bp.route("/register", methods=["POST"])
def register():
    """Зарегистрировать обычного пользователя и сразу выполнить вход."""
    data = _json_body()
    username, email, password_or_error = _validate_registration(data)
    if not username:
        return jsonify({"error": password_or_error}), 400

    history = get_chat_history()
    password_hash = generate_password_hash(password_or_error)
    try:
        user = history.create_user(username=username, email=email, password_hash=password_hash, role="user")
    except sqlite3.IntegrityError:
        return jsonify({"error": "Пользователь с таким email или именем уже существует"}), 409

    _login_user(user)
    return jsonify(_user_payload(user)), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    """Войти по email/username и паролю."""
    data = _json_body()
    identifier = (data.get("identifier") or data.get("email") or data.get("username") or "").strip()
    password = data.get("password") or ""
    if not identifier or not password:
        return jsonify({"error": "Укажите логин и пароль"}), 400

    rate_key = _login_rate_key(identifier)
    if _login_limiter.is_blocked(rate_key):
        return jsonify({"error": "Слишком много попыток входа. Попробуйте позже."}), 429

    user = get_chat_history().get_user_by_identifier(identifier)
    if not user or not user.is_active or not check_password_hash(user.password_hash, password):
        _login_limiter.register_failure(rate_key)
        return jsonify({"error": "Неверный логин или пароль"}), 401

    _login_user(user)
    return jsonify(_user_payload(user))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Выйти из пользовательского аккаунта, оставив гостевой режим доступным."""
    flask_session.pop("user_id", None)
    flask_session.pop("role", None)
    flask_session.pop("telegram_user_id", None)
    flask_session.pop("auth_type", None)
    ensure_guest_id()
    return jsonify(_user_payload(None))
