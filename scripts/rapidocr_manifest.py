#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Генерация runtime_manifest.json для portable-комплекта RapidOCR-json (ТЗ §8.1, §24.3).

Считает SHA-256 архива и всех файлов комплекта (EXE, DLL, ONNX-модели, словари,
лицензии), фиксирует версию движка и активные языковые профили. Манифест не
содержит секретов и предназначен для проверки целостности portable-сборки.

Запуск (PowerShell):
    .\.venv\Scripts\python.exe scripts/rapidocr_manifest.py --install .tools/rapidocr-json/0.2.0 --archive .tools/rapidocr-json/_download/RapidOCR-json_v0.2.0.7z --version 0.2.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Профиль → файлы моделей (синхронизировано с core/ocr.py PROFILE_MODELS).
PROFILES = {
    "cyrillic": ["ch_PP-OCRv3_det_infer.onnx", "ch_ppocr_mobile_v2.0_cls_infer.onnx",
                 "rec_cyrillic_PP-OCRv3_infer.onnx", "dict_cyrillic.txt"],
    "english": ["ch_PP-OCRv3_det_infer.onnx", "ch_ppocr_mobile_v2.0_cls_infer.onnx",
                "rec_en_PP-OCRv3_infer.onnx", "dict_en.txt"],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _license_like(name: str) -> bool:
    low = name.lower()
    return any(token in low for token in ("license", "licence", "copying", "notice", "lgpl", "mit"))


def detect_runtime_version(install: Path, executable: str, *, timeout: float = 5.0) -> str:
    """Версия, которую сообщает сам EXE в стартовом баннере (например, 1.1.0)."""
    import re
    import subprocess

    exe = install / executable
    if not exe.is_file():
        return ""
    try:
        proc = subprocess.Popen(
            [str(exe)], cwd=str(install), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return ""
    banner = ""
    try:
        proc.stdin.close()  # type: ignore[union-attr]
    except Exception:
        pass
    try:
        import threading

        holder: Dict[str, str] = {}

        def _read() -> None:
            try:
                holder["line"] = proc.stdout.readline()  # type: ignore[union-attr]
            except Exception:
                holder["line"] = ""

        thread = threading.Thread(target=_read, daemon=True)
        thread.start()
        thread.join(timeout)
        banner = holder.get("line", "")
    finally:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass
    match = re.search(r"v(\d+\.\d+\.\d+)", banner)
    return match.group(1) if match else ""


def build_manifest(install: Path, *, archive: Path | None, version: str,
                   executable: str, profiles: List[str],
                   runtime_version: str = "") -> Dict[str, Any]:
    files: Dict[str, str] = {}
    licenses: List[str] = []
    for path in sorted(install.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(install).as_posix()
        files[rel] = sha256_file(path)
        if _license_like(path.name):
            licenses.append(rel)

    manifest: Dict[str, Any] = {
        "engine": "rapidocr-json",
        "release_version": version,
        "runtime_version": runtime_version or version,
        "platform": "windows-x64",
        "installed_path": install.as_posix(),
        "executable": executable,
        "active_profiles": profiles,
        "profiles": {name: PROFILES[name] for name in profiles if name in PROFILES},
        "files": files,
        "licenses": licenses,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if archive and archive.is_file():
        manifest["archive_url"] = (
            "https://github.com/hiroi-sora/RapidOCR-json/releases/download/"
            f"v{version}/RapidOCR-json_v{version}.7z"
        )
        manifest["archive_sha256"] = sha256_file(archive)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Сгенерировать runtime_manifest.json")
    parser.add_argument("--install", type=Path, required=True, help="Каталог комплекта")
    parser.add_argument("--archive", type=Path, default=None, help="Файл архива выпуска")
    parser.add_argument("--version", default="0.2.0", help="Версия выпуска (тег релиза)")
    parser.add_argument("--runtime-version", default="", help="Версия, которую сообщает сам EXE")
    parser.add_argument("--executable", default="RapidOCR-json.exe")
    parser.add_argument("--profiles", default="cyrillic,english")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not args.install.is_dir():
        raise SystemExit(f"Каталог не найден: {args.install}")

    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    runtime_version = args.runtime_version or detect_runtime_version(args.install, args.executable)
    manifest = build_manifest(args.install, archive=args.archive, version=args.version,
                              executable=args.executable, profiles=profiles,
                              runtime_version=runtime_version)
    output = args.output or (args.install / "runtime_manifest.json")
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Записан манифест: {output}")
    print(f"Файлов: {len(manifest['files'])}, лицензий: {len(manifest['licenses'])}")
    if manifest.get("archive_sha256"):
        print(f"Архив SHA-256: {manifest['archive_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
