"""Tests de non-regression pour la concurrence du worker d'ingestion.

Contexte : EventWorker ne lancait qu'un seul thread, code en dur, sans
justification documentee. Le mettre a plusieurs threads est sans danger
cote file Redis (les consumer groups sont concus pour ca), a condition que
chaque thread ait une identite de consommateur distincte — sinon le suivi
des messages en cours (XPENDING/XCLAIM) devient ambigu en cas de crash.

Ces tests verifient :
- EventWorker(num_workers=N) demarre bien N threads et s'arrete proprement ;
- chaque thread appelle dequeue_event() avec un consumer_suffix distinct ;
- _get_consumer_name() reste stable (pas de suffixe) quand num_workers=1,
  pour ne rien changer au nom de consommateur historique par defaut.
"""
from __future__ import annotations

import threading
import time

from app.services import event_queue
from app.services.worker import EventWorker


def test_get_consumer_name_without_suffix_is_unchanged():
    base = event_queue._get_consumer_name()
    assert event_queue._get_consumer_name("") == base


def test_get_consumer_name_with_suffix_is_distinct():
    base = event_queue._get_consumer_name()
    a = event_queue._get_consumer_name("0")
    b = event_queue._get_consumer_name("1")
    assert a != base
    assert b != base
    assert a != b
    assert a.endswith("-0")
    assert b.endswith("-1")


def test_single_worker_starts_one_thread_and_stops():
    worker = EventWorker(handler=lambda event: None, poll_interval=0.05, num_workers=1)
    assert len(worker._threads) == 1
    worker.start()
    time.sleep(0.1)
    assert worker.is_running
    worker.stop()
    assert not any(t.is_alive() for t in worker._threads)


def test_multiple_workers_use_distinct_consumer_suffixes(monkeypatch):
    seen_suffixes: set[str] = set()
    lock = threading.Lock()

    def _fake_dequeue(timeout=1.0, consumer_suffix=""):
        with lock:
            seen_suffixes.add(consumer_suffix)
        time.sleep(0.01)
        return None

    monkeypatch.setattr("app.services.worker.dequeue_event", _fake_dequeue)

    worker = EventWorker(handler=lambda event: None, poll_interval=0.01, num_workers=3)
    worker.start()
    time.sleep(0.2)
    worker.stop()

    assert seen_suffixes == {"0", "1", "2"}
