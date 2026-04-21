from contextlib import asynccontextmanager
import logging
from pathlib import Path
from time import time

from fastapi import FastAPI
from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import EventLog
from .schemas import EventCreate, EventRead, WatcherSimulateRequest
from .services import LocalFolderWatcher, WatchEvent, file_sha256
from .settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _insert_event(payload: EventCreate) -> EventRead:
    with SessionLocal() as session:
        event = EventLog(
            source=payload.source,
            event_type=payload.event_type,
            path=payload.path,
            fingerprint=payload.fingerprint,
            observed_at=payload.observed_at,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return EventRead.model_validate(event)


def _on_watch_event(event: WatchEvent) -> None:
    try:
        fingerprint: str | None = None
        if event.path.exists() and event.path.is_file():
            fingerprint = file_sha256(event.path)

        _insert_event(
            EventCreate(
                source="watcher",
                event_type=event.event_type,
                path=str(event.path),
                fingerprint=fingerprint,
                observed_at=event.observed_at,
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("watcher callback failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    watched_folders = [Path(settings.watch_cv_dir), Path(settings.watch_job_dir)]
    watcher = LocalFolderWatcher(folders=watched_folders, callback=_on_watch_event)
    watcher.start()
    app.state.watcher = watcher
    try:
        yield
    finally:
        watcher.stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.environment,
    }


@app.post("/events", response_model=EventRead)
def create_event(payload: EventCreate) -> EventRead:
    return _insert_event(payload)


@app.get("/events", response_model=list[EventRead])
def list_events(limit: int = 50) -> list[EventRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(EventLog).order_by(EventLog.id.desc()).limit(safe_limit)
        ).all()
        return [EventRead.model_validate(row) for row in rows]


@app.post("/watcher/simulate")
def simulate_watcher_event(payload: WatcherSimulateRequest) -> dict[str, str]:
    folder = Path(settings.watch_cv_dir)
    if payload.folder == "job":
        folder = Path(settings.watch_job_dir)

    folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(payload.filename).name
    target = folder / safe_name
    target.write_text(payload.content, encoding="utf-8")

    return {
        "status": "written",
        "path": str(target),
        "timestamp": str(time()),
    }
