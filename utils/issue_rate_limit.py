#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-memory rate limit для user-reports (IP + guest_id)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class IssueRateLimiter:
    def __init__(self, max_per_hour: int = 3) -> None:
        self.max_per_hour = max(1, int(max_per_hour))
        self._events: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        window_start = now - 3600
        with self._lock:
            bucket = [ts for ts in self._events[key] if ts >= window_start]
            if len(bucket) >= self.max_per_hour:
                self._events[key] = bucket
                return False
            bucket.append(now)
            self._events[key] = bucket
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
