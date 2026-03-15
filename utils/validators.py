#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Валидаторы входных данных для приложения
"""

import re
import bleach
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator, constr


# ============================================
# Константы валидации
# ============================================

# Максимальная длина сообщения чата
MAX_MESSAGE_LENGTH = 5000

# Минимальная длина сообщения
MIN_MESSAGE_LENGTH = 1

# Запрещённые символы в сообщениях
FORBIDDEN_CHARS = r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]'

# Разрешённые HTML теги для очистки
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 's',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'code', 'pre',
    'blockquote', 'hr',
    'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td'
]

# Разрешённые атрибуты HTML тегов
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'code': ['class'],
    'pre': ['class'],
    'th': ['colspan', 'rowspan'],
    'td': ['colspan', 'rowspan']
}

# Разрешённые протоколы для ссылок
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


# ============================================
# Pydantic модели для валидации
# ============================================

class ChatMessage(BaseModel):
    """Модель сообщения чата"""
    message: constr(min_length=MIN_MESSAGE_LENGTH, max_length=MAX_MESSAGE_LENGTH)
    chat_id: Optional[str] = None
    
    @validator('message')
    def validate_message(cls, v):
        """Валидация сообщения на запрещённые символы"""
        if re.search(FORBIDDEN_CHARS, v):
            raise ValueError('Сообщение содержит недопустимые символы')
        return v.strip()


class ChatRequest(BaseModel):
    """Модель запроса к чату"""
    message: constr(min_length=MIN_MESSAGE_LENGTH, max_length=MAX_MESSAGE_LENGTH)
    chat_id: Optional[str] = None
    top_k: Optional[int] = Field(default=3, ge=1, le=10)


class DocumentUpload(BaseModel):
    """Модель для загрузки документа"""
    filename: str
    content_type: str
    
    @validator('filename')
    def validate_filename(cls, v):
        """Валидация имени файла"""
        # Проверка на пустое имя
        if not v or not v.strip():
            raise ValueError('Имя файла не может быть пустым')
        
        # Проверка на недопустимые символы
        if re.search(r'[<>:"|?*\x00-\x1f]', v):
            raise ValueError('Имя файла содержит недопустимые символы')
        
        # Проверка расширения
        allowed_extensions = ['html', 'htm', 'txt', 'docx', 'doc', 'pdf', 'xlsx', 'xls', 'pptx']
        ext = v.rsplit('.', 1)[-1].lower() if '.' in v else ''
        if ext not in allowed_extensions:
            raise ValueError(f'Недопустимый формат файла. Разрешены: {", ".join(allowed_extensions)}')
        
        return v


class SearchRequest(BaseModel):
    """Модель запроса поиска"""
    query: constr(min_length=MIN_MESSAGE_LENGTH, max_length=MAX_MESSAGE_LENGTH)
    top_k: Optional[int] = Field(default=3, ge=1, le=10)


class HealthCheckResponse(BaseModel):
    """Модель ответа проверки здоровья"""
    status: str
    ollama: bool
    database: bool
    timestamp: str


# ============================================
# Функции валидации
# ============================================

def sanitize_html(html: str) -> str:
    """
    Очистка HTML от опасного контента
    
    Args:
        html: Исходный HTML
        
    Returns:
        Очищенный HTML
    """
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True
    )


def sanitize_text(text: str) -> str:
    """
    Очистка текста от HTML тегов и опасного контента
    
    Args:
        text: Исходный текст
        
    Returns:
        Очищенный текст
    """
    # Сначала удаляем все HTML теги
    clean_text = bleach.clean(text, tags=[], strip=True)
    # Удаляем лишние пробелы
    clean_text = ' '.join(clean_text.split())
    return clean_text


def validate_message_length(message: str, max_length: int = MAX_MESSAGE_LENGTH) -> bool:
    """
    Проверка длины сообщения
    
    Args:
        message: Сообщение для проверки
        max_length: Максимальная длина
        
    Returns:
        True если длина валидна
    """
    return MIN_MESSAGE_LENGTH <= len(message) <= max_length


def validate_url(url: str) -> bool:
    """
    Валидация URL
    
    Args:
        url: URL для проверки
        
    Returns:
        True если URL валиден
    """
    url_pattern = re.compile(
        r'^https?://'  # http:// или https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # домен
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP адрес
        r'(?::\d+)?'  # порт
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return url_pattern.match(url) is not None


def validate_email(email: str) -> bool:
    """
    Валидация email
    
    Args:
        email: Email для проверки
        
    Returns:
        True если email валиден
    """
    email_pattern = re.compile(
        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    )
    return email_pattern.match(email) is not None


def validate_chat_id(chat_id: Optional[str]) -> bool:
    """
    Валидация ID чата
    
    Args:
        chat_id: ID чата для проверки
        
    Returns:
        True если ID валиден или None
    """
    if chat_id is None:
        return True
    
    # Проверка формата UUID
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    return uuid_pattern.match(chat_id) is not None


def validate_top_k(top_k: int) -> bool:
    """
    Валидация параметра top_k
    
    Args:
        top_k: Количество результатов для поиска
        
    Returns:
        True если значение валидно
    """
    return 1 <= top_k <= 10


def validate_file_size(size: int, max_size: int = 10 * 1024 * 1024) -> bool:
    """
    Валидация размера файла
    
    Args:
        size: Размер файла в байтах
        max_size: Максимальный размер в байтах (по умолчанию 10MB)
        
    Returns:
        True если размер валиден
    """
    return 0 < size <= max_size


def validate_content_type(content_type: str, allowed_types: Optional[List[str]] = None) -> bool:
    """
    Валидация типа содержимого файла
    
    Args:
        content_type: MIME тип файла
        allowed_types: Список разрешённых типов
        
    Returns:
        True если тип валиден
    """
    if allowed_types is None:
        allowed_types = [
            'text/html',
            'text/plain',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword',
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        ]
    
    return content_type in allowed_types


# ============================================
# Классы ошибок валидации
# ============================================

class ValidationError(Exception):
    """Базовый класс ошибок валидации"""
    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(self.message)


class MessageTooLongError(ValidationError):
    """Ошибка: сообщение слишком длинное"""
    pass


class MessageTooShortError(ValidationError):
    """Ошибка: сообщение слишком короткое"""
    pass


class InvalidCharactersError(ValidationError):
    """Ошибка: недопустимые символы"""
    pass


class InvalidURLError(ValidationError):
    """Ошибка: недопустимый URL"""
    pass


class InvalidEmailError(ValidationError):
    """Ошибка: недопустимый email"""
    pass


class InvalidFileError(ValidationError):
    """Ошибка: недопустимый файл"""
    pass


class FileTooLargeError(ValidationError):
    """Ошибка: файл слишком большой"""
    pass
