#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Форматировщики ответов и данных
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import json

from config import get_logger

logger = get_logger(__name__)


# ============================================
# Форматирование ответов RAG
# ============================================

def format_rag_response(
    answer: str,
    sources: List[Dict],
    citations: Optional[List[Dict]] = None,
    include_sources: bool = True,
    include_metadata: bool = False
) -> Dict[str, Any]:
    """
    Форматирование RAG ответа для API
    
    Args:
        answer: Сгенерированный ответ
        sources: Список источников
        citations: Список цитат (опционально)
        include_sources: Включать ли источники в ответ
        include_metadata: Включать ли метаданные
        
    Returns:
        Словарь с отформатированным ответом
    """
    response = {
        'answer': answer,
        'timestamp': datetime.now().isoformat(),
        'sources_count': len(sources)
    }
    
    if include_sources and sources:
        formatted_sources = []
        for source in sources:
            formatted_source = {
                'source': source.get('source', 'Неизвестный источник'),
                'score': source.get('score', 0.0),
                'chunk_id': source.get('chunk_id', '')
            }
            
            if include_metadata:
                formatted_source['metadata'] = source.get('metadata', {})
            
            formatted_sources.append(formatted_source)
        
        response['sources'] = formatted_sources
    
    if citations:
        response['citations'] = citations
    
    return response


def format_source_for_display(source: Dict) -> str:
    """
    Форматирование источника для отображения
    
    Args:
        source: Словарь с информацией об источнике
        
    Returns:
        Отформатированная строка
    """
    source_name = source.get('source', 'Неизвестный источник')
    score = source.get('score', 0.0)
    chunk_id = source.get('chunk_id', '')
    
    formatted = f"📄 {source_name}"
    
    if chunk_id:
        formatted += f" (ID: {chunk_id})"
    
    formatted += f"\n   Релевантность: {score:.1%}"
    
    return formatted


def format_sources_list(sources: List[Dict], max_sources: int = 5) -> str:
    """
    Форматирование списка источников
    
    Args:
        sources: Список источников
        max_sources: Максимальное количество источников для отображения
        
    Returns:
        Отформатированный список
    """
    if not sources:
        return "Источники не найдены"
    
    limited_sources = sources[:max_sources]
    formatted = "**Источники:**\n\n"
    
    for i, source in enumerate(limited_sources, 1):
        formatted += f"{i}. {format_source_for_display(source)}\n"
    
    if len(sources) > max_sources:
        formatted += f"\n... и ещё {len(sources) - max_sources} источников"
    
    return formatted


# ============================================
# Форматирование сообщений чата
# ============================================

def format_chat_message(
    role: str,
    content: str,
    timestamp: Optional[str] = None,
    sources: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Форматирование сообщения чата
    
    Args:
        role: Роль (user/assistant/system)
        content: Содержимое сообщения
        timestamp: Временная метка (опционально)
        sources: Источники (опционально)
        
    Returns:
        Словарь с отформатированным сообщением
    """
    message = {
        'role': role,
        'content': content,
        'timestamp': timestamp or datetime.now().isoformat()
    }
    
    if sources:
        message['sources'] = sources
    
    return message


def format_chat_history(messages: List[Dict]) -> List[Dict]:
    """
    Форматирование истории чата
    
    Args:
        messages: Список сообщений
        
    Returns:
        Отформатированная история
    """
    formatted = []
    
    for msg in messages:
        formatted_msg = {
            'role': msg.get('role', 'user'),
            'content': msg.get('content', ''),
            'timestamp': msg.get('timestamp', datetime.now().isoformat())
        }
        
        if 'sources' in msg:
            formatted_msg['sources'] = msg['sources']
        
        formatted.append(formatted_msg)
    
    return formatted


# ============================================
# Форматирование ошибок
# ============================================

def format_error_response(
    error: Exception,
    include_traceback: bool = False,
    user_friendly: bool = True
) -> Dict[str, Any]:
    """
    Форматирование ответа об ошибке
    
    Args:
        error: Исключение
        include_traceback: Включать ли traceback
        user_friendly: Создавать ли дружественное пользователю сообщение
        
    Returns:
        Словарь с информацией об ошибке
    """
    error_type = type(error).__name__
    error_message = str(error)
    
    response = {
        'error': True,
        'error_type': error_type,
        'message': error_message,
        'timestamp': datetime.now().isoformat()
    }
    
    if user_friendly:
        response['user_message'] = get_user_friendly_error(error)
    
    if include_traceback:
        import traceback
        response['traceback'] = traceback.format_exc()
    
    return response


def get_user_friendly_error(error: Exception) -> str:
    """
    Получение дружественного пользователю сообщения об ошибке
    
    Args:
        error: Исключение
        
    Returns:
        Дружественное сообщение
    """
    error_messages = {
        'ConnectionError': 'Не удалось подключиться к серверу. Проверьте подключение к интернету.',
        'TimeoutError': 'Превышено время ожидания ответа. Попробуйте позже.',
        'ValueError': 'Неверный формат данных.',
        'KeyError': 'Отсутствует необходимое поле в данных.',
        'ValidationError': 'Ошибка валидации входных данных.',
        'FileNotFoundError': 'Файл не найден.',
        'PermissionError': 'Недостаточно прав для выполнения операции.',
    }
    
    error_type = type(error).__name__
    return error_messages.get(error_type, f'Произошла ошибка: {str(error)}')


# ============================================
# Форматирование данных для отображения
# ============================================

def format_file_size(size_bytes: int) -> str:
    """
    Форматирование размера файла
    
    Args:
        size_bytes: Размер в байтах
        
    Returns:
        Отформатированная строка
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def format_duration(seconds: float) -> str:
    """
    Форматирование длительности
    
    Args:
        seconds: Длительность в секундах
        
    Returns:
        Отформатированная строка
    """
    if seconds < 1:
        return f"{seconds * 1000:.0f} мс"
    elif seconds < 60:
        return f"{seconds:.2f} сек"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.2f} мин"
    else:
        hours = seconds / 3600
        return f"{hours:.2f} ч"


