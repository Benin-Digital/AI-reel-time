from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import socket
import threading
from typing import Deque

import redis
from ..settings import get_settings
from .watcher import WatchEvent

settings = get_settings()
logger = logging.getLogger(__name__)

_QUEUE_NAME = settings.queue_stream_name
_STREAM_NAME = settings.queue_stream_name
_STREAM_GROUP = settings.queue_consumer_group
_QUEUE_WARN_THRESHOLD = settings.queue_memory_warn_threshold
_client: redis.Redis | None = None
_memory_queue: Deque[str] = deque()
_lock = threading.Lock()


@dataclass(frozen=True)
class QueuedEvent:
    event: WatchEvent
    backend: str
    stream: str | None = None
    group: str | None = None
    message_id: str | None = None


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


def _is_stream_backend() -> bool:
    return settings.queue_backend.lower() == "stream"


def _get_consumer_name() -> str:
    if settings.queue_consumer_name:
        return settings.queue_consumer_name
    host = socket.gethostname() or "worker"
    return f"{host}-{os.getpid()}"


def _ensure_stream_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(_STREAM_NAME, _STREAM_GROUP, id="0", mkstream=True)
    except redis.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _stream_queue_depth(client: redis.Redis) -> int:
    _ensure_stream_group(client)
    try:
        groups = client.xinfo_groups(_STREAM_NAME)
    except Exception:
        return 0
    for group in groups:
        if group.get("name") == _STREAM_GROUP:
            pending = int(group.get("pending") or 0)
            lag = group.get("lag")
            lag_value = int(lag) if lag is not None else 0
            return pending + lag_value
    return 0


def warn_if_unsafe_backend() -> None:
    """Emet un warning si on tourne en backend `memory` hors environnement de dev.

    Le backend memory est NON-PERSISTANT et NON-DISTRIBUE :
    - les evenements en file sont perdus au redemarrage
    - plusieurs workers ne partagent pas la file
    A reserver strictement au dev/CI. En staging/prod, basculer sur `stream` + Redis.
    """
    backend = (settings.queue_backend or "").lower()
    env = (getattr(settings, "environment", "local") or "local").lower()
    safe_envs = {"local", "dev", "development", "test", "ci"}
    if backend == "memory" and env not in safe_envs:
        logger.warning(
            "AI_REALTIME_QUEUE_BACKEND=memory detected in environment=%r. "
            "The in-memory queue is non-persistent and not shared across workers. "
            "Switch to AI_REALTIME_QUEUE_BACKEND=stream with Redis for staging/production.",
            env,
        )


def get_queue_status() -> dict[str, int | bool]:
    memory_count = len(_memory_queue)
    redis_count = 0
    redis_ok = False
    try:
        client = _get_client()
        if _is_stream_backend():
            redis_count = _stream_queue_depth(client)
        else:
            redis_count = client.llen(_QUEUE_NAME)
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
                if _is_stream_backend():
                    fields = _payload_to_stream_fields(payload)
                    if fields is None:
                        moved += 1
                        continue
                    client.xadd(_STREAM_NAME, fields)
                else:
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


def _event_to_stream_fields(event: WatchEvent) -> dict[str, str]:
    return {
        "path": str(event.path),
        "event_type": event.event_type,
        "observed_at": str(event.observed_at),
    }


def _payload_to_stream_fields(payload: str) -> dict[str, str] | None:
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    fields: dict[str, str] = {}
    for key, value in data.items():
        fields[str(key)] = str(value)
    return fields


def _deserialize_event(raw: str | bytes | dict[str, str | bytes]) -> WatchEvent | None:
    try:
        payload: dict[str, str | float]
        if isinstance(raw, dict):
            payload = {}
            for key, value in raw.items():
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                if isinstance(value, bytes):
                    value = value.decode("utf-8")
                payload[str(key)] = str(value)
        else:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                raise ValueError("payload is not a dict")
            payload = loaded
        return WatchEvent(
            path=Path(str(payload["path"])),
            event_type=str(payload["event_type"]),
            observed_at=float(payload["observed_at"]),
        )
    except Exception as exc:
        logger.warning("failed to deserialize event payload: %s", exc)
        return None


def enqueue_event(event: WatchEvent) -> bool:
    payload = _serialize_event(event)
    try:
        client = _get_client()
        if _is_stream_backend():
            _ensure_stream_group(client)
            client.xadd(_STREAM_NAME, _event_to_stream_fields(event))
        else:
            client.rpush(_QUEUE_NAME, payload)
        if _memory_queue:
            flush_memory_queue()
        return True
    except Exception as exc:
        logger.warning("redis enqueue failed, falling back to memory: %s", exc)
        try:
            with _lock:
                if len(_memory_queue) >= settings.queue_memory_max_size:
                    _memory_queue.popleft()
                    logger.warning(
                        "memory queue exceeded max size %d, dropping oldest event",
                        settings.queue_memory_max_size,
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


def dequeue_event(timeout: float = 1.0) -> QueuedEvent | None:
    if _is_stream_backend():
        try:
            client = _get_client()
            _ensure_stream_group(client)
            block_ms = max(1, int(timeout * 1000))
            response = client.xreadgroup(
                _STREAM_GROUP,
                _get_consumer_name(),
                {_STREAM_NAME: ">"},
                count=1,
                block=block_ms,
            )
            if response:
                stream_name, messages = response[0]
                message_id, fields = messages[0]
                event = _deserialize_event(fields)
                if event is None:
                    client.xack(stream_name, _STREAM_GROUP, message_id)
                    return None
                return QueuedEvent(
                    event=event,
                    backend="stream",
                    stream=str(stream_name),
                    group=_STREAM_GROUP,
                    message_id=str(message_id),
                )
        except Exception as exc:
            logger.warning("redis dequeue failed, falling back to memory: %s", exc)
    else:
        try:
            client = _get_client()
            result = client.blpop(_QUEUE_NAME, timeout=max(1, int(timeout)))
            if result:
                _, payload = result
                event = _deserialize_event(payload)
                if event is None:
                    return None
                return QueuedEvent(event=event, backend="list")
        except Exception as exc:
            logger.warning("redis dequeue failed, falling back to memory: %s", exc)

    with _lock:
        if not _memory_queue:
            return None
        payload = _memory_queue.popleft()

    event = _deserialize_event(payload)
    if event is None:
        return None
    return QueuedEvent(event=event, backend="memory")


def ack_event(queued_event: QueuedEvent) -> None:
    if queued_event.backend != "stream":
        return
    if not queued_event.message_id:
        return
    try:
        client = _get_client()
        client.xack(
            queued_event.stream or _STREAM_NAME,
            queued_event.group or _STREAM_GROUP,
            queued_event.message_id,
        )
    except Exception as exc:
        logger.warning("failed to acknowledge stream message: %s", exc)
