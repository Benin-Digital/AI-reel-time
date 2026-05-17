from __future__ import annotations

from collections.abc import Callable
import logging
import threading

from .event_queue import dequeue_event
from .watcher import WatchEvent

logger = logging.getLogger(__name__)


class EventWorker:
    def __init__(self, handler: Callable[[WatchEvent], None], poll_interval: float = 1.0) -> None:
        self._handler = handler
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="event-worker",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            event = dequeue_event(timeout=self._poll_interval)
            if event is None:
                continue
            try:
                self._handler(event)
            except Exception:
                logger.exception("event worker failed to process event")
