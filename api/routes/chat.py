#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API маршруты для работы с историей чатов
"""

from flask import Blueprint, request, jsonify
from typing import Optional

from config import get_logger
from core.chat_history import get_chat_history
from api.middleware.auth import (
    admin_required,
    can_access_chat,
    clear_guest_chats,
    current_user_id,
    forget_guest_chat,
    get_current_user,
    get_guest_chat_ids,
    remember_guest_chat,
)

logger = get_logger(__name__)

# Создаем Blueprint для маршрутов чатов
chat_bp = Blueprint('chat', __name__, url_prefix='/api/chats')


@chat_bp.route('', methods=['GET'])
def get_chats():
    """Получить список всех чатов"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        search = (request.args.get('q') or '').strip()
        
        chat_history = get_chat_history()
        user = get_current_user()
        if user:
            if search:
                sessions = chat_history.search_sessions(search, limit=limit, user_id=user.id)
            else:
                sessions = chat_history.get_sessions(user_id=user.id, limit=limit, offset=offset)
            total = chat_history.get_session_count(user_id=user.id)
        else:
            guest_ids = get_guest_chat_ids()
            sessions = [
                session for session in (chat_history.get_session(chat_id) for chat_id in guest_ids)
                if session and session.user_id is None
            ]
            if search:
                lowered = search.lower()
                sessions = [session for session in sessions if lowered in (session.title or '').lower()]
            sessions.sort(key=lambda item: item.updated_at, reverse=True)
            total = len(sessions)
            sessions = sessions[offset:offset + limit]
        
        logger.info(f"Получен список чатов: {len(sessions)} сессий")
        
        return jsonify({
            'chats': [session.to_dict() for session in sessions],
            'total': total
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
        if not can_access_chat(session):
            return jsonify({'error': 'Нет доступа к чату'}), 403
        
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
        data = request.get_json(silent=True) or {}
        
        title = data.get('title', 'Новый чат')
        chat_history = get_chat_history()
        session = chat_history.create_session(user_id=current_user_id(), title=title)
        if session.user_id is None:
            remember_guest_chat(session.id)
        
        logger.info(f"Создан новый чат: {session.id}")
        
        return jsonify(session.to_dict()), 201
    except Exception as e:
        logger.error(f"Ошибка при создании чата: {e}")
        return jsonify({'error': 'Ошибка при создании чата'}), 500


@chat_bp.route('', methods=['DELETE'])
def delete_all_chats():
    """Удалить все чаты"""
    try:
        chat_history = get_chat_history()
        user = get_current_user()
        if user:
            deleted_count = chat_history.delete_all_sessions(user_id=user.id)
        else:
            deleted_count = 0
            for chat_id in get_guest_chat_ids():
                chat = chat_history.get_session(chat_id)
                if chat and can_access_chat(chat) and chat_history.delete_session(chat_id):
                    deleted_count += 1
            clear_guest_chats()

        logger.info(f"Очищена история чатов: {deleted_count} сессий")

        return jsonify({'success': True, 'deleted': deleted_count})
    except Exception as e:
        logger.error(f"Ошибка при очистке истории чатов: {e}")
        return jsonify({'error': 'Ошибка при очистке истории чатов'}), 500


@chat_bp.route('/<int:chat_id>', methods=['PUT'])
def update_chat(chat_id: int):
    """Обновить чат"""
    try:
        data = request.get_json(silent=True) or {}
        title = data.get('title')
        
        if not title:
            return jsonify({'error': 'Не указан заголовок чата'}), 400
        
        chat_history = get_chat_history()
        session = chat_history.get_session(chat_id)
        if not session:
            logger.warning(f"Чат {chat_id} не найден для обновления")
            return jsonify({'error': 'Чат не найден'}), 404
        if not can_access_chat(session):
            return jsonify({'error': 'Нет доступа к чату'}), 403
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
        session = chat_history.get_session(chat_id)
        if not session:
            logger.warning(f"Чат {chat_id} не найден для удаления")
            return jsonify({'error': 'Чат не найден'}), 404
        if not can_access_chat(session):
            return jsonify({'error': 'Нет доступа к чату'}), 403
        deleted = chat_history.delete_session(chat_id)
        forget_guest_chat(chat_id)
        
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
        data = request.get_json(silent=True) or {}
        
        role = data.get('role', 'user')
        content = data.get('content', '')
        sources = data.get('sources', [])
        citations = data.get('citations', [])
        metadata = data.get('metadata', {})
        
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
        if not can_access_chat(session):
            return jsonify({'error': 'Нет доступа к чату'}), 403
        
        message = chat_history.add_message(
            session_id=chat_id,
            role=role,
            content=content,
            sources=sources,
            citations=citations,
            metadata=metadata
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
        if not can_access_chat(session):
            return jsonify({'error': 'Нет доступа к чату'}), 403
        
        messages = chat_history.get_messages(chat_id)
        
        logger.info(f"Получены сообщения чата {chat_id}: {len(messages)} сообщений")
        
        return jsonify({
            'messages': [msg.to_dict() for msg in messages]
        })
    except Exception as e:
        logger.error(f"Ошибка при получении сообщений чата {chat_id}: {e}")
        return jsonify({'error': 'Ошибка при получении сообщений'}), 500


@chat_bp.route('/feedback', methods=['GET'])
@admin_required
def get_feedback():
    """Получить последние оценки ответов"""
    try:
        limit = request.args.get('limit', 50, type=int)
        chat_history = get_chat_history()
        return jsonify({'feedback': chat_history.get_feedback(limit=limit)})
    except Exception as e:
        logger.error(f"Ошибка при получении feedback: {e}")
        return jsonify({'error': 'Ошибка при получении оценок'}), 500


@chat_bp.route('/feedback', methods=['POST'])
def add_feedback():
    """Сохранить оценку ответа"""
    try:
        data = request.get_json(silent=True) or {}
        rating = data.get('rating')
        if rating not in ['up', 'down']:
            return jsonify({'error': 'rating должен быть up или down'}), 400

        chat_history = get_chat_history()
        session_id = data.get('session_id')
        if session_id is not None:
            session = chat_history.get_session(session_id)
            if not can_access_chat(session):
                return jsonify({'error': 'Нет доступа к чату'}), 403
        feedback = chat_history.add_feedback(
            session_id=session_id,
            message_id=data.get('message_id'),
            rating=rating,
            comment=data.get('comment'),
        )
        return jsonify(feedback), 201
    except Exception as e:
        logger.error(f"Ошибка при сохранении feedback: {e}")
        return jsonify({'error': 'Ошибка при сохранении оценки'}), 500
