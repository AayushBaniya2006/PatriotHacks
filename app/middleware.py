"""ASGI middleware for API hardening: request-body size cap, per-IP
sliding-window rate limiting on /api/*, and baseline security response
headers.

Kept separate from app/main.py so the route-handling surface stays focused
on the actual endpoints; these are pure cross-cutting concerns wired up via
app.add_middleware(...) in app/main.py.

Registration order matters: Starlette's add_middleware() prepends to an
internal list, and the middleware stack is built by wrapping in reverse --
so the LAST middleware registered ends up OUTERMOST (sees the request
first, the response last). app/main.py registers, in order:
BodySizeLimitMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware,
then CORSMiddleware last -- so CORS ends up outermost and still attaches
its headers to the 429/413 responses these middlewares produce directly,
which a cross-origin browser frontend needs in order to read the response
at all (an error response missing CORS headers looks like a network error
to `fetch`, not a readable 429/413).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_BODY_BYTES = 16 * 1024  # ~16KB cap on request bodies

RATE_LIMIT_MAX_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60.0

# Module-level (not instance-level) so it's a single source of truth
# regardless of how many times Starlette constructs the middleware, and so
# tests can reset it directly between runs:
#   from app.middleware import RATE_LIMIT_HITS; RATE_LIMIT_HITS.clear()
RATE_LIMIT_HITS: dict[str, deque] = defaultdict(deque)


class BodySizeLimitMiddleware:
    """Rejects request bodies over `max_bytes` with a 413, before the route
    handler (and pydantic parsing) ever sees the full body.

    Two layers of defense:
      1. Fast path: a Content-Length header already declaring more than the
         cap is rejected immediately, before the downstream app runs at all.
      2. Defensive path: `receive` is wrapped to count actual bytes
         streamed, in case Content-Length is absent or understated (chunked
         transfer, or a lying client). Once the running total exceeds the
         cap it raises HTTPException(413); because that raise happens while
         Starlette's ExceptionMiddleware (below us in the stack) is awaiting
         the app, it's caught there and turned into a proper 413 JSON
         response rather than a raw exception / stack trace.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or ())
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = None
            if declared is not None and declared > self.max_bytes:
                response = JSONResponse({"detail": "Request body too large"}, status_code=413)
                await response(scope, receive, send)
                return

        total = 0

        async def limited_receive() -> dict:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body") or b"")
                if total > self.max_bytes:
                    raise HTTPException(status_code=413, detail="Request body too large")
            return message

        await self.app(scope, limited_receive, send)


class RateLimitMiddleware:
    """Simple in-process sliding-window rate limit per client IP, scoped to
    /api/* (this naturally skips /healthz and the static demo page, since
    neither path starts with /api/). No external deps: one deque of
    monotonic request timestamps per IP, pruned to the trailing window on
    each request.

    In-process only, by design (hackathon-scoped demo, single instance) --
    state resets on restart and isn't shared across multiple workers.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    @staticmethod
    def _client_ip(scope: Scope) -> str:
        # Only the ASGI-reported peer address is trusted here -- this demo
        # isn't deployed behind a known/trusted reverse-proxy allowlist, so
        # an X-Forwarded-For header would be trivially spoofable by any
        # client wanting to dodge the limit.
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        ip = self._client_ip(scope)
        now = time.monotonic()
        hits = RATE_LIMIT_HITS[ip]
        cutoff = now - self.window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self.max_requests:
            retry_after = max(1, int(self.window_seconds - (now - hits[0])) + 1)
            response = JSONResponse(
                {"detail": "Too many requests, please slow down"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        hits.append(now)
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security response headers on every response. Cache-Control:
    no-store is scoped to /api/* only -- the static demo page is fine to
    cache normally."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
