#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Конфигурация логирования для приложения
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

# Импорт настроек
from .settings import settings


class ColoredFormatter(logging.Formatter):
    """Форматтер с цветами для консольного вывода"""
    
    # ANSI коды цветов
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # Добавляем цвет к уровню логирования
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    log_level: Optional[str] = None,
    log_dir: Optional[str] = None,
    app_name: str = "wiki_qa"
) -> None:
    """
    Настройка логирования для приложения
    
    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Директория для хранения логов
        app_name: Имя приложения для логов
    """
    # Получаем настройки из конфигурации если не переданы
    if log_level is None:
        log_level = settings.LOG_LEVEL
    if log_dir is None:
        log_dir = settings.LOG_DIR
    
    # Создаем директорию для логов
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Получаем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Удаляем существующие обработчики
    root_logger.handlers.clear()
    
    # Формат сообщений
    detailed_format = (
        '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s'
    )
    simple_format = '%(asctime)s | %(levelname)-8s | %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Консольный обработчик с цветами
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = ColoredFormatter(simple_format, datefmt=date_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Файловый обработчик для всех логов
    all_logs_file = log_path / f"{app_name}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        all_logs_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(detailed_format, datefmt=date_format)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # Файловый обработчик только для ошибок
    error_logs_file = log_path / f"{app_name}_error.log"
    error_handler = logging.handlers.RotatingFileHandler(
        error_logs_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_formatter = logging.Formatter(detailed_format, datefmt=date_format)
    error_handler.setFormatter(error_formatter)
    root_logger.addHandler(error_handler)
    
    # Уменьшаем шум от сторонних библиотек
    logging.getLogger('chromadb').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Получить логгер для модуля
    
    Args:
        name: Имя модуля (обычно __name__)
    
    Returns:
        Логгер с настроенным форматированием
    """
    return logging.getLogger(name)


# Автоматически настраиваем логирование при импорте
setup_logging()
