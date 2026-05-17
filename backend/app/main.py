from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from time import perf_counter, time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import redis
from sqlalchemy import delete, func, select, text

from .db import SessionLocal, init_db
from .models import EventLog, ExtractedText, ScoreResult
from .schemas import EventCreate, EventRead, WatcherSimulateRequest, ExtractedTextCreate, ExtractedTextRead, ScoreRequest, ScoreRead
from .services import LocalFolderWatcher, WatchEvent, file_sha256, extract_text, score_texts, serialize_keywords, deserialize_keywords
from .security import enforce_security, validate_security_settings
from .settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%SZ"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("request_id", "path", "method", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    if settings.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def _get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _configure_cors(app: FastAPI) -> None:
    origins = _parse_csv(settings.cors_allow_origins)
    if not origins:
        return

    methods = _parse_csv(settings.cors_allow_methods)
    headers = _parse_csv(settings.cors_allow_headers)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=methods or ["*"],
        allow_headers=headers or ["*"],
    )


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


def _insert_score_result(cv_path: Path, job_path: Path, score: float, common: list[str]) -> ScoreRead:
    with SessionLocal() as session:
        result = ScoreResult(
            cv_path=str(cv_path),
            job_path=str(job_path),
            score=score,
            common_keywords=serialize_keywords(common),
        )
        session.add(result)
        session.commit()
        session.refresh(result)
        return ScoreRead(
            id=result.id,
            cv_path=result.cv_path,
            job_path=result.job_path,
            score=result.score,
            common_keywords=deserialize_keywords(result.common_keywords),
            created_at=result.created_at,
        )


def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def _resolve_role(path: Path) -> str | None:
    try:
        path.resolve().relative_to(Path(settings.watch_cv_dir).resolve())
        return "cv"
    except ValueError:
        pass

    try:
        path.resolve().relative_to(Path(settings.watch_job_dir).resolve())
        return "job"
    except ValueError:
        return None


def _list_candidate_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return [
        item
        for item in folder.iterdir()
        if item.is_file() and _is_supported_file(item)
    ]


def _extract_and_persist(path: Path) -> ExtractedTextRead:
    if not path.exists():
        logger.warning("File not found for extraction: %s", path)
        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=str(path),
                extraction_success=False,
                error_message="File not found",
            )
        )

    try:
        extracted = extract_text(path)
        content_hash = file_sha256(path) if path.is_file() else None

        method = path.suffix.lower().lstrip(".") or "unknown"
        success = bool(extracted and extracted.strip())

        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=str(path),
                content_hash=content_hash,
                extracted_text=extracted,
                extraction_method=method,
                extraction_success=success,
                error_message=None if success else "No text extracted",
            )
        )
    except Exception as exc:
        logger.exception("Extraction failed for %s: %s", path, exc)
        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=str(path),
                extraction_success=False,
                error_message=str(exc),
            )
        )


def _cleanup_removed_file(path: Path, role: str) -> None:
    with SessionLocal() as session:
        session.execute(
            delete(ExtractedText).where(ExtractedText.file_path == str(path))
        )
        if role == "cv":
            session.execute(delete(ScoreResult).where(ScoreResult.cv_path == str(path)))
        else:
            session.execute(delete(ScoreResult).where(ScoreResult.job_path == str(path)))
        session.commit()


def _score_against_counterparts(changed_path: Path, role: str) -> None:
    changed_result = _extract_and_persist(changed_path)
    if not changed_result.extraction_success:
        return

    changed_text = changed_result.extracted_text or ""
    if role == "cv":
        for job_path in _list_candidate_files(Path(settings.watch_job_dir)):
            job_result = _extract_and_persist(job_path)
            if not job_result.extraction_success:
                continue
            score, common = score_texts(changed_text, job_result.extracted_text or "")
            _insert_score_result(changed_path, job_path, score, common)
    else:
        for cv_path in _list_candidate_files(Path(settings.watch_cv_dir)):
            cv_result = _extract_and_persist(cv_path)
            if not cv_result.extraction_success:
                continue
            score, common = score_texts(cv_result.extracted_text or "", changed_text)
            _insert_score_result(cv_path, changed_path, score, common)


