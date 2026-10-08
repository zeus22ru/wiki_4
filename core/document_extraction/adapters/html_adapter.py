#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Адаптер HTML/XWiki: DOM-порядок текст → картинка → подпись, плюс локальные ресурсы.

Сохраняет порядок блоков, подписи ``figure/figcaption``, alt, lazy-load и
связывает изображения с контекстом шага. Учитывает зачёркнутый (устаревший) текст
через :mod:`core.html_text`. Скачивание сетевых ресурсов выполняет отдельный
контролируемый экспортёр (см. ТЗ §10), здесь — только локальные/инлайн.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from ..base import (
    ExtractionBlock,
    ExtractionResult,
    Locator,
    VisualOccurrence,
    make_occurrence_id,
    make_source_id,
    stable_hash,
)
from ..imaging import detect_mime_from_bytes, is_svg, probe_image_size

_LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-url", "data-image")
_STRIKE_TAGS = frozenset({"del", "s", "strike"})
_LINE_THROUGH_RE = re.compile(r"line-through", re.IGNORECASE)
_INLINE_DATA_RE = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<data>.+)$", re.IGNORECASE | re.DOTALL)


class HtmlSourceAdapter:
    name = "html"
    version = "1"
    extensions = (".html", ".htm")

    #: Максимальный размер инлайн data-изображения (байты содержимого).
    max_inline_bytes = 8 * 1024 * 1024

    def extract(self, source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        path = Path(source)
        options = options or {}
        rel_path = str(options.get("relative_path") or path.name)
        source_id = make_source_id(rel_path)
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            result = ExtractionResult(
                source_id=source_id, title=path.stem, source_type="html",
                source_path=rel_path, status="failed",
            )
            result.add_diagnostic("read_error", str(exc))
            return result
        return self.extract_from_html(
            html, source_id=source_id, title=path.stem, source_path=rel_path,
            base_dir=path.parent, options=options,
        )

    def extract_from_html(
        self,
        html: str,
        *,
        source_id: str,
        title: str,
        source_path: str,
        base_dir: Optional[Path] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        options = options or {}
        allow_local = bool(options.get("allow_local_resources", True))
        soup = BeautifulSoup(html, "html.parser")

        page_title = title
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            page_title = title_tag.get_text(strip=True)
        for junk in soup(["script", "style", "nav", "footer"]):
            junk.decompose()

        root = soup.find("article") or soup.find(id="xwikicontent") or soup.body or soup

        result = ExtractionResult(
            source_id=source_id, title=page_title, source_type="html",
            source_path=source_path, adapter_version=self.version,
        )
        blocks: List[ExtractionBlock] = []
        occurrences: List[VisualOccurrence] = []
        outline: List[str] = []
        order = 0
        incomplete = False

        def section_path() -> str:
            parts = [page_title] if page_title else []
            parts.extend(h for h in outline if h)
            return " → ".join(parts)

        def add_text(kind: str, text: str, locator: Locator, *, stale: bool = False) -> None:
            nonlocal order
            text = re.sub(r"\s+", " ", text or "").strip()
            if not text:
                return
            if stale:
                text = f"[УСТАРЕЛО: {text}]"
            blocks.append(ExtractionBlock(
                block_id=f"b{order}", kind=kind, order=order, text=text,
                section_path=section_path(), locator=locator,
            ))
            order += 1

        def is_stale_tag(tag: Tag) -> bool:
            for parent in [tag, *tag.parents]:
                if getattr(parent, "name", None) in _STRIKE_TAGS:
                    return True
                style = parent.get("style") if hasattr(parent, "get") else None
                if style and _LINE_THROUGH_RE.search(str(style)):
                    return True
            return False

        def img_src(tag: Tag) -> Optional[str]:
            for attr in ("src",) + _LAZY_ATTRS:
                value = tag.get(attr)
                if value and str(value).strip():
                    return str(value).strip()
            srcset = tag.get("srcset") or tag.get("data-srcset")
            if srcset:
                first = str(srcset).split(",")[0].strip().split(" ")[0]
                if first:
                    return first
            return None

        def resolve_local(src: str) -> Optional[bytes]:
            if src.startswith("data:"):
                m = _INLINE_DATA_RE.match(src)
                if not m:
                    return None
                data = base64.b64decode(m.group("data"), validate=False)
                if len(data) > self.max_inline_bytes:
                    result.add_diagnostic("asset_too_large", f"Инлайн-картинка {len(data)} байт")
                    return None
                return data
            parsed = urlparse(src)
            if parsed.scheme in ("http", "https") or src.startswith("//"):
                return None  # сетевые ресурсы — задача экспортёра
            if not allow_local or base_dir is None:
                return None
            local = (base_dir / unquote(parsed.path)).resolve()
            try:
                local.relative_to(base_dir.resolve())
            except ValueError:
                result.add_diagnostic("asset_outside_root", f"Ресурс вне каталога: {src}")
                return None
            if not local.is_file():
                return None
            try:
                return local.read_bytes()
            except OSError:
                return None

        def emit_visual(tag: Tag, src: Optional[str], caption: str, alt: str, loc: Locator) -> None:
            nonlocal order, incomplete
            stale = is_stale_tag(tag)
            data: Optional[bytes] = None
            mime = ""
            if src:
                data = resolve_local(src)
                if data:
                    mime = detect_mime_from_bytes(data, Path(urlparse(src).path).suffix)
                elif not src.startswith("data:"):
                    parsed = urlparse(src)
                    if parsed.scheme in ("http", "https") or src.startswith("//"):
                        incomplete = True  # не скачиваем сеть здесь
                    else:
                        result.add_diagnostic("asset_missing", f"Не найден локальный ресурс: {src}")
                        incomplete = True
            occ_asset_id = None
            width = height = None
            if data:
                width, height = probe_image_size(data)
            occ = VisualOccurrence(
                occurrence_id="",  # заполним после ревизии
                source_id=source_id,
                locator=loc,
                image_bytes=data,
                asset_id=occ_asset_id,
                mime_type=mime,
                width=width, height=height,
                caption=caption, alt=alt,
                visual_type="unknown",
                context_before="", context_after="",
                section_path=section_path(),
                is_stale=stale,
                extraction_quality="native",
            )
            if data and is_svg(data, mime):
                occ.mime_type = "image/svg+xml"
            occurrences.append(occ)
            block = ExtractionBlock(
                block_id=f"b{order}", kind="visual", order=order, text="",
                section_path=section_path(), locator=loc,
                metadata={"caption": caption, "alt": alt, "stale": stale},
            )
            blocks.append(block)
            order += 1

        def walk(parent: Tag) -> None:
            nonlocal outline, order
            for child in parent.children:
                if isinstance(child, NavigableString):
                    txt = str(child).strip()
                    if txt and len(txt) > 0:
                        add_text("paragraph", txt, Locator(block_order=order),
                                 stale=is_stale_tag(parent))
                    continue
                if not isinstance(child, Tag):
                    continue
                name = child.name.lower()
                if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    level = int(name[1])
                    title_text = child.get_text(separator=" ", strip=True)
                    outline = outline[: level - 1]
                    if title_text:
                        outline.append(title_text)
                        add_text("heading", title_text, Locator(block_order=order))
                    continue
                if name in ("ul", "ol"):
                    for li in child.find_all("li", recursive=False):
                        add_text("paragraph", f"• {li.get_text(separator=' ', strip=True)}",
                                 Locator(block_order=order), stale=is_stale_tag(li))
                    continue
                if name in ("table",):
                    text = _table_to_text(child)
                    add_text("table", text, Locator(block_order=order), stale=is_stale_tag(child))
                    continue
                if name == "figure":
                    figcaption = child.find("figcaption")
                    caption = figcaption.get_text(separator=" ", strip=True) if figcaption else ""
                    for img in child.find_all("img"):
                        emit_visual(img, img_src(img), caption, str(img.get("alt") or ""),
                                    Locator(block_order=order))
                    # текст внутри figure без картинок
                    for p in child.find_all("p"):
                        add_text("paragraph", p.get_text(separator=" ", strip=True),
                                 Locator(block_order=order), stale=is_stale_tag(p))
                    continue
                if name == "picture":
                    imgs = child.find_all("img")
                    if imgs:
                        img = imgs[0]
                        emit_visual(img, img_src(img), "", str(img.get("alt") or ""),
                                    Locator(block_order=order))
                    continue
                if name == "img":
                    emit_visual(child, img_src(child), "", str(child.get("alt") or ""),
                                Locator(block_order=order))
                    continue
                if name == "svg":
                    raw = str(child).encode("utf-8")
                    occ = VisualOccurrence(
                        occurrence_id="", source_id=source_id,
                        locator=Locator(block_order=order), image_bytes=raw,
                        mime_type="image/svg+xml",
                        visual_type="illustration", section_path=section_path(),
                        is_stale=is_stale_tag(child), extraction_quality="native",
                    )
                    w, h = probe_image_size(raw)
                    occ.width, occ.height = w, h
                    occurrences.append(occ)
                    blocks.append(ExtractionBlock(
                        block_id=f"b{order}", kind="visual", order=order,
                        section_path=section_path(), locator=Locator(block_order=order),
                    ))
                    order += 1
                    continue
                if name == "pre":
                    add_text("paragraph", child.get_text(), Locator(block_order=order),
                             stale=is_stale_tag(child))
                    continue
                walk(child)

        walk(root)

        # Текст перед/после картинок — ближайший контекст.
        self._fill_context(blocks, occurrences)

        revision = stable_hash(html, length=32)
        # Финализируем occurrence_id с учётом ревизии.
        for occ in occurrences:
            occ.occurrence_id = make_occurrence_id(source_id, revision, occ.locator.key())

        result.blocks = blocks
        result.visual_occurrences = occurrences
        result.source_revision = revision
        if not blocks and not occurrences:
            result.status = "empty"
        elif incomplete:
            result.status = "partial"
        else:
            result.status = "success"
        return result

    @staticmethod
    def _fill_context(blocks: List[ExtractionBlock], occurrences: List[VisualOccurrence]) -> None:
        text_by_order = {b.order: b for b in blocks}
        for occ in occurrences:
            bo = occ.locator.block_order or 0
            prev_text = ""
            for o in range(bo - 1, -1, -1):
                b = text_by_order.get(o)
                if b and b.text:
                    prev_text = b.text
                    break
            next_text = ""
            for o in range(bo + 1, bo + 50):
                b = text_by_order.get(o)
                if b and b.text:
                    next_text = b.text
                    break
            occ.context_before = prev_text[:500]
            occ.context_after = next_text[:500]

    def extract_from_url(self, url: str, html: str, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        """Извлечь из уже скачанного HTML с известным URL страницы."""
        source_id = make_source_id(url, prefix="xwiki")
        result = self.extract_from_html(
            html, source_id=source_id, title=url, source_path=url,
            base_dir=None, options=options,
        )
        result.source_url = url
        result.source_type = "xwiki"
        return result


def _table_to_text(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)
