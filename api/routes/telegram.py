#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API для привязки Telegram-аккаунтов к пользователям системы."""

from flask import Blueprint, jsonify, request, session as flask_session

from api.middleware.auth import current_user_id
from api.middleware.telegram_webapp import validate_telegram_init_data
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
        "webapp_enabled": settings.TELEGRAM_WEBAPP_ENABLED,
        "bot_username": settings.TELEGRAM_BOT_USERNAME or None,
    })


@telegram_bp.route("/webapp/auth", methods=["POST"])
def webapp_auth():
    """Проверить Telegram initData и открыть обычную пользовательскую web-сессию."""
    if not settings.TELEGRAM_WEBAPP_ENABLED:
        return jsonify({"error": "Telegram Mini App отключено", "code": "webapp_disabled"}), 503
    if not settings.TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "Telegram Mini App не настроено", "code": "webapp_unconfigured"}), 503

    data = _json_body()
    try:
        identity = validate_telegram_init_data(
            data.get("init_data"),
            settings.TELEGRAM_BOT_TOKEN,
            max_age_seconds=settings.TELEGRAM_WEBAPP_MAX_AGE_SECONDS,
        )
    except ValueError as exc:
        logger.warning("Отклонена авторизация Telegram Mini App: %s", exc)
        return jsonify({"error": "Не удалось подтвердить вход через Telegram", "code": "invalid_init_data"}), 401

    history = get_chat_history()
    link = history.get_telegram_link(identity.user_id)
    if not link:
        return jsonify({
            "error": "Сначала привяжите Telegram к аккаунту БочкарИИ",
            "code": "telegram_not_linked",
            "bot_username": settings.TELEGRAM_BOT_USERNAME or None,
        }), 403

    user = history.get_user(link["user_id"])
    if not user or not user.is_active:
        return jsonify({"error": "Аккаунт недоступен", "code": "account_unavailable"}), 403

    flask_session.clear()
    flask_session["user_id"] = user.id
    flask_session["role"] = user.role
    flask_session["telegram_user_id"] = identity.user_id
    flask_session["auth_type"] = "telegram_webapp"
    flask_session.permanent = True

    logger.info("Вход через Telegram Mini App для user_id=%s", user.id)
    return jsonify({
        "authenticated": True,
        "auth_type": "telegram_webapp",
        "telegram_user": identity.to_dict(),
        "user": user.to_dict(),
    })
