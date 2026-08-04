#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API для привязки Telegram-аккаунтов к пользователям системы."""

from flask import Blueprint, jsonify, request

from api.middleware.auth import current_user_id
from config import get_logger, settings
from core.chat_history import get_chat_history

logger = get_logger(__name__)

telegram_bp = Blueprint("telegram", __name__, url_prefix="/api/telegram")


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@telegram_bp.route("/link", methods=["POST"])
def create_link():
    """Создать код привязки Telegram для текущего пользователя."""
    if not settings.TELEGRAM_ENABLED:
        return jsonify({"error": "Интеграция с Telegram отключена"}), 400

    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Требуется авторизация"}), 401

    chat_history = get_chat_history()
    result = chat_history.create_telegram_link(user_id)
    logger.info(f"Создан код привязки Telegram для пользователя {user_id}")
    return jsonify(result)


@telegram_bp.route("/verify", methods=["POST"])
def verify_link():
    """Верифицировать код привязки (внутренний endpoint для воркера)."""
    if not settings.TELEGRAM_ENABLED:
        return jsonify({"error": "Интеграция с Telegram отключена"}), 400

    data = _json_body()
    code = (data.get("code") or "").strip()
    telegram_user_id = data.get("telegram_user_id")
    telegram_username = (data.get("telegram_username") or "").strip() or None

    if not code:
        return jsonify({"error": "Не указан код привязки"}), 400
    if not isinstance(telegram_user_id, int):
        return jsonify({"error": "Некорректный telegram_user_id"}), 400

    chat_history = get_chat_history()
    result = chat_history.verify_telegram_link(code, telegram_user_id, telegram_username)
    if not result:
        return jsonify({"error": "Код не найден или истёк"}), 404

    logger.info(f"Верифицирован код Telegram привязки для user_id={result['user_id']}")
    return jsonify(result)


@telegram_bp.route("/resolve", methods=["POST"])
def resolve_link():
    """Найти активную привязку по telegram_user_id (для воркера после рестарта)."""
    if not settings.TELEGRAM_ENABLED:
        return jsonify({"error": "Интеграция с Telegram отключена"}), 400

    data = _json_body()
    telegram_user_id = data.get("telegram_user_id")
    if not isinstance(telegram_user_id, int):
        return jsonify({"error": "Некорректный telegram_user_id"}), 400

    chat_history = get_chat_history()
    link = chat_history.get_telegram_link(telegram_user_id)
    if not link:
        return jsonify({"error": "Привязка не найдена"}), 404

    return jsonify({"user_id": link["user_id"], "role": link["role"]})


@telegram_bp.route("/status", methods=["GET"])
def status():
    """Публичный статус интеграции с Telegram."""
    return jsonify({
        "enabled": settings.TELEGRAM_ENABLED,
        "bot_username": None,
    })
