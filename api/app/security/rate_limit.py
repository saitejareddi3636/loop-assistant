from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowRateLimiter:
    """Simple in-memory sliding-window limiter (single-process demo)."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


# Defaults: 10 turns / minute / conversation, 1 voice stream start / 5s
turn_limiter = SlidingWindowRateLimiter(limit=10, window_seconds=60)
voice_start_limiter = SlidingWindowRateLimiter(limit=12, window_seconds=60)
# Dictation uploads: a bit looser than live starts (user may re-record).
transcribe_limiter = SlidingWindowRateLimiter(limit=20, window_seconds=60)
