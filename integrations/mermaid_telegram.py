#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract Mermaid fenced blocks and render them to PNG via local mmdc."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

_MERMAID_FENCE_RE = re.compile(
    r"```mermaid[^\n]*\n([\s\S]*?)```",
    flags=re.IGNORECASE,
)
_MERMAID_INCOMPLETE_RE = re.compile(
    r"```mermaid\b[\s\S]*$",
    flags=re.IGNORECASE,
)
_TRIVIAL_MARKUP_RE = re.compile(r"^[\s*_#\-–—>`\"'~|.]+$", re.UNICODE)

RenderFn = Callable[[str, float], bytes]

_DEFAULT_BROWSER_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


@dataclass(frozen=True)
class MermaidBlock:
    """One fenced mermaid block and its span in the source text."""

    full_match: str
    code: str
    start: int
    end: int


@dataclass
class MermaidProcessResult:
    """Outgoing text (successful blocks stripped) and rendered PNG payloads."""

    text: str
    images: list[bytes] = field(default_factory=list)


def extract_mermaid_blocks(text: str) -> list[MermaidBlock]:
    """Find all ```mermaid fenced blocks in order."""
    if not text:
        return []
    blocks: list[MermaidBlock] = []
    for match in _MERMAID_FENCE_RE.finditer(text):
        blocks.append(
            MermaidBlock(
                full_match=match.group(0),
                code=match.group(1).strip("\n"),
                start=match.start(),
                end=match.end(),
            )
        )
    return blocks


