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
_QUEUE_MAX_MEMORY_SIZE = settings.queue_memory_max_size
_QUEUE_WARN_THRESHOLD = settings.queue_memory_warn_threshold
_client: redis.Redis | None = None
_memory_queue: Deque[str] = deque()
_lock = threading.Lock()


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


def _is_redis_available() -> bool:
    try:
        _get_client().ping()
        return True
    except Exception:
        return False


def get_queue_status() -> dict[str, int | bool]:
    memory_count = len(_memory_queue)
    redis_count = 0
    redis_ok = False
    try:
        redis_count = _get_client().llen(_QUEUE_NAME)
        redis_ok = True
    except Exception:
        redis_ok = False
    return {
        "redis_available": redis_ok,
        "redis_queue_length": int(redis_count or 0),
        "memory_queue_length": int(memory_count),
    }


def flush_memory_queue() -> int:
    if not _is_redis_available():
        return 0
    moved = 0
    client = _get_client()
    with _lock:
        while _memory_queue:
            payload = _memory_queue.popleft()
            try:
                client.rpush(_QUEUE_NAME, payload)
                moved += 1
            except Exception as exc:
                logger.warning("failed to flush memory queue to redis: %s", exc)
                _memory_queue.appendleft(payload)
                break
    return moved


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
        if _memory_queue:
            flush_memory_queue()
        return True
    except Exception as exc:
        logger.warning("redis enqueue failed, falling back to memory: %s", exc)
        try:
            with _lock:
                if len(_memory_queue) >= _QUEUE_MAX_MEMORY_SIZE:
                    _memory_queue.popleft()
                    logger.warning(
                        "memory queue exceeded max size %d, dropping oldest event",
                        _QUEUE_MAX_MEMORY_SIZE,
                    )
                _memory_queue.append(payload)
                if len(_memory_queue) >= _QUEUE_WARN_THRESHOLD:
                    logger.warning(
                        "memory queue length at %d, consider checking redis availability",
                        len(_memory_queue),
                    )
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
