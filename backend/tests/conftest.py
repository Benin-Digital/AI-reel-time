"""Fixtures partagees pytest pour l'API AI Real-Time.

Les variables d'environnement sont configurees AVANT tout import de `app.*`
pour eviter qu'`app.db` n'instancie un engine Postgres reel pendant les tests
unitaires legers.
"""
from __future__ import annotations

import os
from typing import Iterator

# --- Defaults safe pour les tests unitaires (avant import de app) ---------
os.environ.setdefault("AI_REALTIME_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("AI_REALTIME_NER_ENABLED", "false")
os.environ.setdefault("AI_REALTIME_EMBEDDING_ENABLED", "false")
os.environ.setdefault("AI_REALTIME_CONVERSION_USE_DOCLING", "false")
os.environ.setdefault("AI_REALTIME_CROSSENCODER_ENABLED", "false")
os.environ.setdefault("AI_REALTIME_QUEUE_BACKEND", "memory")
os.environ.setdefault("AI_REALTIME_JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("AI_REALTIME_AUTH_ENABLED", "false")
os.environ.setdefault("AI_REALTIME_REQUIRE_API_KEY", "false")

import pytest

from app.settings import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Vide le cache lru du settings entre tests pour eviter les fuites
    quand un test mute des attributs via monkeypatch.setattr(settings, ...)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings():
    """Acces direct a l'instance Settings courante."""
    return get_settings()


@pytest.fixture
def disable_security(monkeypatch) -> None:
    """Force require_api_key=False et auth_enabled=False pour les tests
    qui appellent des endpoints sans header d'auth."""
    from app import security as _sec

    monkeypatch.setattr(_sec.settings, "require_api_key", False)
    monkeypatch.setattr(_sec.settings, "auth_enabled", False)


@pytest.fixture
def reset_memory_queue() -> Iterator[None]:
    """Vide le buffer in-memory du event_queue entre tests."""
    from app.services import event_queue

    event_queue._memory_queue.clear()
    yield
    event_queue._memory_queue.clear()


@pytest.fixture
def sample_watch_event(tmp_path):
    """Fabrique un WatchEvent pointant vers un fichier dans tmp_path."""
    import time
    from app.services.watcher import WatchEvent

    def _build(name: str = "cv_demo.txt", event_type: str = "created") -> WatchEvent:
        target = tmp_path / name
        target.write_text("demo", encoding="utf-8")
        return WatchEvent(path=target, event_type=event_type, observed_at=time.time())

    return _build
