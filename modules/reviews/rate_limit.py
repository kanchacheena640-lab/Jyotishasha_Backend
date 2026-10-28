"""Small fixed-window rate limiter for the public review endpoints (F10-P15).

Uses Redis (REDIS_URL, the same broker Celery already uses) so limits hold
across web workers; if Redis is not configured or unreachable it degrades to a
per-process in-memory window rather than failing the request. Client IPs are
only ever used as a SHA-256 hash in limiter keys -- never stored or logged.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time

_memory: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()
_redis_client = None
_redis_checked = False


def _redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    url = os.getenv("REDIS_URL")
    if url:
        try:
            import redis
            import ssl
            kwargs = {"ssl_cert_reqs": ssl.CERT_NONE} if url.startswith("rediss://") else {}
            client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5, **kwargs)
            client.ping()
            _redis_client = client
        except Exception:
            _redis_client = None
    return _redis_client


def client_key(remote_addr: str | None, forwarded_for: str | None) -> str:
    # The RIGHTMOST X-Forwarded-For entry is the one appended by Render's proxy;
    # earlier entries are client-supplied and would let a caller pick a fresh
    # bucket per request.
    ip = (forwarded_for or "").split(",")[-1].strip() or (remote_addr or "unknown")
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:24]


def allow(bucket: str, key: str, limit: int, window_seconds: int) -> bool:
    """True if this call is within `limit` per `window_seconds` for (bucket, key)."""
    full_key = f"rl:reviews:{bucket}:{key}:{int(time.time() // window_seconds)}"
    client = _redis()
    if client is not None:
        try:
            count = client.incr(full_key)
            if count == 1:
                client.expire(full_key, window_seconds)
            return count <= limit
        except Exception:
            pass
    now = time.time()
    with _lock:
        count, expires = _memory.get(full_key, (0, now + window_seconds))
        if expires < now:
            count, expires = 0, now + window_seconds
        count += 1
        _memory[full_key] = (count, expires)
        if len(_memory) > 10000:
            for k in [k for k, (_, exp) in _memory.items() if exp < now]:
                _memory.pop(k, None)
        return count <= limit


def reset_memory_for_tests() -> None:
    with _lock:
        _memory.clear()