def format_number(number: int, locale: str = 'ru') -> str:
    """
    Форматирование числа с разделителями
    
    Args:
        number: Число
        locale: Локаль
        
    Returns:
        Отформатированная строка
    """
    if locale == 'ru':
        return f"{number:,}".replace(',', ' ')
    return f"{number:,}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Форматирование процента
    
    Args:
        value: Значение (0-1)
        decimals: Количество знаков после запятой
        
    Returns:
        Отформатированная строка
    """
    return f"{value * 100:.{decimals}f}%"


# ============================================
# Форматирование JSON
# ============================================

def format_json_pretty(data: Any, indent: int = 2) -> str:
    """
    Красивое форматирование JSON
    
    Args:
        data: Данные для форматирования
        indent: Отступ
        
    Returns:
        Отформатированная JSON строка
    """
    return json.dumps(data, indent=indent, ensure_ascii=False)


def format_json_compact(data: Any) -> str:
    """
    Компактное форматирование JSON
    
    Args:
        data: Данные для форматирования
        
    Returns:
        Отформатированная JSON строка
    """
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


# ============================================
# Форматирование Markdown
# ============================================

def format_markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    """
    Форматирование таблицы в Markdown
    
    Args:
        headers: Заголовки таблицы
        rows: Строки таблицы
        
    Returns:
        Markdown таблица
    """
    if not headers or not rows:
        return ""
    
    # Формируем заголовок
    table = "| " + " | ".join(headers) + " |\n"
    
    # Формируем разделитель
    table += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    
    # Формируем строки
    for row in rows:
        table += "| " + " | ".join(row) + " |\n"
    
    return table


def format_markdown_list(items: List[str], ordered: bool = False) -> str:
    """
    Форматирование списка в Markdown
    
    Args:
        items: Элементы списка
        ordered: Упорядоченный список
        
    Returns:
        Markdown список
    """
    if not items:
        return ""
    
    if ordered:
        return "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))
    else:
        return "\n".join(f"- {item}" for item in items)


def format_markdown_code(code: str, language: str = "") -> str:
    """
    Форматирование кода в Markdown
    
    Args:
        code: Код
        language: Язык программирования
        
    Returns:
        Markdown код
    """
    return f"```{language}\n{code}\n```"


def format_markdown_quote(text: str) -> str:
    """
    Форматирование цитаты в Markdown
    
    Args:
        text: Текст цитаты
        
    Returns:
        Markdown цитата
    """
    lines = text.split('\n')
    return "\n".join(f"> {line}" for line in lines)


# ============================================
# Форматирование для логирования
# ============================================

def format_log_message(
    level: str,
    message: str,
    context: Optional[Dict] = None,
    extra: Optional[Dict] = None
) -> str:
    """
    Форматирование сообщения для логирования
    
    Args:
        level: Уровень логирования
        message: Сообщение
        context: Контекст (опционально)
        extra: Дополнительные данные (опционально)
        
    Returns:
        Отформатированное сообщение
    """
    parts = [f"[{level}]", message]
    
    if context:
        parts.append(f"Context: {json.dumps(context, ensure_ascii=False)}")
    
    if extra:
        parts.append(f"Extra: {json.dumps(extra, ensure_ascii=False)}")
    
    return " | ".join(parts)
