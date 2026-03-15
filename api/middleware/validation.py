#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Middleware для валидации запросов API
"""

from functools import wraps
from flask import request, jsonify
from typing import Callable, Any, Optional
import json

from utils.validators import (
    ChatMessage, ChatRequest, SearchRequest,
    ValidationError, MessageTooLongError, MessageTooShortError,
    InvalidCharactersError, InvalidURLError
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


def validate_search_request(f: Callable) -> Callable:
    """
    Декоратор для валидации запроса поиска
    
    Args:
        f: Функция-обработчик
        
    Returns:
        Обёрнутая функция
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Валидируем через Pydantic
            search_request = SearchRequest(
                query=request.json_data.get('query', ''),
                top_k=request.json_data.get('top_k', 3)
            )
            
            # Сохраняем валидированные данные
            request.validated_data = search_request.dict()
            
            logger.info(f"Запрос поиска валидирован: top_k={search_request.top_k}")
            return f(*args, **kwargs)
            
        except ValidationError as e:
            logger.error(f"Ошибка валидации запроса поиска: {e}")
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


def validate_file_upload(f: Callable) -> Callable:
    """
    Декоратор для валидации загрузки файла
    
    Args:
        f: Функция-обработчик
        
    Returns:
        Обёрнутая функция
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Проверяем наличие файла
            if 'file' not in request.files:
                logger.warning("Файл не найден в запросе")
                return jsonify({
                    'error': 'Файл не найден',
                    'status': 'error'
                }), 400
            
            file = request.files['file']
            
            # Проверяем, выбран ли файл
            if file.filename == '':
                logger.warning("Имя файла пустое")
                return jsonify({
                    'error': 'Файл не выбран',
                    'status': 'error'
                }), 400
            
            # Валидируем имя файла
            from utils.validators import DocumentUpload
            doc_upload = DocumentUpload(
                filename=file.filename,
                content_type=file.content_type or 'application/octet-stream'
            )
            
            # Проверяем размер файла
            file.seek(0, 2)  # Переходим в конец файла
            file_size = file.tell()
            file.seek(0)  # Возвращаемся в начало
            
            from utils.validators import validate_file_size
            if not validate_file_size(file_size):
                logger.warning(f"Файл слишком большой: {file_size} байт")
                return jsonify({
                    'error': 'Файл превышает максимальный размер (10MB)',
                    'status': 'error'
                }), 400
            
            # Сохраняем валидированные данные
            request.validated_file = {
                'file': file,
                'filename': doc_upload.filename,
                'content_type': doc_upload.content_type,
                'size': file_size
            }
            
            logger.info(f"Файл валидирован: {doc_upload.filename} ({file_size} байт)")
            return f(*args, **kwargs)
            
        except ValidationError as e:
            logger.error(f"Ошибка валидации файла: {e}")
            return jsonify({
                'error': str(e),
                'status': 'error'
            }), 400
        except Exception as e:
            logger.error(f"Неожиданная ошибка при валидации файла: {e}")
            return jsonify({
                'error': 'Ошибка валидации файла',
                'status': 'error'
            }), 500
    
    return decorated_function


def sanitize_input(f: Callable) -> Callable:
    """
    Декоратор для очистки входных данных от опасного HTML
    
    Args:
        f: Функция-обработчик
        
    Returns:
        Обёрнутая функция
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Очищаем все строковые поля в JSON данных
            if hasattr(request, 'json_data') and request.json_data:
                from utils.validators import sanitize_text
                
                def sanitize_dict(data: Any) -> Any:
                    """Рекурсивная очистка словаря"""
                    if isinstance(data, dict):
                        return {k: sanitize_dict(v) for k, v in data.items()}
                    elif isinstance(data, list):
                        return [sanitize_dict(item) for item in data]
                    elif isinstance(data, str):
                        return sanitize_text(data)
                    return data
                
                request.sanitized_data = sanitize_dict(request.json_data)
                logger.debug("Входные данные очищены")
            
            return f(*args, **kwargs)
            
        except Exception as e:
            logger.error(f"Ошибка при очистке данных: {e}")
            # В случае ошибки продолжаем с оригинальными данными
            return f(*args, **kwargs)
    
    return decorated_function


def log_request(f: Callable) -> Callable:
    """
    Декоратор для логирования запросов
    
    Args:
        f: Функция-обработчик
        
    Returns:
        Обёрнутая функция
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Логируем информацию о запросе
        logger.info(f"Запрос: {request.method} {request.path}")
        logger.debug(f"IP: {request.remote_addr}")
        logger.debug(f"User-Agent: {request.user_agent}")
        
        # Логируем тело запроса (без паролей)
        if request.is_json and request.data:
            try:
                data = request.get_json()
                # Удаляем чувствительные данные
                safe_data = {k: v for k, v in data.items() 
                           if k not in ['password', 'token', 'secret']}
                logger.debug(f"Тело запроса: {safe_data}")
            except:
                pass
        
        # Выполняем функцию
        response = f(*args, **kwargs)
        
        # Логируем ответ
        if hasattr(response, 'status_code'):
            logger.info(f"Ответ: {response.status_code}")
        
        return response
    
    return decorated_function


# ============================================
# Функции-помощники
# ============================================

def create_error_response(message: str, status_code: int = 400, 
                          field: Optional[str] = None) -> tuple:
    """
    Создание стандартизированного ответа об ошибке
    
    Args:
        message: Сообщение об ошибке
        status_code: HTTP статус код
        field: Поле, вызвавшее ошибку (опционально)
        
    Returns:
        Кортеж (json_response, status_code)
    """
    response = {
        'error': message,
        'status': 'error'
    }
    
    if field:
        response['field'] = field
    
    return jsonify(response), status_code


def create_success_response(data: Any, message: Optional[str] = None) -> dict:
    """
    Создание стандартизированного успешного ответа
    
    Args:
        data: Данные для ответа
        message: Дополнительное сообщение (опционально)
        
    Returns:
        JSON ответ
    """
    response = {
        'status': 'success',
        'data': data
    }
    
    if message:
        response['message'] = message
    
    return jsonify(response)
