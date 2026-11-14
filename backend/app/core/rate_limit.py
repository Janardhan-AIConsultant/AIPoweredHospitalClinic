"""Best-effort in-memory sliding-window rate limiter.

On serverless each instance keeps its own counters, so this is a first line of defence
against bursts, not a global quota. A shared store (e.g. Postgres/Redis) is the upgrade path.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from app.core.exceptions import RateLimitError

_MAX_KEYS = 10_000


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = self.clock()
        if len(self._hits) > _MAX_KEYS:  # bound memory under key-spraying
            self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window})
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise RateLimitError()
        hits.append(now)


def client_key(request: Request) -> str:
    """Client IP; behind Vercel the first X-Forwarded-For entry is the caller."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def rate_limited(limiter: RateLimiter) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        limiter.check(client_key(request))

    return dependency
