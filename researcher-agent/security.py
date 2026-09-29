"""
Lightweight security helpers appropriate for a local single-user research app:
- a simple in-memory sliding-window rate limiter (per-process; fine for local use)
- an optional API key check for JSON endpoints (only enforced if APP_API_KEY is set)
- filename/content-type validation helpers used by the upload route
"""
import hmac
import time
import threading
from functools import wraps
from flask import request, jsonify, current_app

_rate_lock = threading.Lock()
_rate_buckets = {}  # key -> list[timestamps]


def rate_limited(key: str, limit_per_minute: int) -> bool:
    now = time.time()
    window_start = now - 60
    with _rate_lock:
        bucket = _rate_buckets.setdefault(key, [])
        # drop timestamps outside the window
        while bucket and bucket[0] < window_start:
            bucket.pop(0)
        if len(bucket) >= limit_per_minute:
            return True
        bucket.append(now)
        return False


def rate_limit(scope: str = "default"):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            limit = current_app.config.get("RATE_LIMIT_PER_MINUTE", 30)
            key = f"{scope}:{request.remote_addr}"
            if rate_limited(key, limit):
                return jsonify({"error": "Rate limit exceeded. Please slow down and try again shortly."}), 429
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def require_api_key(fn):
    """No-op unless APP_API_KEY is configured, so the app works out of the box
    locally, but can be locked down by setting APP_API_KEY in .env."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        configured_key = current_app.config.get("APP_API_KEY")
        if not configured_key:
            return fn(*args, **kwargs)
        provided = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(provided.encode(), configured_key.encode()):
            return jsonify({"error": "Unauthorized: missing or invalid X-API-Key header."}), 401
        return fn(*args, **kwargs)
    return wrapped
