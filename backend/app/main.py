from contextlib import asynccontextmanager
import logging
from pathlib import Path
from time import time

from fastapi import FastAPI
from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import EventLog, ExtractedText
from .schemas import EventCreate, EventRead, WatcherSimulateRequest, ExtractedTextCreate, ExtractedTextRead
from .services import LocalFolderWatcher, WatchEvent, file_sha256, extract_text
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


def _upsert_extraction_result(payload: ExtractedTextCreate) -> ExtractedTextRead:
    with SessionLocal() as session:
        existing = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == payload.file_path)
        )

        if existing:
            existing.content_hash = payload.content_hash
            existing.extracted_text = payload.extracted_text
            existing.extraction_method = payload.extraction_method
            existing.extraction_success = payload.extraction_success
            existing.error_message = payload.error_message
            session.commit()
            session.refresh(existing)
            return ExtractedTextRead.model_validate(existing)

        extraction = ExtractedText(
            file_path=payload.file_path,
            content_hash=payload.content_hash,
            extracted_text=payload.extracted_text,
            extraction_method=payload.extraction_method,
            extraction_success=payload.extraction_success,
            error_message=payload.error_message,
        )
        session.add(extraction)
        session.commit()
        session.refresh(extraction)
        return ExtractedTextRead.model_validate(extraction)


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


@app.post("/extract", response_model=ExtractedTextRead)
def ingest_and_extract(file_path: str) -> ExtractedTextRead:
    path = Path(file_path)

    if not path.exists():
        logger.warning("File not found for extraction: %s", file_path)
        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=file_path,
                extraction_success=False,
                error_message="File not found",
            )
        )

    try:
        extracted = extract_text(path)
        content_hash = file_sha256(path) if path.is_file() else None

        method = path.suffix.lower().lstrip(".")
        if not method:
            method = "unknown"

        success = bool(extracted and extracted.strip())

        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=file_path,
                content_hash=content_hash,
                extracted_text=extracted,
                extraction_method=method,
                extraction_success=success,
                error_message=None if success else "No text extracted",
            )
        )
    except Exception as exc:
        logger.exception("Extraction failed for %s: %s", file_path, exc)
        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=file_path,
                extraction_success=False,
                error_message=str(exc),
            )
        )
