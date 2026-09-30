#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-memory rate limit для user-reports (по IP)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class IssueRateLimiter:
    def __init__(self, max_per_hour: int = 3, max_keys: int = 10_000) -> None:
        self.max_per_hour = max(1, int(max_per_hour))
        self.max_keys = max(100, int(max_keys))
        self._events: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _purge_locked(self, now: float) -> None:
        window_start = now - 3600
        empty: list[str] = []
        for key, events in self._events.items():
            if not key:
                empty.append(key)
                continue
            kept = [ts for ts in events if ts >= window_start]
            if kept:
                self._events[key] = kept
            else:
                empty.append(key)
        for key in empty:
            self._events.pop(key, None)
        while len(self._events) > self.max_keys:
            oldest = min(self._events, key=lambda k: self._events[k][0] if self._events[k] else now)
            self._events.pop(oldest, None)

    def allow(self, key: str) -> bool:
        key = (key or "").strip()
        if not key:
            key = "unknown"
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            bucket = list(self._events.get(key, []))
            if len(bucket) >= self.max_per_hour:
                self._events[key] = bucket
                return False
            bucket.append(now)
            self._events[key] = bucket
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
