#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Адаптер самостоятельных изображений (ТЗ §9.7).

Изображение — самостоятельный источник даже при нулевом OCR-тексте. TIFF
раскладывается на кадры-страницы, GIF сохраняет выбранные кадры, SVG
сохраняется как оригинал (в растр его переводит рендерер перед OCR/vision).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import (
    ExtractionBlock,
    ExtractionResult,
    Locator,
    VisualOccurrence,
    make_occurrence_id,
    make_source_id,
    stable_hash,
)
from ..imaging import RASTER_EXTENSIONS, detect_mime_from_bytes, probe_image_size

try:  # pragma: no cover
    from PIL import Image, ImageSequence

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageSequence = None  # type: ignore
    PIL_AVAILABLE = False


class ImageSourceAdapter:
    name = "image"
    version = "1"
    extensions = RASTER_EXTENSIONS + (".svg",)

    #: Лимит кадров GIF/многостраничного изображения.
    max_frames = 12

    def extract(self, source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        path = Path(source)
        options = options or {}
        rel_path = str(options.get("relative_path") or path.name)
        source_id = make_source_id(rel_path)
        result = ExtractionResult(
            source_id=source_id, title=path.stem, source_type="image",
            source_path=rel_path, adapter_version=self.version,
        )
        try:
            data = path.read_bytes()
        except OSError as exc:
            result.status = "failed"
            result.add_diagnostic("read_error", str(exc))
            return result

        mime = detect_mime_from_bytes(data, path.suffix)
        if mime == "image/svg+xml":
            return self._extract_svg(data, path, source_id, rel_path, result)

        occurrences: List[VisualOccurrence] = []
        revision = stable_hash(data, length=32)
        frames = self._split_frames(data, path.suffix.lower())
        if not frames:
            frames = [(data, None)]  # не смогли декодировать — отдаём как есть
            result.add_diagnostic("decode_failed", "Не удалось декодировать кадры изображения")

        for idx, (frame_bytes, frame_index) in enumerate(frames):
            w, h = probe_image_size(frame_bytes)
            loc = Locator(page=frame_index + 1 if frame_index is not None else 1,
                          block_order=idx)
            occ = VisualOccurrence(
                occurrence_id="", source_id=source_id, locator=loc,
                image_bytes=frame_bytes, mime_type=detect_mime_from_bytes(frame_bytes, path.suffix),
                width=w, height=h, visual_type="unknown",
                extraction_quality="native",
            )
            occurrences.append(occ)
            result.blocks.append(ExtractionBlock(
                block_id=f"b{idx}", kind="visual", order=idx, section_path=path.stem,
                locator=loc,
            ))

        for occ in occurrences:
            occ.occurrence_id = make_occurrence_id(source_id, revision, occ.locator.key())
        result.visual_occurrences = occurrences
        result.source_revision = revision
        result.status = "success"
        result.metadata["frame_count"] = len(frames)
        return result

    def _extract_svg(
        self, data: bytes, path: Path, source_id: str, rel_path: str, result: ExtractionResult,
    ) -> ExtractionResult:
        revision = stable_hash(data, length=32)
        occ = VisualOccurrence(
            occurrence_id="", source_id=source_id,
            locator=Locator(page=1, block_order=0, coordinate_space="normalized"),
            image_bytes=data, mime_type="image/svg+xml", visual_type="illustration",
            extraction_quality="native",
        )
        occ.occurrence_id = make_occurrence_id(source_id, revision, occ.locator.key())
        result.visual_occurrences = [occ]
        result.blocks = [ExtractionBlock(block_id="b0", kind="visual", order=0,
                                         section_path=path.stem, locator=occ.locator)]
        result.source_revision = revision
        result.status = "success"
        return result

    def _split_frames(self, data: bytes, suffix: str) -> List[tuple]:
        """Вернуть список (bytes, frame_index). Многостраничный TIFF и GIF разбиваются."""
        if not PIL_AVAILABLE:
            return [(data, None)]
        try:
            with Image.open(io_bytes(data)) as img:
                n_frames = int(getattr(img, "n_frames", 1))
                if n_frames <= 1:
                    return [(data, None)]
                out: List[tuple] = []
                limit = min(n_frames, self.max_frames)
                for i in range(limit):
                    try:
                        img.seek(i)
                        buf = io.BytesIO()
                        img.convert("RGB").save(buf, format="PNG")
                        out.append((buf.getvalue(), i))
                    except Exception:
                        continue
                return out or [(data, None)]
        except Exception:
            return [(data, None)]


def io_bytes(data: bytes):
    import io

    return io.BytesIO(data)
