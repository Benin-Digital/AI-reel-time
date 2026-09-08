from __future__ import annotations

from collections.abc import Callable
import logging
import threading
import time

from .event_queue import ack_event, dequeue_event
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
        ack_on_failure: bool = True,
        num_workers: int = 1,
    ) -> None:
        self._handler = handler
        self._poll_interval = poll_interval
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._ack_on_failure = ack_on_failure
        self._num_workers = max(1, num_workers)
        self._stop_event = threading.Event()
        self._threads = [
            threading.Thread(
                target=self._run,
                name=f"event-worker-{i}",
                args=(i,),
                daemon=True,
            )
            for i in range(self._num_workers)
        ]
        self.last_error: str | None = None

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    @property
    def is_running(self) -> bool:
        return all(thread.is_alive() for thread in self._threads)

    def stop(self) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=5)

    def _run(self, worker_index: int) -> None:
        # A distinct Redis consumer name per thread (not just per process) so
        # the stream consumer group can tell them apart — running several
        # threads under the same consumer name works but muddies delivery
        # tracking (XPENDING/XCLAIM) if one of them ever needs recovery.
        consumer_suffix = str(worker_index) if self._num_workers > 1 else ""
        while not self._stop_event.is_set():
            queued = dequeue_event(timeout=self._poll_interval, consumer_suffix=consumer_suffix)
            if queued is None:
                continue
            success = self._process_event(queued.event)
            if success or self._ack_on_failure:
                ack_event(queued)

    def _process_event(self, event: WatchEvent) -> bool:
        attempt = 0
        while attempt <= self._max_retries and not self._stop_event.is_set():
            try:
                self._handler(event)
                self.last_error = None
                return True
            except Exception as exc:
                attempt += 1
                self.last_error = str(exc)
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
                    return False
                delay = min(
                    self._retry_base_delay * (2 ** (attempt - 1)),
                    self._retry_max_delay,
                )
                time.sleep(delay)
        return False
