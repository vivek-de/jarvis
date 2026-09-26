"""
backend/security/ratelimit.py — simple per-client fixed-window rate limiter (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
In-memory, single-process (fine for a single-user Mac). Phase 5+ can swap in Redis.
Applied as FastAPI middleware; returns HTTP 429 when a client exceeds N req/min.
"""
from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = now or time.time()
        window_start = now - 60.0
        hits = [t for t in self._hits[key] if t >= window_start]
        hits.append(now)
        self._hits[key] = hits
        return len(hits) <= self.per_minute


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int):
        super().__init__(app)
        self.limiter = RateLimiter(per_minute)

    async def dispatch(self, request: Request, call_next):
        # health is always allowed (used by monitors)
        if request.url.path == "/health":
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        if not self.limiter.allow(client):
            return JSONResponse(
                status_code=429,
                content={"error": "rate limit exceeded", "limit_per_min": self.limiter.per_minute},
            )
        return await call_next(request)
