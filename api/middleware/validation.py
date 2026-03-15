#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Middleware для валидации запросов API

Файл очищен в ходе рефакторинга - удалены неиспользуемые middleware.
Оставлены только базовые декораторы валидации.
"""

from functools import wraps
from flask import request, jsonify
from typing import Callable, Any
import json

from utils.validators import (
    ChatMessage, ChatRequest,
    ValidationError, MessageTooLongError, MessageTooShortError,
    InvalidCharactersError
)
from config import get_logger

logger = get_logger(__name__)


# ============================================
# Декораторы валидации
# ============================================

def validate_json(f: Callable) -> Callable:
    """
    Декоратор для проверки Content-Type и парсинга JSON
    
    Args:
        f: Функция-обработчик
        
    Returns:
        Обёрнутая функция
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Проверяем Content-Type
        if not request.is_json:
            logger.warning(f"Неверный Content-Type: {request.content_type}")
            return jsonify({
                'error': 'Content-Type должен быть application/json',
                'status': 'error'
            }), 400
        
        # Проверяем наличие тела запроса
        if not request.data:
            logger.warning("Пустое тело запроса")
            return jsonify({
                'error': 'Тело запроса не может быть пустым',
                'status': 'error'
            }), 400
        
        try:
            # Парсим JSON
            request.json_data = request.get_json()
            return f(*args, **kwargs)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return jsonify({
                'error': 'Неверный формат JSON',
                'status': 'error'
            }), 400
    
    return decorated_function


def validate_chat_message(f: Callable) -> Callable:
    """
    Декоратор для валидации сообщения чата
    
    Args:
        f: Функция-обработчик
        
    Returns:
        Обёрнутая функция
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Проверяем наличие сообщения
            if 'message' not in request.json_data:
                logger.warning("Отсутствует поле 'message' в запросе")
                return jsonify({
                    'error': 'Поле "message" обязательно',
                    'status': 'error'
                }), 400
            
            message = request.json_data['message']
            
            # Проверяем длину сообщения
            if len(message) < 1:
                logger.warning("Сообщение слишком короткое")
                return jsonify({
                    'error': 'Сообщение не может быть пустым',
                    'status': 'error'
                }), 400
            
            if len(message) > 5000:
                logger.warning(f"Сообщение слишком длинное: {len(message)} символов")
                return jsonify({
                    'error': 'Сообщение не может превышать 5000 символов',
                    'status': 'error'
                }), 400
            
            # Валидируем через Pydantic
            chat_message = ChatMessage(
                message=message,
                chat_id=request.json_data.get('chat_id')
            )
            
            # Сохраняем валидированные данные
            request.validated_data = chat_message.dict()
            
            logger.info(f"Сообщение валидировано успешно: {len(message)} символов")
            return f(*args, **kwargs)
            
        except ValidationError as e:
            logger.error(f"Ошибка валидации сообщения: {e}")
            return jsonify({
                'error': str(e),
                'status': 'error'
            }), 400
        except Exception as e:
            logger.error(f"Неожиданная ошибка при валидации: {e}")
            return jsonify({
                'error': 'Ошибка валидации',
                'status': 'error'
            }), 500
    
    return decorated_function


def validate_chat_request(f: Callable) -> Callable:
    """
    Декоратор для валидации полного запроса чата
    
    Args:
        f: Функция-обработчик
        
    Returns:
        Обёрнутая функция
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Валидируем через Pydantic
            chat_request = ChatRequest(
                message=request.json_data.get('message', ''),
                chat_id=request.json_data.get('chat_id'),
                top_k=request.json_data.get('top_k', 3)
            )
            
            # Сохраняем валидированные данные
            request.validated_data = chat_request.dict()
            
            logger.info(f"Запрос чата валидирован: top_k={chat_request.top_k}")
            return f(*args, **kwargs)
            
        except ValidationError as e:
            logger.error(f"Ошибка валидации запроса чата: {e}")
            return jsonify({
                'error': str(e),
                'status': 'error'
            }), 400
        except Exception as e:
            logger.error(f"Неожиданная ошибка при валидации: {e}")
            return jsonify({
                'error': 'Ошибка валидации',
                'status': 'error'
            }), 500
    
    return decorated_function
