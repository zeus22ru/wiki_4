#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Извлечение текста из HTML для индексации с учётом зачёркнутого (устаревшего) контента."""

from __future__ import annotations

import re
from typing import List, Optional, Union

from bs4 import NavigableString, Tag

from config import settings

STRIKE_TAGS = frozenset({"del", "s", "strike"})
OBSOLETE_PREFIX = "[УСТАРЕЛО:"
OBSOLETE_SUFFIX = "]"
_LINE_THROUGH_RE = re.compile(r"line-through", re.IGNORECASE)


def normalize_strikethrough_mode(mode: Optional[str] = None) -> str:
    """Вернуть режим: mark | exclude | keep."""
    raw = (mode if mode is not None else getattr(settings, "STRIKETHROUGH_INDEX_MODE", "mark") or "mark")
    value = str(raw).strip().lower()
    if value in ("mark", "exclude", "keep"):
        return value
    return "mark"


def _has_line_through_style(tag: Tag) -> bool:
    style = tag.get("style")
    if not style:
        return False
    return bool(_LINE_THROUGH_RE.search(str(style)))


def _is_strike_element(tag: Tag) -> bool:
    name = (tag.name or "").lower()
    if name in STRIKE_TAGS:
        return True
    return _has_line_through_style(tag)


def _wrap_obsolete(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return ""
    return f"{OBSOLETE_PREFIX} {cleaned}{OBSOLETE_SUFFIX}"


def _collect_parts(node: Union[Tag, NavigableString], mode: str) -> List[str]:
    """Собрать фрагменты текста из узла DOM с учётом strike."""
    if isinstance(node, NavigableString):
        txt = str(node).strip()
        return [txt] if txt else []

    if not isinstance(node, Tag):
        return []

    if _is_strike_element(node):
        inner = re.sub(r"\s+", " ", node.get_text(separator=" ", strip=True)).strip()
        if not inner:
            return []
        if mode == "exclude":
            return []
        if mode == "mark":
            wrapped = _wrap_obsolete(inner)
            return [wrapped] if wrapped else []
        return [inner]

    parts: List[str] = []
    for child in node.children:
        parts.extend(_collect_parts(child, mode))
    return parts


def get_index_text(
    element: Union[Tag, NavigableString],
    mode: Optional[str] = None,
    separator: str = " ",
) -> str:
    """
    Извлечь текст из HTML-узла для индексации/чанкования.

    mode=mark (default): зачёркнутое → [УСТАРЕЛО: …]
    mode=exclude: зачёркнутое пропускается
    mode=keep: как BeautifulSoup get_text (без пометок)
    """
    resolved = normalize_strikethrough_mode(mode)
    if resolved == "keep":
        if isinstance(element, NavigableString):
            return str(element).strip()
        if isinstance(element, Tag):
            return element.get_text(separator=separator, strip=True)
        return ""

    parts = _collect_parts(element, resolved)
    text = separator.join(p for p in parts if p)
    text = re.sub(r"\s+", " ", text).strip()
    return text
