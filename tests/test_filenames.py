#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты безопасных имён файлов (контракт K3)."""

from utils.filenames import file_extension, safe_filename


def test_safe_filename_keeps_cyrillic_and_lowercases_ext():
    assert safe_filename("Отчёт (финал).PDF") == "Отчёт_финал.pdf"


def test_safe_filename_screenshot_png():
    assert safe_filename("Снимок экрана 2026.PNG") == "Снимок_экрана_2026.png"


def test_safe_filename_strips_path_traversal():
    assert safe_filename("a/../b.txt") == "b.txt"
    assert safe_filename("..\\secret\\b.txt") == "b.txt"


def test_safe_filename_without_extension():
    assert safe_filename("readme") == "readme"
    assert "." not in safe_filename("только имя")


def test_safe_filename_preserves_extension_when_present():
    assert safe_filename("Документ.DOCX").endswith(".docx")
    assert safe_filename("x.HTML").endswith(".html")


def test_safe_filename_long_name_keeps_extension():
    long_stem = "а" * 300
    result = safe_filename(f"{long_stem}.pdf")
    assert result.endswith(".pdf")
    assert len(result) <= 180


def test_safe_filename_emoji_only_falls_back_with_ext():
    assert safe_filename("😀🎉.PNG") == "file.png"
    assert safe_filename("🔥") == "file"


def test_file_extension_cases():
    assert file_extension("a.PNG") == "png"
    assert file_extension("noext") == ""
    assert file_extension("") == ""
    assert file_extension(".env") == ""
