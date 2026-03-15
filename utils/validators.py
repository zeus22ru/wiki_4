#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Валидаторы входных данных для приложения

Файл очищен в ходе рефакторинга - удалены неиспользуемые функции.
Оставлены только используемые Pydantic модели и базовые валидаторы.
"""

import re
from typing import Optional
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


# ============================================
# Функции валидации
# ============================================

def sanitize_text(text: str) -> str:
    """
    Очистка текста от HTML тегов и опасного контента
    
    Args:
        text: Исходный текст
        
    Returns:
        Очищенный текст
    """
    import bleach
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
