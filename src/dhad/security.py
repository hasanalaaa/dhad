"""Production HTTP security controls for Dhad's ASGI application."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass(frozen=True, slots=True)
class SecuritySettings:
    """Validated production security settings.

    API authentication is disabled when ``api_keys`` is empty.  Enabling it via
    ``DHAD_API_KEYS`` protects all analysis POST routes while keeping health,
    documentation, and static assets public.
    """

    max_text_characters: int = 50_000
    max_request_bytes: int = 262_144
    rate_limit_requests: int = 120
    rate_limit_window_seconds: float = 60.0
    rate_limit_enabled: bool = True
    rate_limit_max_identities: int = 50_000
    api_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_text_characters < 1:
            raise ValueError("max_text_characters must be positive")
        if self.max_request_bytes < 1024:
            raise ValueError("max_request_bytes must be at least 1024")
        if self.rate_limit_requests < 1:
            raise ValueError("rate_limit_requests must be positive")
        if self.rate_limit_window_seconds <= 0:
            raise ValueError("rate_limit_window_seconds must be positive")
        if self.rate_limit_max_identities < 1:
            raise ValueError("rate_limit_max_identities must be positive")
        if any(not item.strip() for item in self.api_keys):
            raise ValueError("API keys cannot be blank")

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        def integer(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        def floating(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be a number") from exc

        enabled = os.environ.get("DHAD_RATE_LIMIT_ENABLED", "true").strip().lower()
        if enabled not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
            raise ValueError("DHAD_RATE_LIMIT_ENABLED must be a boolean")
        keys = tuple(
            dict.fromkeys(
                item.strip()
                for item in os.environ.get("DHAD_API_KEYS", "").split(",")
                if item.strip()
            )
        )
        return cls(
            max_text_characters=integer("DHAD_MAX_TEXT_CHARACTERS", 50_000),
            max_request_bytes=integer("DHAD_MAX_REQUEST_BYTES", 262_144),
            rate_limit_requests=integer("DHAD_RATE_LIMIT_REQUESTS", 120),
            rate_limit_window_seconds=floating("DHAD_RATE_LIMIT_WINDOW_SECONDS", 60.0),
            rate_limit_enabled=enabled in {"1", "true", "yes", "on"},
            rate_limit_max_identities=integer("DHAD_RATE_LIMIT_MAX_IDENTITIES", 50_000),
            api_keys=keys,
        )

    @property
    def authentication_enabled(self) -> bool:
        return bool(self.api_keys)


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    """Concurrent in-memory token bucket with bounded stale-state cleanup."""

    def __init__(
        self,
        requests: int,
        window_seconds: float,
        *,
        max_identities: int = 50_000,
        clock=time.monotonic,
    ) -> None:
        if requests < 1 or window_seconds <= 0 or max_identities < 1:
            raise ValueError("Token bucket limits must be positive")
        self.capacity = float(requests)
        self.refill_rate = float(requests) / window_seconds
        self.window_seconds = float(window_seconds)
        self.clock = clock
        self.max_identities = max_identities
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = asyncio.Lock()
        self._operations = 0

    async def consume(self, identity: str) -> tuple[bool, int, float]:
        """Consume one token and return ``allowed, remaining, retry_after``."""

        async with self._lock:
            now = self.clock()
            bucket = self._buckets.get(identity)
            if bucket is None:
                bucket = _Bucket(self.capacity, now)
                self._buckets[identity] = bucket
                while len(self._buckets) > self.max_identities:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(identity)
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_rate)
            bucket.updated_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                allowed = True
                retry_after = 0.0
            else:
                allowed = False
                retry_after = (1.0 - bucket.tokens) / self.refill_rate
            remaining = max(0, int(bucket.tokens))
            self._operations += 1
            if self._operations % 1024 == 0:
                stale_before = now - max(self.window_seconds * 4.0, 300.0)
                self._buckets = OrderedDict(
                    (key, value)
                    for key, value in self._buckets.items()
                    if value.updated_at >= stale_before
                )
            return allowed, remaining, retry_after


class PayloadTooLargeError(Exception):
    """Raised internally when an ASGI request body exceeds the byte budget."""


_PUBLIC_PATHS = frozenset(
    {
        "/",
        "/api/health",
        "/v2/languages",
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/manifest.webmanifest",
        "/service-worker.js",
        "/favicon.svg",
    }
)


def _header_map(scope: Scope) -> dict[bytes, bytes]:
    return {name.lower(): value for name, value in scope.get("headers", [])}


def _json_response(
    status: int, payload: dict[str, object], headers: Iterable[tuple[bytes, bytes]] = ()
):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    base = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    base.extend(headers)
    return body, base


class ProductionSecurityMiddleware:
    """ASGI middleware for byte limits, API keys, and token-bucket limiting."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: SecuritySettings,
        limiter: TokenBucketLimiter | None = None,
    ) -> None:
        self.app = app
        self.settings = settings
        self.limiter = limiter or TokenBucketLimiter(
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
            max_identities=settings.rate_limit_max_identities,
        )
        self._key_hashes = tuple(
            hashlib.sha256(item.encode("utf-8")).digest() for item in settings.api_keys
        )

    @staticmethod
    def _is_public(scope: Scope) -> bool:
        path = str(scope.get("path", ""))
        if path in _PUBLIC_PATHS or path.startswith("/static/"):
            return True
        return scope.get("method") == "OPTIONS"

    def _presented_key(self, headers: dict[bytes, bytes]) -> str | None:
        direct = headers.get(b"x-api-key")
        try:
            if direct:
                return direct.decode("utf-8", errors="strict").strip()
            authorization = headers.get(b"authorization", b"").decode(
                "utf-8", errors="strict"
            )
        except UnicodeDecodeError:
            return None
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() == "bearer" and credential.strip():
            return credential.strip()
        return None

    def _authorized(self, presented: str | None) -> bool:
        if not self._key_hashes:
            return True
        if presented is None:
            return False
        digest = hashlib.sha256(presented.encode("utf-8")).digest()
        return any(hmac.compare_digest(digest, expected) for expected in self._key_hashes)

    @staticmethod
    def _client_identity(scope: Scope, presented_key: str | None) -> str:
        if presented_key:
            return "key:" + hashlib.sha256(presented_key.encode("utf-8")).hexdigest()[:24]
        client = scope.get("client")
        host = client[0] if client else "unknown"
        return f"ip:{host}"

    async def _send_error(
        self,
        send: Send,
        status: int,
        code: str,
        message: str,
        *,
        headers: Iterable[tuple[bytes, bytes]] = (),
    ) -> None:
        body, response_headers = _json_response(
            status,
            {"error": {"code": code, "message": message}},
            headers,
        )
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw_headers = scope.get("headers", [])
        headers = _header_map(scope)
        content_lengths = [
            value for name, value in raw_headers if name.lower() == b"content-length"
        ]
        if len(content_lengths) > 1:
            await self._send_error(
                send, 400, "invalid_content_length", "Multiple Content-Length headers"
            )
            return
        has_transfer_encoding = any(
            name.lower() == b"transfer-encoding" for name, _ in raw_headers
        )
        if content_lengths and has_transfer_encoding:
            await self._send_error(
                send,
                400,
                "ambiguous_request_framing",
                "Content-Length and Transfer-Encoding cannot be combined",
            )
            return
        content_length = content_lengths[0] if content_lengths else None
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await self._send_error(
                    send, 400, "invalid_content_length", "Invalid Content-Length"
                )
                return
            if declared < 0:
                await self._send_error(
                    send, 400, "invalid_content_length", "Invalid Content-Length"
                )
                return
            if declared > self.settings.max_request_bytes:
                await self._send_error(
                    send,
                    413,
                    "payload_too_large",
                    f"Request body exceeds {self.settings.max_request_bytes} bytes",
                )
                return

        public = self._is_public(scope)
        presented_key = self._presented_key(headers)
        if (
            not public
            and self.settings.authentication_enabled
            and not self._authorized(presented_key)
        ):
            await self._send_error(
                send,
                401,
                "invalid_api_key",
                "A valid API key is required",
                headers=((b"www-authenticate", b"Bearer"),),
            )
            return

        rate_headers: list[tuple[bytes, bytes]] = []
        if not public and self.settings.rate_limit_enabled:
            allowed, remaining, retry_after = await self.limiter.consume(
                self._client_identity(scope, presented_key)
            )
            rate_headers = [
                (b"x-ratelimit-limit", str(self.settings.rate_limit_requests).encode("ascii")),
                (b"x-ratelimit-remaining", str(remaining).encode("ascii")),
            ]
            if not allowed:
                retry_seconds = max(1, int(retry_after + 0.999))
                await self._send_error(
                    send,
                    429,
                    "rate_limit_exceeded",
                    "Too many requests",
                    headers=(*rate_headers, (b"retry-after", str(retry_seconds).encode("ascii"))),
                )
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.settings.max_request_bytes:
                    raise PayloadTooLargeError
            return message

        async def secured_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                if rate_headers:
                    existing = list(message.get("headers", []))
                    existing_names = {name.lower() for name, _ in existing}
                    existing.extend(
                        (name, value)
                        for name, value in rate_headers
                        if name.lower() not in existing_names
                    )
                    message = {**message, "headers": existing}
            await send(message)

        try:
            await self.app(scope, limited_receive, secured_send)
        except PayloadTooLargeError:
            if response_started:
                raise
            await self._send_error(
                send,
                413,
                "payload_too_large",
                f"Request body exceeds {self.settings.max_request_bytes} bytes",
            )


def enforce_text_limit(text: str, settings: SecuritySettings) -> None:
    """Raise a value error before NLP work when text exceeds the character cap."""

    if len(text) > settings.max_text_characters:
        raise ValueError(
            f"Text exceeds the configured limit of {settings.max_text_characters} characters"
        )
