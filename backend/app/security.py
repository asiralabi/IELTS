"""Request-level protections: rate limits, body size caps, security headers,
and the admin gate for routes that change data every student shares.

Kept dependency-free on purpose. The limiter lives in process memory, which
on a serverless platform means per instance: it will not stop a determined
distributed attack, but it does stop the cheap ones — one machine guessing
passwords, a script registering accounts, or a loop running up the bill on
the hosted model. A shared store (Redis, Upstash) is the upgrade path if the
pilot grows past that.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request, UploadFile, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.config import settings

# ── who is calling ──────────────────────────────────────────────────────────


def client_ip(request: Request) -> str:
    """The caller's address, preferring what the platform proxy recorded.

    Vercel sets `x-real-ip` itself, so a client cannot forge it there. The
    first `x-forwarded-for` hop is the fallback for the Caddy deployment.
    """
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── rate limiting ───────────────────────────────────────────────────────────


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until allowed."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, window_s - (now - q[0]))
            q.append(now)
            # Keep memory bounded on a long-lived process.
            if len(self._hits) > 50_000:
                for stale in [k for k, v in self._hits.items() if not v][:10_000]:
                    del self._hits[stale]
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()

# (method, path prefix) -> (limit, window seconds). Matched in order; the first
# rule whose prefix matches wins. Generation and marking each cost a call to
# the hosted model, so they share a per-caller budget.
RATE_RULES: list[tuple[str, str, int, int]] = [
    ("POST", "/auth/login", 10, 60),
    ("POST", "/auth/register", 5, 3600),
    ("POST", "/auth/refresh", 30, 60),
    ("DELETE", "/auth/me", 5, 3600),
    ("GET", "/auth/me/export", 10, 3600),
    ("POST", "/feedback", 5, 600),
    ("GET", "/feedback", 10, 60),
    ("POST", "/knowledge", 10, 3600),
    ("POST", "/chat", 30, 600),
    ("POST", "/writing", 20, 600),
    ("POST", "/speaking", 30, 600),
    ("POST", "/reading", 40, 600),
    ("POST", "/listening", 40, 600),
    ("POST", "/questions", 40, 600),
    ("POST", "/mock-exam", 10, 600),
    ("POST", "/progress", 20, 600),
    ("POST", "/cambridge", 60, 600),
]


def _caller_key(request: Request) -> str:
    # A bearer token identifies a user more reliably than an IP that many
    # students on one campus network share. It is not verified here; a forged
    # token only buys a forger their own private budget, and the route itself
    # still rejects it.
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and len(auth) > 20:
        return "tok:" + auth[-32:]
    return "ip:" + client_ip(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if settings.rate_limit_enabled:
            method, path = request.method, request.url.path
            for rule_method, prefix, limit, window in RATE_RULES:
                if method == rule_method and path.startswith(prefix):
                    # Auth routes are keyed by IP: there is no user yet, and a
                    # password-guesser must not be able to reset the window by
                    # sending a random Authorization header.
                    key = (
                        "ip:" + client_ip(request)
                        if prefix.startswith("/auth") or prefix == "/feedback"
                        else _caller_key(request)
                    )
                    wait = limiter.hit(f"{prefix}|{key}", limit, window)
                    if wait is not None:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Too many requests. Please wait a moment and try again."},
                            headers={"Retry-After": str(int(wait))},
                        )
                    break
        return await call_next(request)


# ── body size ───────────────────────────────────────────────────────────────

MAX_JSON_BYTES = 1 * 1024 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class BodySizeMiddleware(BaseHTTPMiddleware):
    """Refuse oversized bodies before anything reads them into memory."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        length = request.headers.get("content-length")
        if length is not None:
            try:
                size = int(length)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
            ctype = request.headers.get("content-type", "")
            cap = MAX_UPLOAD_BYTES if ctype.startswith("multipart/") else MAX_JSON_BYTES
            if size > cap:
                return JSONResponse(status_code=413, content={"detail": "Request is too large."})
        return await call_next(request)


async def read_upload_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, stopping as soon as it passes `max_bytes`.

    The header check above can be skipped by a chunked request, so routes that
    accept files read through this instead of `await upload.read()`.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="File is too large.")
        chunks.append(chunk)
    return b"".join(chunks)


# ── response headers ────────────────────────────────────────────────────────

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), payment=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/auth"):
            # Tokens must never sit in a shared or browser cache.
            response.headers["Cache-Control"] = "no-store"
        return response


# ── admin gate ──────────────────────────────────────────────────────────────


def require_admin(x_admin_token: str = Header(default="")) -> None:
    """Guard for routes that change what EVERY student sees.

    Uses the same shared token as the feedback inbox. Unset means closed: a
    deployment nobody configured must not let any registered user rewrite the
    knowledge base that grounds everyone's marking.
    """
    expected = settings.feedback_admin_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to the Oratio team.",
        )
    if not secrets.compare_digest(x_admin_token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token.")
