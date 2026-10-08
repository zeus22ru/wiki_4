#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke-test: принимает ли модель изображения (ТЗ §15.1, §24.5).

Отправляет небольшое изображение с известным текстом на OpenAI-совместимый
endpoint (/v1/chat/completions) и проверяет, что модель реально получает
картинку и читает с неё контрольный код.

Это реальный сетевой запрос с ключом из настроек (.env) — выполняется только
по явному запуску. Модель/сервер можно задать аргументами.

Запуск:
    .\\.venv\\Scripts\\python.exe scripts/check_vision_model.py --model deepseek-v4-pro
    .\\.venv\\Scripts\\python.exe scripts/check_vision_model.py --list

Коды возврата:
    0 — изображение принято и код прочитан (vision подтверждён)
    2 — модели изображения не поддерживаются (vision_unsupported)
    3 — изображение принято, но контрольный код не найден (неубедительно)
    1 — ошибка запроса/конфигурации
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

from config import settings  # noqa: E402

#: Контрольный код, который заведомо отсутствует в обычном тексте промпта.
_CONTROL_CODE = "7391"
_CONTROL_TEXT = f"VISION {_CONTROL_CODE}"
_CONTROL_TEXT_RU = "Проверка 42"

_IMAGE_UNSUPPORTED_HINTS = (
    "image", "vision", "multimodal", "invalid content type", "content_type",
    "does not support", "unsupported",
)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def _mask(secret: str) -> str:
    if not secret:
        return "(нет)"
    return secret[:4] + "…" + secret[-2:] if len(secret) > 8 else "(задан)"


def make_probe_image() -> bytes:
    """Сгенерировать PNG с контрольным текстом."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Нужен Pillow для генерации картинки: {exc}")

    font = None
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "tahoma.ttf"):
        try:
            font = ImageFont.truetype(name, 44)
            break
        except Exception:
            continue
    if font is None:
        raise SystemExit("Не найден TrueType-шрифт для генерации картинки")

    img = Image.new("RGB", (520, 160), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), _CONTROL_TEXT, fill="black", font=font)
    draw.text((20, 90), _CONTROL_TEXT_RU, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def list_models(base_url: str, api_key: str, timeout: float) -> int:
    """Показать список моделей сервера (GET /v1/models)."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = requests.get(f"{base_url}/v1/models", headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        print(f"✗ Не удалось получить список моделей: {exc}")
        return 1
    if response.status_code != 200:
        print(f"✗ GET /v1/models → HTTP {response.status_code}: {response.text[:300]}")
        return 1
    payload = response.json()
    models = payload.get("data") or payload.get("models") or []
    ids = [m.get("id") or m.get("name") for m in models if isinstance(m, dict)]
    print(f"Сервер {base_url}: моделей — {len(ids)}")
    for model_id in ids:
        print(f"  - {model_id}")
    return 0


def check_vision(base_url: str, api_key: str, model: str, timeout: float) -> int:
    """Проверить приём изображения моделью."""
    image = make_probe_image()
    data_url = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Прочитай текст на изображении дословно."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 1024,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    print(f"Endpoint: {base_url}/v1/chat/completions")
    print(f"Модель:   {model}")
    print(f"Ключ:     {_mask(api_key)}")
    print(f"Контроль: {_CONTROL_TEXT} / {_CONTROL_TEXT_RU}")
    print("Отправляю запрос с изображением…")

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions", json=payload, headers=headers, timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        print(f"✗ Ошибка запроса: {exc}")
        return 1

    if response.status_code != 200:
        body = response.text[:600]
        low = body.lower()
        if response.status_code in (400, 404, 415, 422) and any(h in low for h in _IMAGE_UNSUPPORTED_HINTS):
            print(f"✗ HTTP {response.status_code}: модель не принимает изображения (vision_unsupported).")
            print(f"  Ответ сервера: {body}")
            return 2
        print(f"✗ HTTP {response.status_code}: {body}")
        return 1

    data = response.json()
    content = ""
    finish_reason = ""
    try:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        # reasoning-модели могут отдать reasoning_content вместо/вместе с content
        content = message.get("content") or message.get("reasoning_content") or ""
        finish_reason = choice.get("finish_reason") or ""
    except Exception:
        content = ""
    print(f"finish_reason: {finish_reason}")
    print(f"Ответ модели (первые 300 симв.): {content[:300]!r}")

    if _CONTROL_CODE in content:
        print(f"✓ OK: модель приняла изображение и прочитала код {_CONTROL_CODE}.")
        return 0
    print(
        "△ Изображение принято (HTTP 200), но контрольный код не найден.\n"
        "  Возможные причины: слабый OCR у модели, картинка не дошла до неё,\n"
        "  или модель ответила, игнорируя изображение. Нужна ручная проверка."
    )
    return 3


def main() -> int:
    default_model = (
        getattr(settings, "VISUAL_CHAT_MODEL", "") or settings.OLLAMA_CHAT_MODEL
    )
    default_base = (
        getattr(settings, "VISUAL_CHAT_BASE_URL", "") or settings.get_chat_base_url()
    ).rstrip("/")
    default_key = (
        getattr(settings, "VISUAL_CHAT_API_KEY", "") or settings.get_chat_api_key()
    )

    parser = argparse.ArgumentParser(description="Smoke-test поддержки изображений моделью")
    parser.add_argument("--model", default=default_model, help="Идентификатор модели")
    parser.add_argument("--base-url", default=default_base, help="Базовый URL без /v1")
    parser.add_argument("--api-key", default=default_key, help="Ключ (по умолчанию из настроек)")
    parser.add_argument("--timeout", type=float, default=90.0, help="Таймаут запроса, сек")
    parser.add_argument("--list", action="store_true", help="Только показать список моделей")
    args = parser.parse_args()

    _configure_stdout()

    if not args.base_url:
        print("✗ Не задан базовый URL (--base-url или CHAT_BASE_URL/OLLAMA_URL).")
        return 1

    if args.list:
        return list_models(args.base_url, args.api_key, args.timeout)

    if not args.model:
        print("✗ Не задана модель (--model или OLLAMA_CHAT_MODEL).")
        return 1
    return check_vision(args.base_url, args.api_key, args.model, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
