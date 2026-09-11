from pathlib import Path
import time
from unittest.mock import MagicMock

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
    assert result.event.path == event.path
    assert result.event.event_type == event.event_type


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

    assert first is not None and first.event.path == events[1].path
    assert second is not None and second.event.path == events[2].path


# ── Recuperation des messages orphelins (redis stream, XAUTOCLAIM) ──────────
# Regression reelle (production, 2026-09-11) : dequeue_event() ne lisait
# jamais qu'avec l'id ">" (XREADGROUP), qui par construction ne revisite
# JAMAIS les messages deja livres a un autre consumer, mort ou vivant. Un
# redeploiement qui tue le worker en cours de traitement d'un evenement
# laisse ce message bloque pour toujours sous l'identite du consumer
# disparu -- observe en direct : redis_queue_length reste bloque a 400+
# pendant toute une session de plusieurs heures avec ~7 redeploiements,
# sans jamais descendre, alors que worker_alive=true et aucune erreur
# rapportee. XAUTOCLAIM recupere ces messages abandonnes.

def _fake_stream_fields(event: WatchEvent) -> dict[str, str]:
    return {
        "path": str(event.path),
        "event_type": event.event_type,
        "observed_at": str(event.observed_at),
    }


def test_dequeue_reclaims_a_stale_orphaned_message_before_reading_new_ones(monkeypatch):
    """Un message idle depuis plus de _RECLAIM_IDLE_MS (laisse par un
    consumer mort) doit etre recupere via XAUTOCLAIM, sans meme interroger
    XREADGROUP pour de nouveaux messages."""
    monkeypatch.setattr(event_queue, "_is_stream_backend", lambda: True)
    monkeypatch.setattr(event_queue, "_ensure_stream_group", lambda client: None)

    orphaned_event = WatchEvent(path=Path("/tmp/orphaned.txt"), event_type="rescore", observed_at=time.time())
    fake_client = MagicMock()
    fake_client.xautoclaim.return_value = (
        "0-0",
        [("1234-0", _fake_stream_fields(orphaned_event))],
        [],
    )
    monkeypatch.setattr(event_queue, "_get_client", lambda: fake_client)

    result = event_queue.dequeue_event(timeout=0.1)

    assert result is not None
    assert result.event.path == orphaned_event.path
    assert result.event.event_type == "rescore"
    assert result.message_id == "1234-0"
    fake_client.xautoclaim.assert_called_once()
    fake_client.xreadgroup.assert_not_called()


def test_dequeue_reads_new_message_when_nothing_to_reclaim(monkeypatch):
    """Quand XAUTOCLAIM ne trouve rien a recuperer (cas normal), le
    comportement habituel (lire un nouveau message via XREADGROUP) doit
    continuer de fonctionner sans changement."""
    monkeypatch.setattr(event_queue, "_is_stream_backend", lambda: True)
    monkeypatch.setattr(event_queue, "_ensure_stream_group", lambda client: None)

    new_event = WatchEvent(path=Path("/tmp/new.txt"), event_type="created", observed_at=time.time())
    fake_client = MagicMock()
    fake_client.xautoclaim.return_value = ("0-0", [], [])
    fake_client.xreadgroup.return_value = [
        (event_queue._STREAM_NAME, [("5678-0", _fake_stream_fields(new_event))]),
    ]
    monkeypatch.setattr(event_queue, "_get_client", lambda: fake_client)

    result = event_queue.dequeue_event(timeout=0.1)

    assert result is not None
    assert result.event.path == new_event.path
    assert result.message_id == "5678-0"
    fake_client.xautoclaim.assert_called_once()
    fake_client.xreadgroup.assert_called_once()


def test_reclaim_failure_falls_back_to_reading_new_messages(monkeypatch):
    """Si XAUTOCLAIM echoue (ex: serveur Redis plus ancien sans cette
    commande), le worker doit continuer a fonctionner via XREADGROUP plutot
    que de planter."""
    monkeypatch.setattr(event_queue, "_is_stream_backend", lambda: True)
    monkeypatch.setattr(event_queue, "_ensure_stream_group", lambda client: None)

    new_event = WatchEvent(path=Path("/tmp/new2.txt"), event_type="created", observed_at=time.time())
    fake_client = MagicMock()
    fake_client.xautoclaim.side_effect = Exception("ERR unknown command 'XAUTOCLAIM'")
    fake_client.xreadgroup.return_value = [
        (event_queue._STREAM_NAME, [("9999-0", _fake_stream_fields(new_event))]),
    ]
    monkeypatch.setattr(event_queue, "_get_client", lambda: fake_client)

    result = event_queue.dequeue_event(timeout=0.1)

    assert result is not None
    assert result.event.path == new_event.path
