#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Скрипт для распаковки ZIP-архивов с поддержкой длинных путей в Windows.
Использует префикс \\?\ для обхода ограничения MAX_PATH (260 символов).
Декодирует URL-encoded имена и заменяет недопустимые символы.
"""

import os
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote

# Недопустимые символы в именах файлов Windows
INVALID_CHARS = '<>:"/\|?*'
REPLACEMENTS = {
    ':': '_',
    '*': '_',
    '?': '_',
    '"': '_',
    '<': '_',
    '>': '_',
    '|': '_',
}

def sanitize_filename(filename):
    """Заменяет недопустимые символы в имени файла."""
    for invalid, replacement in REPLACEMENTS.items():
        filename = filename.replace(invalid, replacement)
    return filename

def ensure_long_path(path):
    r"""Добавляет префикс \\?\ для поддержки длинных путей в Windows."""
    if sys.platform == 'win32' and not path.startswith('\\\\?\\'):
        # Преобразуем в абсолютный путь
        path = os.path.abspath(path)
        # Заменяем прямые слеши на обратные для Windows
        path = path.replace('/', '\\')
        # Добавляем префикс
        path = '\\\\?\\' + path
    return path

def extract_zip(zip_path, extract_to):
    """Распаковывает ZIP-архив с поддержкой длинных путей."""
    zip_path = ensure_long_path(zip_path)
    extract_to = ensure_long_path(extract_to)

    # Создаем целевую директорию
    os.makedirs(extract_to, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for member in zip_ref.infolist():
            # Декодируем URL-encoded имя файла
            member_filename = unquote(member.filename)
            # Заменяем недопустимые символы
            member_filename = sanitize_filename(member_filename)
            # Заменяем прямые слеши на обратные
            member_filename = member_filename.replace('/', '\\')
            
            member_path = os.path.join(extract_to, member_filename)
            member_path = ensure_long_path(member_path)

            # Создаем директории
            if member.filename.endswith('/'):
                os.makedirs(member_path, exist_ok=True)
            else:
                # Создаем родительскую директорию
                parent_dir = os.path.dirname(member_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                # Распаковываем файл
                with zip_ref.open(member) as source, open(member_path, 'wb') as target:
                    target.write(source.read())

    print(f"Архив {zip_path} успешно распакован в {extract_to}")

def main():
    data_dir = Path(__file__).parent / 'data'
    zip_files = [
        '1c.WebHome.zip',
        'faq.WebHome.zip',
        'sa.WebHome.zip'
    ]

    for zip_file in zip_files:
        zip_path = data_dir / zip_file
        extract_to = data_dir / zip_file.replace('.zip', '')

        if zip_path.exists():
            print(f"Распаковка {zip_file}...")
            try:
                extract_zip(str(zip_path), str(extract_to))
            except Exception as e:
                print(f"Ошибка при распаковке {zip_file}: {e}")
        else:
            print(f"Файл {zip_file} не найден")

if __name__ == '__main__':
    main()
