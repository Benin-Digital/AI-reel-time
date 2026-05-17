from __future__ import annotations

from collections.abc import Callable
import logging
import threading
import time

from .event_queue import dequeue_event
from .watcher import WatchEvent

logger = logging.getLogger(__name__)


class EventWorker:
    def __init__(
        self,
        handler: Callable[[WatchEvent], None],
        poll_interval: float = 1.0,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
        retry_max_delay: float = 10.0,
    ) -> None:
        self._handler = handler
        self._poll_interval = poll_interval
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
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
            self._process_event(event)

    def _process_event(self, event: WatchEvent) -> None:
        attempt = 0
        while attempt <= self._max_retries and not self._stop_event.is_set():
            try:
                self._handler(event)
                return
            except Exception:
                attempt += 1
                logger.exception(
                    "event worker failed to process event on attempt %d",
                    attempt,
                )
                if attempt > self._max_retries:
                    logger.error(
                        "dropping event after %d failed attempts: %s",
                        self._max_retries,
                        event,
                    )
                    return
                delay = min(
                    self._retry_base_delay * (2 ** (attempt - 1)),
                    self._retry_max_delay,
                )
                time.sleep(delay)
