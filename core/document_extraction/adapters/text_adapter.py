#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Адаптер простого текста (.txt) и markdown-подобных файлов."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from ..base import ExtractionBlock, ExtractionResult, Locator, make_source_id, stable_hash

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


class TextSourceAdapter:
    name = "text"
    version = "1"
    extensions = (".txt", ".md", ".log")

    def extract(self, source: Any, *, options: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        path = Path(source)
        options = options or {}
        rel_path = str(options.get("relative_path") or path.name)
        source_id = make_source_id(rel_path)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            result = ExtractionResult(
                source_id=source_id, title=path.stem, source_type="text",
                source_path=rel_path, status="failed",
            )
            result.add_diagnostic("read_error", str(exc))
            return result

        title = path.stem
        blocks = []
        order = 0
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            m = _HEADING_RE.match(stripped)
            if m:
                blocks.append(ExtractionBlock(
                    block_id=f"b{order}", kind="heading", order=order,
                    text=m.group(2).strip(), section_path=m.group(2).strip(),
                    locator=Locator(block_order=order),
                ))
            else:
                blocks.append(ExtractionBlock(
                    block_id=f"b{order}", kind="paragraph", order=order,
                    text=re.sub(r"\s+", " ", stripped),
                    locator=Locator(block_order=order),
                ))
            order += 1

        status = "success" if blocks else "empty"
        revision = stable_hash(raw, length=32)
        return ExtractionResult(
            source_id=source_id, title=title, source_type="text",
            source_path=rel_path, source_revision=revision,
            blocks=blocks, status=status, adapter_version=self.version,
        )
