#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регистрация, вход и текущий пользователь."""

import re
import sqlite3

from flask import Blueprint, jsonify, request, session as flask_session
from werkzeug.security import check_password_hash, generate_password_hash

from api.middleware.auth import ensure_guest_id, get_current_user
from core.chat_history import get_chat_history

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

_USERNAME_RE = re.compile(r"^[A-Za-zА-Яа-я0-9_.-]{3,50}$")


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
    if "@" not in email or len(email) > 255:
        return None, None, "Укажите корректный email"
    if not password:
        return None, None, "Пароль не должен быть пустым"
    return username, email, password


def _login_user(user) -> None:
    flask_session["user_id"] = user.id
    flask_session["role"] = user.role
    flask_session.permanent = True


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

    user = get_chat_history().get_user_by_identifier(identifier)
    if not user or not user.is_active or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Неверный логин или пароль"}), 401

    _login_user(user)
    return jsonify(_user_payload(user))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Выйти из пользовательского аккаунта, оставив гостевой режим доступным."""
    flask_session.pop("user_id", None)
    flask_session.pop("role", None)
    ensure_guest_id()
    return jsonify(_user_payload(None))

