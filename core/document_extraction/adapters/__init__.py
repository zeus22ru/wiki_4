#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регистрация встроенных адаптеров извлечения.

Импорт адаптеров ленивый и безопасный: если тяжёлая библиотека (openpyxl,
python-pptx, pdfplumber и т.п.) отсутствует, адаптер регистрируется, но при
вызове вернёт статус ``unsupported`` с понятной диагностикой.
"""

from __future__ import annotations

_registered = False


def register_default_adapters(force: bool = False) -> None:
    """Зарегистрировать все встроенные адаптеры (идемпотентно)."""
    global _registered
    if _registered and not force:
        return
    from ..registry import register_adapter
    from .text_adapter import TextSourceAdapter
    from .html_adapter import HtmlSourceAdapter
    from .docx_adapter import DocxSourceAdapter
    from .pdf_adapter import PdfSourceAdapter
    from .pptx_adapter import PptxSourceAdapter
    from .xlsx_adapter import XlsxSourceAdapter
    from .image_adapter import ImageSourceAdapter
    from .convert_adapter import ConvertSourceAdapter

    register_adapter(TextSourceAdapter())
    register_adapter(HtmlSourceAdapter())
    register_adapter(DocxSourceAdapter())
    register_adapter(PdfSourceAdapter())
    register_adapter(PptxSourceAdapter())
    register_adapter(XlsxSourceAdapter())
    register_adapter(ImageSourceAdapter())
    register_adapter(ConvertSourceAdapter())
    _registered = True
