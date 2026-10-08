"""Полная переиндексация с визуальными чанками и vision-описаниями.

Пишет прогресс в reindex_run.log (UTF-8) и в stdout.
"""
import json
import time
from pathlib import Path

from create_vector_db import reindex_vector_db

LOG = Path("reindex_run.log")
log = LOG.open("w", encoding="utf-8")


def out(line: str) -> None:
    print(line, flush=True)
    log.write(line + "\n")
    log.flush()


started = time.perf_counter()
seen: set = set()


def report(update: dict) -> None:
    progress = update.get("progress")
    stage = update.get("stage")
    message = update.get("message")
    key = (stage, int((progress or 0) // 5))
    if key not in seen:
        seen.add(key)
        out(f"[{progress:>3}%] {stage:<10} {message}")
    diag = update.get("diagnostics")
    if diag:
        out(f"      diagnostics: {json.dumps(diag, ensure_ascii=False)}")


out(f"=== старт {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
try:
    result = reindex_vector_db(progress_callback=report)
    out("=" * 60)
    out(f"ГОТОВО за {time.perf_counter() - started:.1f}s")
    out(json.dumps(result, ensure_ascii=False, indent=2, default=str))
except Exception as exc:  # noqa: BLE001
    out(f"ОШИБКА: {type(exc).__name__}: {exc}")
    raise
finally:
    log.close()
