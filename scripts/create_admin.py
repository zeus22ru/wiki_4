#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Создать или повысить пользователя до роли admin."""

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from werkzeug.security import generate_password_hash

from core.chat_history import get_chat_history  # noqa: E402


def _prompt(value: str | None, label: str, secret: bool = False) -> str:
    if value:
        return value.strip()
    return (getpass.getpass(label) if secret else input(label)).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Создать администратора приложения.")
    parser.add_argument("--username", help="Имя пользователя")
    parser.add_argument("--email", help="Email")
    parser.add_argument("--password", help="Пароль. Если не указан, будет запрошен скрытым вводом")
    args = parser.parse_args()

    username = _prompt(args.username, "Username: ")
    email = _prompt(args.email, "Email: ").lower()
    password = _prompt(args.password, "Password: ", secret=True)

    if not username or not email or not password:
        print("Username, email и password обязательны.")
        return 1
    history = get_chat_history()
    existing = history.get_user_by_identifier(email) or history.get_user_by_identifier(username)
    if existing:
        history.update_user_role(existing.id, "admin")
        print(f"Пользователь {existing.username} повышен до admin.")
        return 0

    try:
        history.create_user(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role="admin",
        )
    except sqlite3.IntegrityError:
        print("Пользователь с таким email или username уже существует.")
        return 1

    print(f"Администратор {username} создан.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

