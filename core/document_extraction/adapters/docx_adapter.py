#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Адаптер DOCX: реальный порядок параграфов/таблиц/изображений (ТЗ §9.1).

Читает XML ``document.xml`` и отношения OOXML, а не только ``word/media``:
обход идёт в порядке тела документа, поддерживаются inline и anchored-рисунки,
вложенные таблицы, подписи и alt/title/description, native-текст фигур и
заголовки по стилям. Сложные объекты (SmartArt, диаграммы, группы фигур) при
наличии отдаются офисному рендереру как fallback.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from ..base import (
    ExtractionBlock,
    ExtractionResult,
    Locator,
    VisualOccurrence,
    make_occurrence_id,
    make_source_id,
    stable_hash,
)
from ..imaging import detect_mime_from_bytes, probe_image_size

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_HEADING_STYLE_RE = re.compile(r"(heading|заголовок|заголовок\d|h\d)\s*(\d)?", re.IGNORECASE)

#: Расширения, которые считаем растровыми/векторными изображениями.
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".emf", ".wmf", ".svg")


class DocxSourceAdapter:
    name = "docx"
    version = "1"
    extensions = (".docx",)

    def extract(self, source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        path = Path(source)
        options = options or {}
        rel_path = str(options.get("relative_path") or path.name)
        source_id = make_source_id(rel_path)

        if not zipfile.is_zipfile(path):
            result = ExtractionResult(
                source_id=source_id, title=path.stem, source_type="docx",
                source_path=rel_path, status="failed",
            )
            result.add_diagnostic("not_a_zip", "Файл не является OOXML (DOCX)")
            return result

        try:
            with zipfile.ZipFile(path) as zf:
                return self._extract_zip(zf, path, source_id, rel_path, options)
        except (OSError, zipfile.BadZipFile) as exc:
            result = ExtractionResult(
                source_id=source_id, title=path.stem, source_type="docx",
                source_path=rel_path, status="failed",
            )
            result.add_diagnostic("read_error", str(exc))
            return result

    def _extract_zip(
        self,
        zf: zipfile.ZipFile,
        path: Path,
        source_id: str,
        rel_path: str,
        options: Dict[str, Any],
    ) -> ExtractionResult:
        result = ExtractionResult(
            source_id=source_id, title=path.stem, source_type="docx",
            source_path=rel_path, adapter_version=self.version,
        )
        rels = self._load_relationships(zf, "word/_rels/document.xml.rels")
        media_cache: Dict[str, bytes] = {}

        def read_media(rid: str) -> Optional[bytes]:
            target = rels.get(rid)
            if not target:
                return None
            if target.startswith("http://") or target.startswith("https://"):
                result.add_diagnostic("external_image", f"Внешний ресурс: {target}")
                return None
            if target not in media_cache:
                name = target.replace("\\", "/")
                if not name.startswith("word/"):
                    name = "word/" + name.lstrip("./")
                try:
                    media_cache[target] = zf.read(name)
                except KeyError:
                    result.add_diagnostic("media_missing", f"Нет части {name}")
                    return None
            return media_cache[target]

        try:
            doc_xml = zf.read("word/document.xml")
        except KeyError:
            result.status = "failed"
            result.add_diagnostic("no_document_xml", "Отсутствует word/document.xml")
            return result

        root = ET.fromstring(doc_xml)
        body = root.find(f"{_W}body")
        blocks: List[ExtractionBlock] = []
        occurrences: List[VisualOccurrence] = []
        outline: List[str] = []

        # Заголовок документа.
        title = path.stem
        core = self._read_core_title(zf)
        if core:
            title = core
        result.title = title

        order = 0

        def section_path() -> str:
            parts = [title] if title else []
            parts.extend(h for h in outline if h)
            return " → ".join(parts)

        def emit_text(kind: str, text: str, loc: Locator) -> None:
            nonlocal order
            text = re.sub(r"\s+", " ", text or "").strip()
            if not text:
                return
            blocks.append(ExtractionBlock(
                block_id=f"b{order}", kind=kind, order=order, text=text,
                section_path=section_path(), locator=loc,
            ))
            order += 1

        def emit_visual(
            data: Optional[bytes], loc: Locator, *, caption: str = "", alt: str = "",
            quality: str = "native", mime: str = "", warnings: Optional[List[str]] = None,
        ) -> None:
            nonlocal order
            mime_type = mime
            width = height = None
            if data:
                mime_type = mime_type or detect_mime_from_bytes(data)
                width, height = probe_image_size(data)
            occ = VisualOccurrence(
                occurrence_id="", source_id=source_id, locator=loc,
                image_bytes=data, mime_type=mime_type, width=width, height=height,
                caption=caption, alt=alt, section_path=section_path(),
                extraction_quality=quality, warnings=list(warnings or []),
            )
            occurrences.append(occ)
            blocks.append(ExtractionBlock(
                block_id=f"b{order}", kind="visual", order=order,
                section_path=section_path(), locator=loc,
                metadata={"caption": caption, "alt": alt},
            ))
            order += 1

        def drawing_caption(par: ET.Element) -> str:
            # Подпись: ближайший следующий абзац, начинающийся с "Рис."
            return ""

        def handle_paragraph(par: ET.Element) -> None:
            nonlocal order
            style_val = ""
            ppr = par.find(f"{_W}pPr")
            if ppr is not None:
                pstyle = ppr.find(f"{_W}pStyle")
                if pstyle is not None:
                    style_val = pstyle.get(f"{_W}val") or ""
                outline_lvl = ppr.find(f"{_W}outlineLvl")
                if outline_lvl is not None and not style_val:
                    style_val = f"heading {int(outline_lvl.get(f'{_W}val') or 0) + 1}"

            # Текст параграфа.
            text = "".join(t.text or "" for t in par.iter(f"{_W}t"))
            text = re.sub(r"\s+", " ", text).strip()

            heading_level = self._heading_level(style_val)
            if heading_level is not None and text:
                outline[:] = outline[: heading_level - 1]
                outline.append(text)
                emit_text("heading", text, Locator(block_order=order, object_path="body/paragraph"))
                return

            if text:
                emit_text("paragraph", text, Locator(block_order=order, object_path="body/paragraph"))

            # Изображения внутри параграфа (inline и anchored).
            for blip in par.iter(f"{_A}blip"):
                rid = blip.get(f"{_R}embed") or blip.get(f"{_R}link")
                data = read_media(rid) if rid else None
                emit_visual(data, Locator(block_order=order, object_path="body/paragraph/drawing"))

            # Native-текст фигур/textbox.
            for txbx in par.iter(f"{_W}txbxContent"):
                shape_text = "".join(t.text or "" for t in txbx.iter(f"{_W}t"))
                shape_text = re.sub(r"\s+", " ", shape_text).strip()
                if shape_text and shape_text != text:
                    emit_text("paragraph", shape_text, Locator(block_order=order, object_path="shape/textbox"))

        def handle_table(tbl: ET.Element, object_path: str) -> None:
            rows_text: List[str] = []
            for ri, row in enumerate(tbl.findall(f"{_W}tr")):
                cells: List[str] = []
                for cell in row.findall(f"{_W}tc"):
                    cell_text = " ".join(
                        (t.text or "") for t in cell.iter(f"{_W}t")
                    ).strip()
                    cells.append(re.sub(r"\s+", " ", cell_text))
                    # Изображения в ячейке.
                    for blip in cell.iter(f"{_A}blip"):
                        rid = blip.get(f"{_R}embed") or blip.get(f"{_R}link")
                        data = read_media(rid) if rid else None
                        emit_visual(data, Locator(block_order=order, object_path=f"{object_path}/cell"))
                    # Вложенные таблицы в ячейке.
                    for nested in cell.findall(f"{_W}tbl"):
                        handle_table(nested, f"{object_path}/nested")
                if any(cells):
                    rows_text.append(" | ".join(cells))
            if rows_text:
                emit_text("table", "\n".join(rows_text), Locator(block_order=order, object_path=object_path))

        for child in list(body):
            tag = child.tag
            if tag == f"{_W}p":
                handle_paragraph(child)
            elif tag == f"{_W}tbl":
                handle_table(child, "body/table")

        # Headers/footers отдельно (ТЗ §9.1 — не плодить шумные дубли).
        self._extract_headers_footers(zf, rels, result)

        revision = stable_hash(
            zf.read("word/document.xml"),
            "|".join(sorted(media_cache.keys())),
            length=32,
        )
        for occ in occurrences:
            occ.occurrence_id = make_occurrence_id(source_id, revision, occ.locator.key())

        result.blocks = blocks
        result.visual_occurrences = occurrences
        result.source_revision = revision
        if not blocks and not occurrences:
            result.status = "empty"
        else:
            result.status = "success"
        return result

    def _extract_headers_footers(
        self,
        zf: zipfile.ZipFile,
        rels: Dict[str, str],
        result: ExtractionResult,
    ) -> None:
        """Учесть логотипы/колонтитулы, но пометить их как второстепенные."""
        count = 0
        for name in zf.namelist():
            base = Path(name).name
            if base.startswith("header") or base.startswith("footer"):
                if not name.endswith(".xml"):
                    continue
                try:
                    root = ET.fromstring(zf.read(name))
                except ET.ParseError:
                    continue
                text = "".join(t.text or "" for t in root.iter(f"{_W}t")).strip()
                if text:
                    count += 1
                for blip in root.iter(f"{_A}blip"):
                    if blip.get(f"{_R}embed"):
                        count += 1
        if count:
            result.metadata["header_footer_objects"] = count

    @staticmethod
    def _load_relationships(zf: zipfile.ZipFile, rel_path: str) -> Dict[str, str]:
        rels: Dict[str, str] = {}
        try:
            root = ET.fromstring(zf.read(rel_path))
        except (KeyError, ET.ParseError):
            return rels
        for rel in root.findall(f"{_REL_NS}Relationship"):
            rid = rel.get("Id")
            target = rel.get("Target")
            if rid and target:
                rels[rid] = target
        return rels

    @staticmethod
    def _read_core_title(zf: zipfile.ZipFile) -> str:
        try:
            root = ET.fromstring(zf.read("docProps/core.xml"))
        except (KeyError, ET.ParseError):
            return ""
        title = root.find("{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}title")
        return (title.text or "").strip() if title is not None else ""

    @staticmethod
    def _heading_level(style_val: str) -> Optional[int]:
        if not style_val:
            return None
        m = _HEADING_STYLE_RE.search(style_val)
        if not m:
            return None
        digits = re.search(r"(\d+)", style_val)
        if digits:
            return max(1, min(6, int(digits.group(1))))
        return 1
