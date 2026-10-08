#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portable-конвертация офисных документов через LibreOffice (ТЗ §9.6).

Не требует установленного Microsoft Office и COM Automation. Работает с копией
исходника в изолированном временном профиле, ограничивает время и выходной
размер, отключает макросы и обновление внешних ссылок (по возможности).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple


class OfficeRendererError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class OfficeRenderer:
    """Обёртка над portable soffice.exe."""

    def __init__(
        self,
        executable: Optional[str] = None,
        *,
        timeout_sec: int = 180,
        max_output_bytes: int = 200 * 1024 * 1024,
    ) -> None:
        self.executable = executable or os.getenv("OFFICE_RENDERER_PATH", "")
        self.timeout_sec = int(timeout_sec)
        self.max_output_bytes = int(max_output_bytes)

    def available(self) -> bool:
        return bool(self.executable) and Path(self.executable).is_file()

    def convert(
        self,
        source: Path,
        target_ext: str,
        *,
        out_dir: Optional[Path] = None,
        timeout_sec: Optional[int] = None,
    ) -> Path:
        """Сконвертировать копию документа в ``target_ext`` (например ``docx``/``pdf``)."""
        if not self.available():
            raise OfficeRendererError("renderer_unavailable", "LibreOffice portable не найден")
        target_ext = target_ext.lstrip(".").lower()
        timeout = int(timeout_sec or self.timeout_sec)
        work_root = Path(out_dir or tempfile.mkdtemp(prefix="kb_office_"))
        work_root.mkdir(parents=True, exist_ok=True)
        profile_dir = work_root / "_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        copy_path = work_root / ("source" + source.suffix)
        shutil.copy2(source, copy_path)

        cmd = [
            self.executable,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--nolockcheck",
            "--nodefault",
            "--norestore",
            f"-env:UserInstallation=file:///{profile_dir.as_posix()}",
            "--convert-to",
            target_ext,
            "--outdir",
            str(work_root),
            str(copy_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OfficeRendererError("renderer_timeout", f"Превышено время конвертации: {exc}") from exc
        except OSError as exc:
            raise OfficeRendererError("renderer_unavailable", str(exc)) from exc

        output = work_root / (copy_path.stem + "." + target_ext)
        if not output.is_file():
            raise OfficeRendererError(
                "renderer_failed",
                f"Конвертация не дала результат (rc={proc.returncode})",
            )
        if output.stat().st_size > self.max_output_bytes:
            raise OfficeRendererError("renderer_output_too_large", "Результат конвертации слишком большой")
        return output


def render_to_png(
    renderer: OfficeRenderer,
    source: Path,
    *,
    page: Optional[int] = None,
    dpi: int = 150,
) -> List[Path]:
    """Сконвертировать документ в PDF и (опционально) отрендерить страницы в PNG.

    Возвращает список PNG-файлов. PDF-рендеринг выполняется через pypdfium2.
    """
    pdf_path = renderer.convert(source, "pdf")
    try:
        import pypdfium2 as pdfium
    except Exception:
        return []
    doc = pdfium.PdfDocument(str(pdf_path))
    pages = range(len(doc)) if page is None else [page - 1]
    out_paths: List[Path] = []
    for idx in pages:
        try:
            bitmap = doc[idx].render(scale=dpi / 72.0)
            img = bitmap.to_pil()
            png_path = pdf_path.with_name(f"{pdf_path.stem}_p{idx + 1}.png")
            img.save(png_path, format="PNG")
            out_paths.append(png_path)
        except Exception:
            continue
    return out_paths
