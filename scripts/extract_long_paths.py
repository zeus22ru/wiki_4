#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Скрипт для распаковки ZIP-архивов с поддержкой длинных путей в Windows.
Использует префикс \\?\ для обхода ограничения MAX_PATH (260 символов).
Декодирует URL-encoded имена и заменяет недопустимые символы.
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings

REPLACEMENTS = {
    ':': '_',
    '*': '_',
    '?': '_',
    '"': '_',
    '<': '_',
    '>': '_',
    '|': '_',
}


def sanitize_filename(filename: str) -> str:
    """Заменяет недопустимые символы в имени файла."""
    for invalid, replacement in REPLACEMENTS.items():
        filename = filename.replace(invalid, replacement)
    return filename


def ensure_long_path(path: str) -> str:
    r"""Добавляет префикс \\?\ для поддержки длинных путей в Windows."""
    if sys.platform == 'win32' and not path.startswith('\\\\?\\'):
        # Преобразуем в абсолютный путь
        path = os.path.abspath(path)
        # Заменяем прямые слеши на обратные для Windows
        path = path.replace('/', '\\')
        # Добавляем префикс
        path = '\\\\?\\' + path
    return path


def _safe_member_path(member_name: str) -> Path:
    """Возвращает относительный путь участника архива без traversal-компонентов."""
    decoded = unquote(member_name).replace("\\", "/")
    parts = []
    for part in PurePosixPath(decoded).parts:
        if part in ("", ".", "..") or part.endswith(":"):
            continue
        parts.append(sanitize_filename(part))
    return Path(*parts) if parts else Path()


def extract_zip(zip_path: Path, extract_to: Path) -> None:
    """Распаковывает ZIP-архив с поддержкой длинных путей."""
    zip_path = zip_path.resolve()
    extract_to = extract_to.resolve()
    long_zip_path = ensure_long_path(str(zip_path))
    long_extract_to = ensure_long_path(str(extract_to))

    # Создаем целевую директорию
    os.makedirs(long_extract_to, exist_ok=True)

    with zipfile.ZipFile(long_zip_path, 'r') as zip_ref:
        for member in zip_ref.infolist():
            member_relative_path = _safe_member_path(member.filename)
            if not member_relative_path.parts:
                continue

            member_path = extract_to / member_relative_path
            long_member_path = ensure_long_path(str(member_path))

            # Создаем директории
            if member.is_dir() or member.filename.endswith('/'):
                os.makedirs(long_member_path, exist_ok=True)
            else:
                # Создаем родительскую директорию
                parent_dir = os.path.dirname(long_member_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                # Распаковываем файл
                with zip_ref.open(member) as source, open(long_member_path, 'wb') as target:
                    target.write(source.read())

    print(f"Архив {zip_path} успешно распакован в {extract_to}")


def _iter_zip_jobs(input_path: Path, output_path: Path | None, pattern: str):
    if input_path.is_file():
        if input_path.suffix.lower() != ".zip":
            raise ValueError(f"Ожидался ZIP-файл: {input_path}")
        yield input_path, output_path or input_path.with_suffix("")
        return

    if not input_path.is_dir():
        raise FileNotFoundError(f"Входной путь не найден: {input_path}")

    for zip_path in sorted(input_path.glob(pattern)):
        if not zip_path.is_file() or zip_path.suffix.lower() != ".zip":
            continue
        destination = (output_path / zip_path.stem) if output_path else zip_path.with_suffix("")
        yield zip_path, destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Распаковка ZIP-архивов из data/ с поддержкой длинных путей Windows."
    )
    parser.add_argument(
        "-i",
        "--input",
        default=str(PROJECT_ROOT / settings.DATA_DIR),
        help="ZIP-файл или директория с ZIP-архивами (по умолчанию DATA_DIR из настроек)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Директория вывода. Для одного ZIP можно указать конечную папку распаковки.",
    )
    parser.add_argument(
        "--pattern",
        default="*.zip",
        help="Маска ZIP-файлов при input-директории (по умолчанию *.zip)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    for zip_path, extract_to in _iter_zip_jobs(input_path, output_path, args.pattern):
        print(f"Распаковка {zip_path}...")
        try:
            extract_zip(zip_path, extract_to)
        except Exception as e:
            print(f"Ошибка при распаковке {zip_path}: {e}")

if __name__ == '__main__':
    main()
