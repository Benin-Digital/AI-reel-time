from fastapi import FastAPI
from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import EventLog
from .schemas import EventCreate, EventRead
from .settings import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.environment,
    }


@app.post("/events", response_model=EventRead)
def create_event(payload: EventCreate) -> EventRead:
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


@app.get("/events", response_model=list[EventRead])
def list_events(limit: int = 50) -> list[EventRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(EventLog).order_by(EventLog.id.desc()).limit(safe_limit)
        ).all()
        return [EventRead.model_validate(row) for row in rows]
