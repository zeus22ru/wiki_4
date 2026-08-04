#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Клиент Telegram Bot API для wiki_4 RAG."""

from __future__ import annotations

import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

TELEGRAM_MAX_MESSAGE_LENGTH_DEFAULT: int = 4096
_FENCED_CODE_RE = re.compile(r"```(?:\w*\n)?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BULLET_RE = re.compile(r"^(\s*)\*\s+", re.MULTILINE)


def escape_html(text: str) -> str:
    """Экранирование спецсимволов для Telegram parse_mode=HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def strip_markdown_light(text: str) -> str:
    """Убрать markdown-разметку для plain-text fallback в Telegram."""
    text = re.sub(r"```(?:\w*\n)?(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = _BULLET_RE.sub(r"\1• ", text)
    return text


def markdown_to_telegram_html(text: str) -> str:
    """Преобразовать распространённый Markdown ответа LLM в HTML для Telegram."""
    if not text:
        return ""

    parts: list[tuple[str, str]] = []
    last_end = 0
    for match in _FENCED_CODE_RE.finditer(text):
        if match.start() > last_end:
            parts.append(("text", text[last_end : match.start()]))
        parts.append(("code", match.group(1).rstrip("\n")))
        last_end = match.end()
    if last_end < len(text):
        parts.append(("text", text[last_end:]))

    if not parts:
        parts = [("text", text)]

    chunks: list[str] = []
    for kind, chunk in parts:
        if kind == "code":
            chunks.append(f"<pre>{escape_html(chunk)}</pre>")
        else:
            chunks.append(_markdown_text_chunk_to_html(chunk))
    return "".join(chunks)


def _markdown_text_chunk_to_html(text: str) -> str:
    text = escape_html(text)
    text = _LINK_RE.sub(
        lambda m: f'<a href="{escape_html(m.group(2))}">{m.group(1)}</a>',
        text,
    )
    text = _INLINE_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _BOLD_RE.sub(
        lambda m: f"<b>{m.group(1) or m.group(2)}</b>",
        text,
    )
    text = _HEADER_RE.sub(lambda m: f"<b>{m.group(1).strip()}</b>", text)
    text = _BULLET_RE.sub(r"\1• ", text)
    return text


def split_markdown_for_telegram(
    markdown: str,
    *,
    max_html_len: int = TELEGRAM_MAX_MESSAGE_LENGTH_DEFAULT,
    part_header_reserve: int = 32,
) -> list[str]:
    """Разбить markdown на части, каждая влезает в лимит Telegram после конвертации в HTML."""
    markdown = markdown or ""
    if not markdown.strip():
        return [markdown]

    content_limit = max(500, max_html_len - part_header_reserve)
    single_html = markdown_to_telegram_html(markdown)
    if len(single_html) <= content_limit:
        return [markdown]

    parts: list[str] = []
    remaining = markdown
    while remaining:
        remaining = remaining.lstrip("\n")
        if not remaining:
            break

        if len(markdown_to_telegram_html(remaining)) <= content_limit:
            parts.append(remaining)
            break

        lo, hi = 1, len(remaining)
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = remaining[:mid]
            para_break = candidate.rfind("\n\n")
            if para_break >= int(mid * 0.4):
                candidate = remaining[:para_break]
            else:
                line_break = candidate.rfind("\n")
                if line_break >= int(mid * 0.5):
                    candidate = remaining[:line_break]

            if not candidate.strip():
                lo = mid + 1
                continue

            if len(markdown_to_telegram_html(candidate)) <= content_limit:
                best = len(candidate)
                lo = mid + 1
            else:
                hi = mid - 1

        if best <= 0:
            best = 1
            while best < len(remaining):
                if len(markdown_to_telegram_html(remaining[:best])) > content_limit:
                    best = max(1, best - 1)
                    break
                best += 1

        chunk = remaining[:best].rstrip()
        if not chunk:
            chunk = remaining[:1]
        parts.append(chunk)
        remaining = remaining[len(chunk) :]

    return parts if parts else [markdown]


def validate_rich_message(rich_message: dict[str, Any]) -> dict[str, Any]:
    """Require exactly one of markdown / html / blocks per Bot API InputRichMessage."""
    if not isinstance(rich_message, dict):
        raise ValueError("rich_message must be a dict")
    present = [k for k in ("markdown", "html", "blocks") if k in rich_message and rich_message[k] is not None]
    if len(present) != 1:
        raise ValueError("rich_message must contain exactly one of markdown, html, blocks")
    return rich_message


def prepare_rich_markdown(text: str, *, max_chars: int) -> str:
    """Truncate markdown for Rich Message limits."""
    text = text or ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    return text[: max_chars - 1] + "…"


class TelegramError(RuntimeError):
    """Ошибка вызова Telegram Bot API."""


@dataclass
class TelegramClient:
    """Минимальный клиент для методов Telegram Bot API."""

    bot_token: str
    base_url: str = "https://api.telegram.org"
    timeout: float = 40.0
    max_message_length: int = TELEGRAM_MAX_MESSAGE_LENGTH_DEFAULT

    def __post_init__(self) -> None:
        self.bot_token = (self.bot_token or "").strip()
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN не задан")
        self.base_url = self.base_url.rstrip("/")

    def _method_url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.bot_token}/{method}"

    def _request(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._method_url(method)
        try:
            if files is not None:
                response = requests.post(
                    url,
                    data=data or {},
                    files=files,
                    timeout=self.timeout,
                )
            elif json_payload is not None:
                response = requests.post(
                    url,
                    json=json_payload,
                    timeout=self.timeout,
                )
            else:
                response = requests.get(
                    url,
                    params=params or {},
                    timeout=self.timeout,
                )
        except requests.RequestException as exc:
            raise TelegramError(f"Ошибка HTTP при вызове {method}: {exc}") from exc

        if response.status_code == 429:
            try:
                body = response.json()
                retry_after = body.get("parameters", {}).get("retry_after", 1)
            except Exception:
                retry_after = 1
            time.sleep(retry_after)
            return self._request(
                method,
                params=params,
                json_payload=json_payload,
                data=data,
                files=files,
            )

        try:
            response.raise_for_status()
            body = response.json()
        except requests.HTTPError as exc:
            raise TelegramError(f"HTTP {response.status_code} при вызове {method}: {exc}") from exc
        except ValueError as exc:
            raise TelegramError(f"Telegram вернул не JSON для {method}") from exc

        if not body.get("ok"):
            description = body.get("description", "unknown error")
            raise TelegramError(f"Ошибка Telegram {method}: {description}")

        return body

    def get_updates(
        self,
        offset: int | None = None,
        limit: int = 100,
        timeout: int = 30,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        body = self._request("getUpdates", params=payload)
        return body.get("result", []) or []

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str = "HTML",
        formatted: bool = False,
        disable_web_page_preview: bool = True,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = self._prepare_text(text, parse_mode=parse_mode, formatted=formatted)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._request("sendMessage", json_payload=payload)

    def send_rich_message(
        self,
        chat_id: int,
        rich_message: dict[str, Any],
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "rich_message": validate_rich_message(rich_message),
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._request("sendRichMessage", json_payload=payload)

    def send_rich_message_draft(
        self,
        chat_id: int,
        draft_id: int,
        rich_message: dict[str, Any],
    ) -> dict[str, Any]:
        if not draft_id:
            raise ValueError("draft_id must be a non-zero integer")
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "draft_id": int(draft_id),
            "rich_message": validate_rich_message(rich_message),
        }
        return self._request("sendRichMessageDraft", json_payload=payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True
        return self._request("answerCallbackQuery", json_payload=payload)

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str = "HTML",
        formatted: bool = False,
    ) -> dict[str, Any]:
        text = self._prepare_text(text, parse_mode=parse_mode, formatted=formatted)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self._request("editMessageText", json_payload=payload)

    def send_chat_action(self, chat_id: int, action: str = "typing") -> dict[str, Any]:
        return self._request(
            "sendChatAction",
            json_payload={"chat_id": chat_id, "action": action},
        )

    def send_photo(
        self,
        chat_id: int,
        photo: bytes,
        *,
        filename: str = "diagram.png",
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Upload a PNG/JPEG photo via Bot API sendPhoto (multipart)."""
        if not photo:
            raise ValueError("photo bytes must be non-empty")
        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        mime, _ = mimetypes.guess_type(filename)
        files = {"photo": (filename, photo, mime or "image/png")}
        return self._request("sendPhoto", data=data, files=files)

    def get_me(self) -> dict[str, Any]:
        return self._request("getMe")

    def get_file(self, file_id: str) -> dict[str, Any]:
        body = self._request("getFile", params={"file_id": file_id})
        result = body.get("result")
        if not isinstance(result, dict):
            raise TelegramError("Telegram не вернул метаданные файла")
        return result

    def download_file_bytes(self, file_id: str) -> tuple[bytes, str, str]:
        """Скачать файл по file_id. Возвращает (bytes, filename, mime)."""
        info = self.get_file(file_id)
        file_path = info.get("file_path")
        if not file_path:
            raise TelegramError("Telegram не вернул file_path")
        url = f"{self.base_url}/file/bot{self.bot_token}/{file_path}"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TelegramError(f"Ошибка скачивания файла: {exc}") from exc
        filename = Path(str(file_path)).name or "photo.jpg"
        mime, _ = mimetypes.guess_type(filename)
        return response.content, filename, mime or "image/jpeg"

    def _prepare_text(
        self,
        text: str,
        *,
        parse_mode: str = "HTML",
        formatted: bool = False,
    ) -> str:
        if parse_mode == "HTML" and not formatted:
            text = escape_html(text)
        if len(text) > self.max_message_length:
            if formatted:
                text = self._truncate_html_safe(text, self.max_message_length)
            else:
                text = self._smart_truncate(text, self.max_message_length)
        return text

    @staticmethod
    def _truncate_html_safe(html: str, max_length: int) -> str:
        if len(html) <= max_length:
            return html
        suffix = "\n\n…"
        max_length = max(100, max_length - len(suffix))
        truncated = TelegramClient._smart_truncate(html, max_length)
        truncated = re.sub(r"<[^>]*$", "", truncated)
        for tag in ("b", "i", "u", "s", "code", "pre", "a"):
            open_count = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", truncated))
            close_count = truncated.count(f"</{tag}>")
            truncated += f"</{tag}>" * max(0, open_count - close_count)
        return truncated + suffix

    @staticmethod
    def _smart_truncate(text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        truncated = text[:max_length]
        for sep in ("\n\n", "\n", ". ", " "):
            idx = truncated.rfind(sep)
            if idx > max_length * 0.7:
                return truncated[:idx]
        return truncated
