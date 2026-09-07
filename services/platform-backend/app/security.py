from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from argon2 import PasswordHasher

try:
    from argon2.exceptions import InvalidHashError as _InvalidHashError
except ImportError:  # Compatibility with argon2-cffi versions without InvalidHashError symbol.
    from argon2.exceptions import InvalidHash as _InvalidHashError

from argon2.exceptions import VerifyMismatchError

from app.errors import ApiError

_password_hasher = PasswordHasher()


def new_uuid() -> str:
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (random_a << 64)
    value |= 0b10 << 62
    value |= random_b
    return str(uuid.UUID(int=value))


def utc_timestamp() -> int:
    return int(time.time())


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, _InvalidHashError):
        return False


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def request_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def issue_access_token(
    *,
    subject: str,
    session_id: str,
    kind: str,
    secret: str,
    ttl_seconds: int,
) -> str:
    claims = {
        "sub": subject,
        "sid": session_id,
        "typ": kind,
        "iat": utc_timestamp(),
        "exp": utc_timestamp() + ttl_seconds,
        "jti": new_uuid(),
    }
    body = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signature = _b64url(hmac.digest(secret.encode(), body.encode(), "sha256"))
    return f"{body}.{signature}"


def decode_access_token(token: str, secret: str, expected_kind: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
        expected = _b64url(hmac.digest(secret.encode(), body.encode(), "sha256"))
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        claims: dict[str, Any] = json.loads(_b64url_decode(body))
        if claims.get("typ") != expected_kind or int(claims.get("exp", 0)) <= utc_timestamp():
            raise ValueError
        return claims
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError(401, "INVALID_SESSION", "登录状态无效或已过期。") from exc


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class RateLimiter:
    """Small-process limiter; replace with Redis when API replicas exceed one."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (now - events[0])))
                raise ApiError(
                    429,
                    "RATE_LIMITED",
                    "操作过于频繁，请稍后重试。",
                    retryable=True,
                    details={"retry_after": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)
