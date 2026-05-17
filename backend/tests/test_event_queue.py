from pathlib import Path
import time

from app.services import event_queue
from app.services.watcher import WatchEvent


def test_enqueue_dequeue_memory_fallback(monkeypatch):
    event_queue._memory_queue.clear()

    def _boom():
        raise RuntimeError("no redis")

    monkeypatch.setattr(event_queue, "_get_client", _boom)

    event = WatchEvent(
        path=Path("/tmp/cv_demo.txt"),
        event_type="created",
        observed_at=time.time(),
    )

    assert event_queue.enqueue_event(event) is True
    result = event_queue.dequeue_event(timeout=0.1)

    assert result is not None
    assert result.path == event.path
    assert result.event_type == event.event_type