def hide_mermaid_source(text: str, *, placeholder: str = "") -> str:
    """
    Remove Mermaid source from user-visible text.

    Complete fences are replaced with placeholder (default empty).
    Trailing incomplete ```mermaid (during streaming) is cut off.
    """
    if not text:
        return text or ""
    out = _MERMAID_FENCE_RE.sub(placeholder, text)
    out = _MERMAID_INCOMPLETE_RE.sub(placeholder, out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def is_trivial_display_text(text: str) -> bool:
    """True if text is empty or only leftover markdown punctuation (e.g. '**')."""
    raw = (text or "").strip()
    if not raw:
        return True
    if _TRIVIAL_MARKUP_RE.match(raw):
        return True
    stripped = re.sub(r"[*_`#~>\[\]\(\)]+", " ", raw)
    stripped = re.sub(r"\s+", " ", stripped).strip(" \t\n\r-–—|.")
    return not stripped


def resolve_mmdc_cmd(explicit: str | None = None, *, project_root: Path | None = None) -> str:
    """Prefer local node_modules/.bin/mmdc, else PATH / explicit command."""
    root = project_root or Path(__file__).resolve().parents[1]
    local_bin = root / "node_modules" / ".bin"
    for name in ("mmdc.cmd", "mmdc"):
        candidate = local_bin / name
        if candidate.is_file():
            return str(candidate)

    cmd = (explicit or "").strip() or "mmdc"
    # On Windows, bare "mmdc" often fails with CreateProcess; resolve to .cmd.
    which = shutil.which(cmd)
    if which:
        return which
    return cmd


def resolve_browser_executable(explicit: str | None = None) -> str | None:
    """Return a Chrome/Edge path for Puppeteer, or None."""
    if explicit and explicit.strip():
        path = Path(explicit.strip())
        if path.is_file():
            return str(path)
        logger.warning("TELEGRAM_PUPPETEER_EXECUTABLE_PATH not found: %s", explicit)

    env_path = (os.getenv("PUPPETEER_EXECUTABLE_PATH") or "").strip()
    if env_path and Path(env_path).is_file():
        return env_path

    local_app = os.getenv("LOCALAPPDATA") or ""
    candidates = list(_DEFAULT_BROWSER_CANDIDATES)
    if local_app:
        candidates.insert(
            0,
            str(Path(local_app) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        )
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def _write_puppeteer_config(path: Path, executable_path: str) -> None:
    payload = {
        "executablePath": executable_path,
        "args": ["--no-sandbox", "--disable-gpu"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def render_mermaid_png(
    code: str,
    *,
    mmdc_cmd: str,
    timeout: float = 30.0,
    browser_executable: str | None = None,
    puppeteer_config_path: str | None = None,
) -> bytes:
    """Render Mermaid source to PNG bytes via mmdc subprocess."""
    code = (code or "").strip()
    if not code:
        raise ValueError("empty mermaid code")

    with tempfile.TemporaryDirectory(prefix="wiki4_mmdc_") as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / "diagram.mmd"
        output_path = tmp_path / "diagram.png"
        input_path.write_text(code + "\n", encoding="utf-8")
        cmd = [
            mmdc_cmd,
            "-i",
            str(input_path),
            "-o",
            str(output_path),
            "-b",
            "white",
        ]

        config_file: Path | None = None
        if puppeteer_config_path and Path(puppeteer_config_path).is_file():
            config_file = Path(puppeteer_config_path)
        else:
            browser = resolve_browser_executable(browser_executable)
            if browser:
                config_file = tmp_path / "puppeteer.json"
                _write_puppeteer_config(config_file, browser)
            else:
                logger.warning(
                    "No Chrome/Edge found for mmdc; render may fail. "
                    "Set TELEGRAM_PUPPETEER_EXECUTABLE_PATH or install Chrome."
                )
        if config_file is not None:
            cmd.extend(["-p", str(config_file)])

        use_shell = os.name == "nt" and str(mmdc_cmd).lower().endswith((".cmd", ".bat"))
        completed = subprocess.run(
            subprocess.list2cmdline(cmd) if use_shell else cmd,
            capture_output=True,
            timeout=timeout,
            shell=use_shell,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
            stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
            detail = (stderr or stdout or "unknown mmdc error").strip()
            raise RuntimeError(f"mmdc failed ({completed.returncode}): {detail[:800]}")
        if not output_path.is_file():
            raise RuntimeError("mmdc completed but PNG was not created")
        data = output_path.read_bytes()
        if not data:
            raise RuntimeError("mmdc produced an empty PNG")
        return data


def process_answer_mermaid(
    text: str,
    *,
    enabled: bool = True,
    max_diagrams: int = 5,
    mmdc_cmd: str | None = None,
    timeout: float = 30.0,
    browser_executable: str | None = None,
    puppeteer_config_path: str | None = None,
    render_fn: RenderFn | None = None,
    project_root: Path | None = None,
) -> MermaidProcessResult:
    """
    Render up to max_diagrams mermaid fences to PNG.

    Mermaid source is never returned in text when enabled: fences are always
    stripped. Failed renders log an error and may append a short warning.
    """
    source = text or ""
    if not enabled:
        return MermaidProcessResult(text=source)

    blocks = extract_mermaid_blocks(source)
    if not blocks:
        return MermaidProcessResult(text=hide_mermaid_source(source))

    cmd = resolve_mmdc_cmd(mmdc_cmd, project_root=project_root)
    logger.info(
        "Rendering %s Mermaid block(s) via mmdc=%s",
        min(len(blocks), max_diagrams),
        cmd,
    )

    def _default_render(code: str, to: float) -> bytes:
        return render_mermaid_png(
            code,
            mmdc_cmd=cmd,
            timeout=to,
            browser_executable=browser_executable,
            puppeteer_config_path=puppeteer_config_path,
        )

    renderer: RenderFn = render_fn or _default_render

    images: list[bytes] = []
    attempted = 0
    failed = 0

    for index, block in enumerate(blocks):
        if index >= max_diagrams:
            logger.info(
                "Mermaid diagram %s skipped (max %s per message)",
                index + 1,
                max_diagrams,
            )
            failed += len(blocks) - index
            break
        attempted += 1
        try:
            png = renderer(block.code, float(timeout))
        except Exception:
            logger.exception("Failed to render Mermaid block %s", index + 1)
            failed += 1
            continue
        images.append(png)

    out = hide_mermaid_source(source)
    if failed and not images:
        note = "⚠️ Не удалось отрисовать схему."
        out = f"{out}\n\n{note}".strip() if out and not is_trivial_display_text(out) else note
    elif failed:
        base = "" if is_trivial_display_text(out) else out
        out = f"{base}\n\n⚠️ Часть схем не удалось отрисовать.".strip()
    elif is_trivial_display_text(out):
        # Photo-only answers ("только схема"): no leftover "**" / empty markup.
        out = ""
    return MermaidProcessResult(text=out, images=images)


def send_mermaid_photos(
    client: object,
    chat_id: int,
    images: Sequence[bytes],
) -> None:
    """Send rendered PNGs via TelegramClient.send_photo; ignore per-photo errors."""
    send_photo = getattr(client, "send_photo", None)
    if not callable(send_photo) or not images:
        return
    for i, png in enumerate(images, start=1):
        try:
            send_photo(chat_id, png, filename=f"diagram_{i}.png")
        except Exception:
            logger.exception("Failed to send Mermaid photo %s", i)
