#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Общая валидация данных пользователя (регистрация и админ-управление).

Вынесено из api/routes/auth.py, чтобы админка переиспользовала те же правила.
"""

from __future__ import annotations

import re

USERNAME_RE = re.compile(r"^[A-Za-zА-Яа-я0-9_.-]{3,50}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MIN_PASSWORD_LENGTH = 8
MAX_EMAIL_LENGTH = 255

USERNAME_ERROR = "Имя пользователя: 3-50 символов, буквы, цифры, точка, дефис или подчёркивание"
EMAIL_ERROR = "Укажите корректный email"

VALID_ROLES = ("user", "admin")


def normalize_username(username: str) -> str:
    return (username or "").strip()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_username(username: str) -> str | None:
    """Вернуть текст ошибки по логину или None, если он корректен."""
    if not USERNAME_RE.match(normalize_username(username)):
        return USERNAME_ERROR
    return None


def validate_email(email: str) -> str | None:
    """Вернуть текст ошибки по email или None, если он корректен."""
    value = normalize_email(email)
    if not EMAIL_RE.match(value) or len(value) > MAX_EMAIL_LENGTH:
        return EMAIL_ERROR
    return None


def validate_password(password: str, username: str = "") -> str | None:
    """Вернуть текст ошибки по паролю или None, если он корректен."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
    if username and (password or "").lower() == normalize_username(username).lower():
        return "Пароль не должен совпадать с именем пользователя"
    return None


def validate_registration_payload(data: dict) -> tuple[str, str, str] | tuple[None, None, str]:
    """Проверить username/email/password.

    Возвращает ``(username, email, password)`` либо ``(None, None, error)``.
    """
    username = normalize_username(data.get("username"))
    email = normalize_email(data.get("email"))
    password = data.get("password") or ""

    error = validate_username(username) or validate_email(email) or validate_password(password, username)
    if error:
        return None, None, error
    return username, email, password
