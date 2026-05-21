from __future__ import annotations

import threading
import time
from typing import Dict, Tuple

import redis

from ..settings import get_settings

settings = get_settings()

_client: redis.Redis | None = None
_lock = threading.Lock()
_memory_limits: Dict[str, Tuple[int, int]] = {}


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def _memory_check(key: str, window: int, limit: int) -> bool:
    with _lock:
        stored_window, count = _memory_limits.get(key, (window, 0))
        if stored_window != window:
            stored_window = window
            count = 0
        count += 1
        _memory_limits[key] = (stored_window, count)
        return count <= limit


def check_rate_limit(identifier: str, limit: int, window_seconds: int) -> bool:
    if limit <= 0 or window_seconds <= 0:
        return True

    window = int(time.time() // window_seconds)
    key = f"ratelimit:{window_seconds}:{window}:{identifier}"

    try:
        client = _get_client()
        count = client.incr(key)
        if count == 1:
            client.expire(key, window_seconds)
        return count <= limit
    except Exception:
        return _memory_check(key, window, limit)