def _process_watch_event(event: WatchEvent) -> None:
    role = _resolve_role(event.path)
    if role is None:
        return

    if not event.path.exists() or not event.path.is_file():
        _cleanup_removed_file(event.path, role)
        return

    if not _is_supported_file(event.path):
        logger.info("Skipping unsupported file type: %s", event.path)
        return

    _score_against_counterparts(event.path, role)


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
        return

    try:
        _process_watch_event(event)
    except Exception as exc:  # pragma: no cover
        logger.exception("watcher processing failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    init_db()
    app.state.started_at = time()
    watched_folders = [Path(settings.watch_cv_dir), Path(settings.watch_job_dir)]
    watcher = LocalFolderWatcher(folders=watched_folders, callback=_on_watch_event)
    watcher.start()
    app.state.watcher = watcher
    try:
        yield
    finally:
        watcher.stop()


_configure_logging()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
_configure_cors(app)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid4()))
    request.state.request_id = request_id
    start = perf_counter()
    enforce_security(request)
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    duration_ms = (perf_counter() - start) * 1000
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": settings.app_version,
    }


@app.get("/ready")
def readiness() -> dict[str, str]:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        logger.error("db readiness failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")

    try:
        client = _get_redis_client()
        client.ping()
    except Exception as exc:  # pragma: no cover
        logger.error("redis readiness failed: %s", exc)
        raise HTTPException(status_code=503, detail="redis unavailable")

    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> dict[str, float | int]:
    uptime = int(time() - app.state.started_at)
    with SessionLocal() as session:
        events = session.scalar(select(func.count()).select_from(EventLog))
        extractions = session.scalar(select(func.count()).select_from(ExtractedText))
        scores = session.scalar(select(func.count()).select_from(ScoreResult))
    return {
        "uptime_seconds": uptime,
        "event_count": int(events or 0),
        "extraction_count": int(extractions or 0),
        "score_count": int(scores or 0),
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




@app.get("/extractions", response_model=list[ExtractedTextRead])
def list_extractions(limit: int = 50) -> list[ExtractedTextRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(ExtractedText).order_by(ExtractedText.id.desc()).limit(safe_limit)
        ).all()
        return [ExtractedTextRead.model_validate(row) for row in rows]



@app.post("/score", response_model=ScoreRead)
def score_match(payload: ScoreRequest) -> ScoreRead:
    cv_path = Path(payload.cv_path)
    job_path = Path(payload.job_path)

    if not cv_path.exists():
        raise HTTPException(status_code=404, detail="CV file not found")
    if not job_path.exists():
        raise HTTPException(status_code=404, detail="JOB file not found")

    cv_text = extract_text(cv_path)
    job_text = extract_text(job_path)
    score, common = score_texts(cv_text, job_text)
    return _insert_score_result(cv_path, job_path, score, common)


@app.get("/scores", response_model=list[ScoreRead])
def list_scores(limit: int = 50) -> list[ScoreRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(ScoreResult).order_by(ScoreResult.id.desc()).limit(safe_limit)
        ).all()
        return [
            ScoreRead(
                id=row.id,
                cv_path=row.cv_path,
                job_path=row.job_path,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
            )
            for row in rows
        ]


@app.post("/maintenance/cleanup")
def cleanup_retention() -> dict[str, int]:
    deleted_events = 0
    deleted_extractions = 0
    deleted_scores = 0

    with SessionLocal() as session:
        if settings.retention_event_days > 0:
            cutoff = text(
                f"now() - interval '{int(settings.retention_event_days)} days'"
            )
            deleted_events = session.execute(
                delete(EventLog).where(EventLog.created_at < cutoff)
            ).rowcount or 0

        if settings.retention_extraction_days > 0:
            cutoff = text(
                f"now() - interval '{int(settings.retention_extraction_days)} days'"
            )
            deleted_extractions = session.execute(
                delete(ExtractedText).where(ExtractedText.created_at < cutoff)
            ).rowcount or 0

        if settings.retention_score_days > 0:
            cutoff = text(
                f"now() - interval '{int(settings.retention_score_days)} days'"
            )
            deleted_scores = session.execute(
                delete(ScoreResult).where(ScoreResult.created_at < cutoff)
            ).rowcount or 0

        session.commit()

    return {
        "deleted_events": deleted_events,
        "deleted_extractions": deleted_extractions,
        "deleted_scores": deleted_scores,
    }

@app.post("/extract", response_model=ExtractedTextRead)
def ingest_and_extract(file_path: str) -> ExtractedTextRead:
    return _extract_and_persist(Path(file_path))
