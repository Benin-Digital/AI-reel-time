from __future__ import annotations

from collections import deque
import json
import logging
from pathlib import Path
import threading
from typing import Deque

import redis

from ..settings import get_settings
from .watcher import WatchEvent

settings = get_settings()
logger = logging.getLogger(__name__)

_QUEUE_NAME = "airealtime:watch_events"
_client: redis.Redis | None = None
_memory_queue: Deque[str] = deque()
_lock = threading.Lock()


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _serialize_event(event: WatchEvent) -> str:
    payload = {
        "path": str(event.path),
        "event_type": event.event_type,
        "observed_at": event.observed_at,
    }
    return json.dumps(payload)


def _deserialize_event(raw: str | bytes) -> WatchEvent | None:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        return WatchEvent(
            path=Path(payload["path"]),
            event_type=payload["event_type"],
            observed_at=float(payload["observed_at"]),
        )
    except Exception as exc:
        logger.warning("failed to deserialize event payload: %s", exc)
        return None


def enqueue_event(event: WatchEvent) -> bool:
    payload = _serialize_event(event)
    try:
        client = _get_client()
        client.rpush(_QUEUE_NAME, payload)
        return True
    except Exception as exc:
        logger.warning("redis enqueue failed, falling back to memory: %s", exc)
        try:
            with _lock:
                _memory_queue.append(payload)
            return True
        except Exception as memory_exc:
            logger.exception("memory enqueue failed: %s", memory_exc)
            return False


def dequeue_event(timeout: float = 1.0) -> WatchEvent | None:
    try:
        client = _get_client()
        result = client.blpop(_QUEUE_NAME, timeout=max(1, int(timeout)))
        if result:
            _, payload = result
            return _deserialize_event(payload)
    except Exception as exc:
        logger.warning("redis dequeue failed, falling back to memory: %s", exc)

    with _lock:
        if not _memory_queue:
            return None
        payload = _memory_queue.popleft()

    return _deserialize_event(payload)
