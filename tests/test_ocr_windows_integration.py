#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows integration-тест portable RapidOCR-json (ТЗ §22.6).

Пропускается, если portable-комплект не распакован (нет EXE). Не требует сети.
Проверяет реальный запуск EXE, pipe-режим, распознавание, второй проход и
корректное закрытие процессов.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from core.ocr import RapidOcrJsonProvider, profile_args

_REPO = Path(__file__).resolve().parents[1]
_EXE = _REPO / ".tools" / "rapidocr-json" / "0.2.0" / "RapidOCR-json.exe"

pytestmark = pytest.mark.skipif(not _EXE.is_file(), reason="portable RapidOCR-json не установлен")


def _make_image_with_text() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "tahoma.ttf"):
        try:
            font = ImageFont.truetype(name, 40)
            break
        except Exception:
            continue
    if font is None:
        pytest.skip("нет TrueType-шрифта для генерации тестовой картинки")

    img = Image.new("RGB", (720, 120), "white")
    ImageDraw.Draw(img).text((20, 30), "Расходного ордера 00-00006695", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_profile_args_cyrillic() -> None:
    args = profile_args("cyrillic")
    assert "--rec=rec_cyrillic_PP-OCRv3_infer.onnx" in args
    assert "--keys=dict_cyrillic.txt" in args
    assert "--det=ch_PP-OCRv3_det_infer.onnx" in args


def test_auto_discovery_finds_pack() -> None:
    provider = RapidOcrJsonProvider()
    assert provider.executable.endswith("RapidOCR-json.exe")
    assert Path(provider.executable).is_file()
    assert provider.health_check()["ok"] is True


def test_real_engine_pipe_recognizes_and_closes() -> None:
    provider = RapidOcrJsonProvider(
        executable=str(_EXE), mode="pipe", profile="cyrillic", dual_pass=True,
        startup_timeout_sec=30, recognize_timeout_sec=120, retry_count=0,
    )
    try:
        health = provider.health_check()
        assert health["ok"] is True
        res = provider.recognize(_make_image_with_text())
        assert res.status == "success", res.warnings
        assert res.blocks, "нет блоков OCR"
        combined = (res.text_raw + "\n" + res.text_raw_alt)
        # Второй проход (латиница/цифры) должен надёжно ловить номер ордера.
        assert "000066" in combined, combined
    finally:
        provider.close()
    assert provider._procs == {}
