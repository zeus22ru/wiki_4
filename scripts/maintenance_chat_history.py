#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Maintenance для старых guest/orphan chat sessions."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from core.chat_history import get_chat_history  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Очистить старые гостевые и orphan-сессии истории чатов."
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=30,
        help="Удалять guest/orphan-сессии старше N дней по updated_at (по умолчанию: 30).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Максимум сессий за один запуск (по умолчанию: 1000).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Выполнить удаление. Без этого флага запускается dry-run.",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Запустить VACUUM после фактического удаления.",
    )
    args = parser.parse_args()

    result = get_chat_history().cleanup_guest_sessions(
        retention_days=args.retention_days,
        dry_run=not args.apply,
        limit=args.limit,
        vacuum=args.vacuum,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
