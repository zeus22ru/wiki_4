#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API загрузки и выдачи вложений к вопросам чата."""

from flask import Blueprint, jsonify, request, send_file

from config import get_logger
from core.chat_attachments import (
    ChatAttachmentError,
    attachments_enabled,
    load_attachment,
    save_uploaded_file,
)

logger = get_logger(__name__)

chat_attachments_bp = Blueprint(
    "chat_attachments",
    __name__,
    url_prefix="/api/chat",
)


@chat_attachments_bp.route("/attachments", methods=["POST"])
def upload_chat_attachments():
    """Загрузить одно или несколько вложений перед отправкой вопроса."""
    if not attachments_enabled():
        return jsonify({"error": "Вложения к чату отключены"}), 403

    files = request.files.getlist("files") or request.files.getlist("files[]")
    if not files:
        single = request.files.get("file")
        if single:
            files = [single]
    if not files:
        return jsonify({"error": "Не выбраны файлы"}), 400

    saved = []
    try:
        for file in files:
            if not file or not file.filename:
                continue
            item = save_uploaded_file(file)
            saved.append(item.to_metadata_dict())
    except ChatAttachmentError as e:
        logger.warning("Ошибка загрузки вложения: %s", e)
        return jsonify({"error": str(e)}), 400

    if not saved:
        return jsonify({"error": "Не удалось сохранить файлы"}), 400

    logger.info("Загружено вложений чата: %s", len(saved))
    return jsonify({"attachments": saved}), 201


@chat_attachments_bp.route("/attachments/<attachment_id>", methods=["GET"])
def get_chat_attachment(attachment_id: str):
    """Отдать файл вложения (для превью в истории чата)."""
    item = load_attachment(attachment_id)
    if not item or not item.path.is_file():
        return jsonify({"error": "Вложение не найдено"}), 404
    return send_file(
        item.path,
        mimetype=item.mime,
        as_attachment=False,
        download_name=item.filename,
    )
