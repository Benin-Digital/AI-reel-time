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


def test_memory_queue_is_bounded(monkeypatch):
    event_queue._memory_queue.clear()
    event_queue.settings.queue_memory_max_size = 2

    def _boom():
        raise RuntimeError("no redis")

    monkeypatch.setattr(event_queue, "_get_client", _boom)

    events = [
        WatchEvent(path=Path(f"/tmp/cv_demo_{i}.txt"), event_type="created", observed_at=time.time())
        for i in range(3)
    ]

    for ev in events:
        assert event_queue.enqueue_event(ev) is True

    assert len(event_queue._memory_queue) == 2
    first = event_queue.dequeue_event(timeout=0.1)
    second = event_queue.dequeue_event(timeout=0.1)

    assert first is not None and first.path == events[1].path
    assert second is not None and second.path == events[2].path
