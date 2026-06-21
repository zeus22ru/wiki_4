#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Polling-worker Telegram-бота wiki_4 — связь с POST /api/chat/stream (SSE)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from config import get_logger, settings  # noqa: E402
from core.chat_attachments import attachments_enabled  # noqa: E402
from integrations.telegram import (  # noqa: E402
    TelegramClient,
    TelegramError,
    escape_html,
    markdown_to_telegram_html,
    split_markdown_for_telegram,
    strip_markdown_light,
)

logger = get_logger(__name__)

VALID_MODES = {"обычный", "кратко", "подробно", "по_источникам", "по_шагам", "инструкция"}
TELEGRAM_TYPING_INTERVAL_SECONDS: float = 5.0

BUTTON_HELP = "❓ Справка"
BUTTON_RESET = "🔄 Новый диалог"
BUTTON_MODE = "📝 Режим ответа"
BUTTON_HISTORY = "📜 История"

MODE_LABELS: dict[str, str] = {
    "обычный": "Обычный",
    "кратко": "Кратко",
    "подробно": "Подробно",
    "по_источникам": "По источникам",
    "по_шагам": "По шагам",
    "инструкция": "Инструкция",
}


def build_main_keyboard() -> dict[str, Any]:
    """Постоянная reply-клавиатура с основными действиями."""
    return {
        "keyboard": [
            [{"text": BUTTON_HELP}, {"text": BUTTON_RESET}],
            [{"text": BUTTON_MODE}, {"text": BUTTON_HISTORY}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_mode_inline_keyboard() -> dict[str, Any]:
    """Inline-клавиатура для выбора режима ответа."""
    rows = [
        ["обычный", "кратко"],
        ["подробно", "по_источникам"],
        ["по_шагам", "инструкция"],
    ]
    return {
        "inline_keyboard": [
            [
                {
                    "text": MODE_LABELS[mode],
                    "callback_data": f"mode:{mode}",
                }
                for mode in row
            ]
            for row in rows
        ],
    }


class TelegramSession:
    """In-memory состояние на telegram_user_id."""

    def __init__(self) -> None:
        self.user_id: int | None = None
        self.chat_id: int | None = None  # wiki_4 session_id
        self.answer_mode: str = "обычный"


_sessions: dict[int, TelegramSession] = {}


def get_session(tg_user_id: int) -> TelegramSession:
    if tg_user_id not in _sessions:
        _sessions[tg_user_id] = TelegramSession()
    return _sessions[tg_user_id]


def load_offset(path: str | Path) -> int | None:
    """Прочитать сохранённый offset обновлений Telegram."""
    offset_path = Path(path)
    if not offset_path.exists():
        return None
    try:
        data = json.loads(offset_path.read_text(encoding="utf-8"))
        offset = data.get("offset")
        return int(offset) if offset is not None else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning("Не удалось прочитать offset Telegram из %s", offset_path)
        return None


def save_offset(path: str | Path, offset: int) -> None:
    """Сохранить offset атомарной заменой файла."""
    offset_path = Path(path)
    offset_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = offset_path.with_suffix(offset_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps({"offset": int(offset)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(offset_path)


def parse_command(text: str) -> tuple[str | None, str]:
    """Выделение команды и аргументов из текста сообщения."""
    text = text.strip()
    if not text.startswith("/"):
        return None, text
    parts = text.split(maxsplit=1)
    cmd = parts[0][1:].lower()
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args


def normalize_user_input(text: str) -> tuple[str | None, str]:
    """Преобразовать нажатие кнопки reply-клавиатуры в команду."""
    text = text.strip()
    if text == BUTTON_HELP:
        return "help", ""
    if text == BUTTON_RESET:
        return "reset", ""
    if text == BUTTON_MODE:
        return "mode", ""
    if text == BUTTON_HISTORY:
        return "history", ""
    return parse_command(text)


def send_bot_message(
    client: TelegramClient,
    chat_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    """Отправить сообщение бота с основной клавиатурой по умолчанию."""
    try:
        client.send_message(
            chat_id,
            text,
            reply_markup=reply_markup if reply_markup is not None else build_main_keyboard(),
        )
    except TelegramError:
        logger.exception("Ошибка отправки сообщения в chat_id=%s", chat_id)


def _html_escape(text: str) -> str:
    """Экранирование спецсимволов HTML для Telegram."""
    return escape_html(text)


def handle_start(code: str, tg_user_id: int, client: TelegramClient) -> str:
    """Вызов POST /api/telegram/verify для привязки аккаунта."""
    try:
        url = f"{settings.TELEGRAM_INTERNAL_API_URL.rstrip('/')}/api/telegram/verify"
        headers: dict[str, str] = {
            "X-API-Key": settings.TELEGRAM_INTERNAL_API_KEY,
            "Content-Type": "application/json",
        }
        resp = requests.post(
            url,
            json={"code": code, "telegram_user_id": tg_user_id},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            session = get_session(tg_user_id)
            session.user_id = data.get("user_id")
            return (
                f"✅ Аккаунт привязан! "
                f"Ваш ID: {data['user_id']}, "
                f"роль: {data.get('role', 'user')}"
            )
        if resp.status_code == 404:
            return "❌ Код не найден или истёк. Запросите новый код в веб-интерфейсе."
        return f"❌ Ошибка привязки: {resp.status_code}"
    except requests.RequestException as exc:
        logger.exception("Ошибка привязки Telegram аккаунта для user_id=%s", tg_user_id)
        return f"❌ Ошибка сети при привязке: {exc}"


def handle_reset(session: TelegramSession) -> str:
    session.chat_id = None
    return "🔄 Сессия сброшена. Следующий вопрос начнёт новый диалог."


def handle_mode(mode: str) -> str:
    mode = mode.strip().lower()
    if mode not in VALID_MODES:
        return f"❌ Неизвестный режим. Доступные: {', '.join(sorted(VALID_MODES))}"
    return f"✅ Режим установлен: {mode}"


def handle_history(session: TelegramSession) -> str:  # noqa: ARG001
    return "📜 История чатов доступна в веб-интерфейсе."


def handle_help() -> str:
    return (
        "Доступные команды:\n"
        "/start <код> — привязать аккаунт wiki_4\n"
        "/reset — сбросить текущий диалог\n"
        "/mode <режим> — изменить режим ответа\n"
        "/history — история чатов\n"
        "/help — эта справка\n\n"
        "Или используйте кнопки под полем ввода.\n"
        "Кнопка «Режим ответа» откроет список режимов.\n\n"
        "Можно отправить фото (скриншот) с подписью или без — бот проанализирует "
        "изображение так же, как в веб-чате.\n\n"
        "Режимы: обычный, кратко, подробно, по_источникам, по_шагам, инструкция"
    )


def send_mode_picker(client: TelegramClient, chat_id: int, current_mode: str) -> None:
    """Показать inline-клавиатуру выбора режима."""
    text = (
        f"Текущий режим: <b>{_html_escape(current_mode)}</b>\n"
        "Выберите режим ответа:"
    )
    try:
        client.send_message(
            chat_id,
            text,
            formatted=True,
            reply_markup=build_mode_inline_keyboard(),
        )
    except TelegramError:
        logger.exception("Ошибка отправки выбора режима в chat_id=%s", chat_id)


def message_has_image(message: dict[str, Any]) -> bool:
    if message.get("photo"):
        return True
    document = message.get("document")
    if isinstance(document, dict):
        mime = (document.get("mime_type") or "").lower()
        return mime.startswith("image/")
    return False


def message_question_text(message: dict[str, Any]) -> str:
    return (message.get("text") or message.get("caption") or "").strip()


def primary_image_file_id(message: dict[str, Any]) -> str | None:
    photos = message.get("photo")
    if photos:
        return photos[-1].get("file_id")
    document = message.get("document")
    if isinstance(document, dict):
        mime = (document.get("mime_type") or "").lower()
        if mime.startswith("image/"):
            return document.get("file_id")
    return None


def upload_chat_attachment(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Загрузить вложение через тот же API, что и веб-чат."""
    url = f"{settings.TELEGRAM_INTERNAL_API_URL.rstrip('/')}/api/chat/attachments"
    headers = {"X-API-Key": settings.TELEGRAM_INTERNAL_API_KEY}
    response = requests.post(
        url,
        headers=headers,
        files={"files": (filename, file_bytes, content_type)},
        timeout=60,
    )
    if response.status_code == 403:
        raise RuntimeError("Вложения к чату отключены на сервере")
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(str(detail or f"HTTP {response.status_code}"))
    body = response.json()
    attachments = body.get("attachments") or []
    if not attachments:
        raise RuntimeError("Сервер не вернул id вложения")
    return str(attachments[0]["id"])


def collect_image_attachment_ids(client: TelegramClient, message: dict[str, Any]) -> list[str]:
    file_id = primary_image_file_id(message)
    if not file_id:
        return []
    file_bytes, filename, content_type = client.download_file_bytes(file_id)
    attachment_id = upload_chat_attachment(file_bytes, filename, content_type)
    return [attachment_id]


def _answer_part_label(index: int, total: int) -> str:
    if total <= 1:
        return ""
    return f"📄 Часть {index + 1}/{total}\n\n"


def _plain_preview_text(markdown_text: str) -> str:
    """Превью во время стриминга — plain text без обрезки по 85%."""
    preview = strip_markdown_light(markdown_text)
    limit = settings.TELEGRAM_MAX_MESSAGE_LENGTH
    if len(preview) > limit:
        preview = preview[: limit - 1] + "…"
    return preview


_SOURCES_SECTION_RE = re.compile(r"\n\n\*\*Источники:\*\*[\s\S]*$")


def _strip_sources_section(markdown_text: str) -> str:
    """Убрать блок «**Источники:**» из текста ответа (как в веб-UI)."""
    return _SOURCES_SECTION_RE.sub("", markdown_text).rstrip()


def _send_html_or_plain(
    client: TelegramClient,
    chat_id: int,
    text_html: str,
    text_plain: str,
    *,
    message_id: int | None = None,
) -> None:
    try:
        if message_id is not None:
            client.edit_message_text(
                chat_id,
                message_id,
                text_html,
                parse_mode="HTML",
                formatted=True,
            )
        else:
            client.send_message(
                chat_id,
                text_html,
                parse_mode="HTML",
                formatted=True,
            )
    except TelegramError:
        plain = text_plain
        limit = settings.TELEGRAM_MAX_MESSAGE_LENGTH
        if len(plain) > limit:
            plain = plain[: limit - 1] + "…"
        if message_id is not None:
            client.edit_message_text(chat_id, message_id, plain, parse_mode="")
        else:
            client.send_message(chat_id, plain, parse_mode="")


def _send_full_answer(
    client: TelegramClient,
    chat_id: int,
    message_id: int,
    markdown_text: str,
) -> None:
    """Отправить полный ответ: форматирование + разбиение на несколько сообщений."""
    display = markdown_text if markdown_text else "(пустой ответ)"
    parts = split_markdown_for_telegram(
        display,
        max_html_len=settings.TELEGRAM_MAX_MESSAGE_LENGTH,
    )
    total = len(parts)

    for index, part in enumerate(parts):
        label = _answer_part_label(index, total)
        html = markdown_to_telegram_html(part)
        if label:
            html = f"<b>{escape_html(label.strip())}</b>\n\n{html}"
        plain = strip_markdown_light(label + part)

        if index == 0:
            _send_html_or_plain(
                client,
                chat_id,
                html,
                plain,
                message_id=message_id,
            )
        else:
            _send_html_or_plain(client, chat_id, html, plain)


def _edit_streaming_preview(
    client: TelegramClient,
    chat_id: int,
    message_id: int,
    markdown_text: str,
) -> None:
    """Обновить превью во время стриминга (plain text, без преждевременной обрезки)."""
    client.edit_message_text(
        chat_id,
        message_id,
        _plain_preview_text(markdown_text),
        parse_mode="",
    )


def handle_question(
    update: dict[str, Any],
    session: TelegramSession,
    client: TelegramClient,
    *,
    text: str,
    has_image: bool = False,
) -> None:
    """Основной поток обработки вопроса со стримингом через SSE."""
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    tg_user_id = message.get("from", {}).get("id")

    if (not text and not has_image) or not tg_user_id or not chat_id:
        logger.warning("Пропущено сообщение без текста/фото или chat_id: %s", update.get("update_id"))
        return

    if not session.user_id:
        try:
            client.send_message(
                chat_id,
                "⚠️ Аккаунт не привязан. Отправьте /start <код>",
                reply_markup={"remove_keyboard": True},
            )
        except TelegramError:
            logger.exception("Не удалось отправить сообщение о непривязанном аккаунте")
        return

    attachment_ids: list[str] = []
    if has_image:
        if not attachments_enabled():
            try:
                client.send_message(chat_id, "⚠️ Вложения к чату отключены на сервере.")
            except TelegramError:
                logger.exception("Не удалось сообщить об отключённых вложениях")
            return
        try:
            attachment_ids = collect_image_attachment_ids(client, message)
        except (TelegramError, RuntimeError) as exc:
            logger.exception("Ошибка загрузки фото из Telegram для tg_user_id=%s", tg_user_id)
            try:
                client.send_message(chat_id, f"❌ Не удалось обработать фото: {exc}")
            except TelegramError:
                pass
            return
        if not attachment_ids:
            try:
                client.send_message(chat_id, "❌ Не удалось обработать фото.")
            except TelegramError:
                pass
            return

    # 1. Индикатор "печатает"
    try:
        client.send_chat_action(chat_id, "typing")
    except TelegramError:
        pass

    # 2. Отправить placeholder
    try:
        placeholder = client.send_message(chat_id, "⏳ Думаю...")
        message_id = placeholder["result"]["message_id"]
    except TelegramError:
        logger.exception("Не удалось отправить placeholder для chat_id=%s", chat_id)
        return

    # 3. Вызвать POST /api/chat/stream
    url = f"{settings.TELEGRAM_INTERNAL_API_URL.rstrip('/')}/api/chat/stream"
    headers = {
        "X-API-Key": settings.TELEGRAM_INTERNAL_API_KEY,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload: dict[str, Any] = {
        "message": text,
        "chat_id": session.chat_id,
        "answer_mode": session.answer_mode,
        "telegram_user_id": tg_user_id,
    }
    if attachment_ids:
        payload["attachment_ids"] = attachment_ids

    accumulated = ""
    sources: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    last_edit = 0.0
    min_edit_interval = settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS / 1000.0
    last_typing_at = 0.0
    stream_success = False

    try:
        resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("Ошибка запроса к /api/chat/stream для tg_user_id=%s", tg_user_id)
        try:
            client.edit_message_text(chat_id, message_id, f"❌ Ошибка связи с сервером: {exc}")
        except TelegramError:
            pass
        return

    try:
        sse_pattern = re.compile(r"^data:\s*(.*)$")
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            match = sse_pattern.match(line)
            if not match:
                continue
            data = match.group(1)
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            chunk_type = chunk.get("type")
            if chunk_type == "delta":
                accumulated += chunk.get("text", "")
            elif chunk_type == "done":
                if chunk.get("answer") is not None:
                    accumulated = chunk["answer"]
                sources = chunk.get("sources", [])
                citations = chunk.get("citations", [])
                if chunk.get("chat_id") is not None:
                    session.chat_id = chunk["chat_id"]
                stream_success = True
                break
            elif chunk_type == "error":
                error_msg = chunk.get("message", "Ошибка при обработке запроса")
                accumulated = f"❌ {error_msg}"
                stream_success = True
                break
            elif chunk_type == "status":
                # Можно игнорировать или показывать в placeholder
                pass

            now = time.time()
            if now - last_edit >= min_edit_interval and accumulated:
                display = accumulated if accumulated else "⏳ Думаю..."
                try:
                    if display == "⏳ Думаю...":
                        client.edit_message_text(chat_id, message_id, display, parse_mode="")
                    else:
                        _edit_streaming_preview(client, chat_id, message_id, display)
                    last_edit = now
                except TelegramError:
                    pass

            if now - last_typing_at >= TELEGRAM_TYPING_INTERVAL_SECONDS:
                try:
                    client.send_chat_action(chat_id, "typing")
                    last_typing_at = now
                except TelegramError:
                    pass
    except Exception:
        logger.exception("Ошибка чтения SSE-потока для tg_user_id=%s", tg_user_id)
        accumulated = "❌ Ошибка при получении ответа."

    try:
        answer_text = accumulated
        if not settings.TELEGRAM_SHOW_SOURCES:
            answer_text = _strip_sources_section(answer_text)
        _send_full_answer(client, chat_id, message_id, answer_text)
    except TelegramError:
        logger.exception("Не удалось отправить финальное сообщение")

    # Отправить источники отдельным сообщением
    if settings.TELEGRAM_SHOW_SOURCES and (sources or citations):
        sources_text_parts = ["📄 Источники:"]
        for i, src in enumerate(sources[:10], 1):
            title = src.get("title", "Без названия")
            path_or_url = src.get("path") or src.get("source", "")
            line = f"{i}. {title}"
            if path_or_url and path_or_url != "N/A":
                line += f" — {path_or_url}"
            sources_text_parts.append(line)
        for i, cit in enumerate(citations[:10], len(sources) + 1):
            src_name = cit.get("source", "Без названия")
            sources_text_parts.append(f"{i}. {src_name}")
        sources_text = "\n".join(sources_text_parts)
        try:
            client.send_message(chat_id, sources_text)
        except TelegramError:
            logger.exception("Не удалось отправить источники")


def process_callback_query(update: dict[str, Any], client: TelegramClient) -> None:
    """Обработка нажатий inline-кнопок."""
    callback = update.get("callback_query", {})
    data = (callback.get("data") or "").strip()
    tg_user_id = callback.get("from", {}).get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    callback_id = callback.get("id")

    if not data or not tg_user_id or not chat_id or not callback_id:
        return

    session = get_session(tg_user_id)

    if data.startswith("mode:"):
        mode = data[5:].strip().lower()
        reply = handle_mode(mode)
        try:
            client.answer_callback_query(
                callback_id,
                text=MODE_LABELS.get(mode, mode) if reply.startswith("✅") else reply[:200],
            )
        except TelegramError:
            logger.exception("Ошибка answerCallbackQuery для user_id=%s", tg_user_id)
        if reply.startswith("✅"):
            session.answer_mode = mode
            send_bot_message(client, chat_id, reply)
        else:
            send_bot_message(client, chat_id, reply)


def process_message(update: dict[str, Any], client: TelegramClient) -> None:
    """Диспетчер: команда, кнопка или вопрос (в т.ч. с фото)."""
    message = update.get("message", {})
    raw_text = (message.get("text") or "").strip()
    question_text = message_question_text(message)
    has_image = message_has_image(message)
    tg_user_id = message.get("from", {}).get("id")
    chat_id = message.get("chat", {}).get("id")

    if not tg_user_id or not chat_id:
        return
    if not raw_text and not question_text and not has_image:
        return

    session = get_session(tg_user_id)
    cmd, args = normalize_user_input(raw_text) if raw_text else (None, "")

    if cmd == "start":
        if args:
            reply = handle_start(args, tg_user_id, client)
            send_bot_message(client, chat_id, reply)
        else:
            send_bot_message(
                client,
                chat_id,
                "Привет! Отправьте /start <код>, чтобы привязать аккаунт wiki_4.",
                reply_markup={"remove_keyboard": True},
            )
    elif cmd == "reset":
        reply = handle_reset(session)
        send_bot_message(client, chat_id, reply)
    elif cmd == "mode":
        if args:
            reply = handle_mode(args)
            send_bot_message(client, chat_id, reply)
            if reply.startswith("✅"):
                session.answer_mode = args.strip().lower()
        else:
            send_mode_picker(client, chat_id, session.answer_mode)
    elif cmd == "history":
        reply = handle_history(session)
        send_bot_message(client, chat_id, reply)
    elif cmd == "help":
        reply = handle_help()
        send_bot_message(client, chat_id, reply)
    elif cmd is None:
        handle_question(
            update,
            session,
            client,
            text=question_text,
            has_image=has_image,
        )
    else:
        send_bot_message(client, chat_id, f"❌ Неизвестная команда: /{cmd}")


def process_update(update: dict[str, Any], client: TelegramClient) -> None:
    """Диспетчер входящих обновлений Telegram."""
    if update.get("callback_query"):
        process_callback_query(update, client)
        return
    if update.get("message"):
        process_message(update, client)


def run_once(
    client: TelegramClient,
    offset: int | None,
    limit: int = 100,
) -> tuple[int | None, int]:
    """Получить updates и обработать. Возвращает (next_offset, processed_count)."""
    updates = client.get_updates(offset=offset, limit=limit)
    processed = 0
    for update in updates:
        try:
            process_update(update, client)
            processed += 1
        except Exception:
            logger.exception("Ошибка обработки update id=%s", update.get("update_id"))
        if "update_id" in update:
            offset = update["update_id"] + 1
    return offset, processed


def main() -> int:
    parser = argparse.ArgumentParser(description="Запустить polling-worker Telegram-бота wiki_4.")
    parser.add_argument("--once", action="store_true", help="Выполнить один polling-цикл и завершиться")
    parser.add_argument("--limit", type=int, default=100, help="Размер пачки updates getUpdates")
    args = parser.parse_args()

    if not settings.TELEGRAM_ENABLED:
        print("TELEGRAM_ENABLED=false. Включите интеграцию в .env перед запуском worker.")
        return 1

    if not settings.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN не задан")
        return 1

    client = TelegramClient(
        bot_token=settings.TELEGRAM_BOT_TOKEN,
        max_message_length=settings.TELEGRAM_MAX_MESSAGE_LENGTH,
    )

    try:
        me = client.get_me()
    except TelegramError as exc:
        print(f"Ошибка подключения к Telegram API: {exc}")
        return 1

    username = me.get("result", {}).get("username", "unknown")
    print(f"Подключён как @{username}")
    logger.info("Telegram worker запущен как @%s", username)

    offset = load_offset(settings.TELEGRAM_OFFSET_PATH)
    logger.info("Telegram worker offset=%s", offset)

    while True:
        try:
            next_offset, processed = run_once(client, offset, limit=args.limit)
            if next_offset is not None:
                offset = next_offset
                save_offset(settings.TELEGRAM_OFFSET_PATH, offset)
            logger.info("Цикл Telegram завершён: обработано=%s, next_offset=%s", processed, next_offset)

            if args.once:
                return 0
            if processed == 0:
                time.sleep(max(1, settings.TELEGRAM_POLL_INTERVAL_SECONDS))
        except KeyboardInterrupt:
            print("\nОстановка...")
            logger.info("Telegram worker остановлен по KeyboardInterrupt")
            break
        except Exception:
            logger.exception("Ошибка в основном цикле Telegram worker")
            if args.once:
                return 1
            time.sleep(5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
