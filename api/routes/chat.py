#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API маршруты для работы с историей чатов
"""

from flask import Blueprint, request, jsonify
from typing import Optional

from config import get_logger
from core.chat_history import get_chat_history
from models import ChatSession, Message

logger = get_logger(__name__)

# Создаем Blueprint для маршрутов чатов
chat_bp = Blueprint('chat', __name__, url_prefix='/api/chats')


@chat_bp.route('', methods=['GET'])
def get_chats():
    """Получить список всех чатов"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        user_id = request.args.get('user_id', type=int)
        
        chat_history = get_chat_history()
        sessions = chat_history.get_sessions(user_id=user_id, limit=limit, offset=offset)
        
        logger.info(f"Получен список чатов: {len(sessions)} сессий")
        
        return jsonify({
            'chats': [session.to_dict() for session in sessions],
            'total': chat_history.get_session_count(user_id=user_id)
        })
    except Exception as e:
        logger.error(f"Ошибка при получении списка чатов: {e}")
        return jsonify({'error': 'Ошибка при получении списка чатов'}), 500


@chat_bp.route('/<int:chat_id>', methods=['GET'])
def get_chat(chat_id: int):
    """Получить детали чата по ID"""
    try:
        chat_history = get_chat_history()
        session = chat_history.get_session(chat_id)
        
        if not session:
            logger.warning(f"Чат {chat_id} не найден")
            return jsonify({'error': 'Чат не найден'}), 404
        
        messages = chat_history.get_messages(chat_id)
        
        logger.info(f"Получен чат {chat_id}: {len(messages)} сообщений")
        
        return jsonify({
            'chat': session.to_dict(),
            'messages': [msg.to_dict() for msg in messages]
        })
    except Exception as e:
        logger.error(f"Ошибка при получении чата {chat_id}: {e}")
        return jsonify({'error': 'Ошибка при получении чата'}), 500


@chat_bp.route('', methods=['POST'])
def create_chat():
    """Создать новый чат"""
    try:
        data = request.get_json()
        
        title = data.get('title', 'Новый чат')
        user_id = data.get('user_id')
        
        chat_history = get_chat_history()
        session = chat_history.create_session(user_id=user_id, title=title)
        
        logger.info(f"Создан новый чат: {session.id}")
        
        return jsonify(session.to_dict()), 201
    except Exception as e:
        logger.error(f"Ошибка при создании чата: {e}")
        return jsonify({'error': 'Ошибка при создании чата'}), 500


@chat_bp.route('/<int:chat_id>', methods=['PUT'])
def update_chat(chat_id: int):
    """Обновить чат"""
    try:
        data = request.get_json()
        title = data.get('title')
        
        if not title:
            return jsonify({'error': 'Не указан заголовок чата'}), 400
        
        chat_history = get_chat_history()
        updated = chat_history.update_session(chat_id, title=title)
        
        if not updated:
            logger.warning(f"Чат {chat_id} не найден для обновления")
            return jsonify({'error': 'Чат не найден'}), 404
        
        logger.info(f"Обновлён чат {chat_id}")
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Ошибка при обновлении чата {chat_id}: {e}")
        return jsonify({'error': 'Ошибка при обновлении чата'}), 500


@chat_bp.route('/<int:chat_id>', methods=['DELETE'])
def delete_chat(chat_id: int):
    """Удалить чат"""
    try:
        chat_history = get_chat_history()
        deleted = chat_history.delete_session(chat_id)
        
        if not deleted:
            logger.warning(f"Чат {chat_id} не найден для удаления")
            return jsonify({'error': 'Чат не найден'}), 404
        
        logger.info(f"Удалён чат {chat_id}")
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Ошибка при удалении чата {chat_id}: {e}")
        return jsonify({'error': 'Ошибка при удалении чата'}), 500


@chat_bp.route('/<int:chat_id>/messages', methods=['POST'])
def add_message(chat_id: int):
    """Добавить сообщение в чат"""
    try:
        data = request.get_json()
        
        role = data.get('role', 'user')
        content = data.get('content', '')
        sources = data.get('sources', [])
        
        if not content:
            return jsonify({'error': 'Не указано содержание сообщения'}), 400
        
        if role not in ['user', 'assistant']:
            return jsonify({'error': 'Неверная роль сообщения'}), 400
        
        chat_history = get_chat_history()
        
        # Проверяем существование чата
        session = chat_history.get_session(chat_id)
        if not session:
            logger.warning(f"Чат {chat_id} не найден")
            return jsonify({'error': 'Чат не найден'}), 404
        
        message = chat_history.add_message(
            session_id=chat_id,
            role=role,
            content=content,
            sources=sources
        )
        
        logger.info(f"Добавлено сообщение в чат {chat_id}")
        
        return jsonify(message.to_dict()), 201
    except Exception as e:
        logger.error(f"Ошибка при добавлении сообщения в чат {chat_id}: {e}")
        return jsonify({'error': 'Ошибка при добавлении сообщения'}), 500


@chat_bp.route('/<int:chat_id>/messages', methods=['GET'])
def get_messages(chat_id: int):
    """Получить все сообщения чата"""
    try:
        chat_history = get_chat_history()
        
        # Проверяем существование чата
        session = chat_history.get_session(chat_id)
        if not session:
            logger.warning(f"Чат {chat_id} не найден")
            return jsonify({'error': 'Чат не найден'}), 404
        
        messages = chat_history.get_messages(chat_id)
        
        logger.info(f"Получены сообщения чата {chat_id}: {len(messages)} сообщений")
        
        return jsonify({
            'messages': [msg.to_dict() for msg in messages]
        })
    except Exception as e:
        logger.error(f"Ошибка при получении сообщений чата {chat_id}: {e}")
        return jsonify({'error': 'Ошибка при получении сообщений'}), 500
