from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import tempfile
from time import perf_counter, time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import redis
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .auth import (
    authenticate_user,
    create_access_token,
    ensure_bootstrap_user,
    hash_password,
)
from .models import (
    EventLog,
    ExtractedText,
    ScoreResult,
    CvDocument,
    JobDocument,
    MatchResult,
    CvEmbedding,
    JobEmbedding,
    User,
)
from .schemas import (
    EventCreate,
    EventRead,
    WatcherSimulateRequest,
    IngestDeleteRequest,
    IngestDeleteBatchRequest,
    ExtractedTextCreate,
    ExtractedTextRead,
    ScoreRequest,
    ScoreRead,
    CvDocumentRead,
    CvDocumentDetailRead,
    JobDocumentRead,
    JobDocumentDetailRead,
    MatchRead,
    SearchRequest,
    SearchHit,
    AuthLoginRequest,
    AuthLoginResponse,
    MatchExplainRead,
    UserCreate,
    UserUpdate,
    UserRead,
)
from .services import (
    LocalFolderWatcher,
    WatchEvent,
    EventWorker,
    enqueue_event,
    file_sha256,
    embed_text,
    embed_texts,
    extract_text,
    score_texts,
    serialize_keywords,
    deserialize_keywords,
    get_queue_status,
)
from .services.explain import build_match_explanation
from .security import enforce_security, validate_security_settings
from .settings import get_settings
from .observability import (
    CONTENT_TYPE_LATEST,
    record_request,
    render_metrics,
    update_runtime_metrics,
)

settings = get_settings()
logger = logging.getLogger(__name__)
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}


def _resolve_document_pdf_path(doc_path: str, folder: str) -> Path:
    pdf_path = Path(doc_path).resolve()
    root = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir).resolve()
    try:
        pdf_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="PDF document not found") from exc

    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Document is not a PDF")

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF document not found")

    return pdf_path


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


def _write_upload_to_temp(upload: UploadFile, target_dir: Path, safe_name: str) -> Path:
    max_bytes = max(0, settings.upload_max_mb) * 1024 * 1024
    temp_path: Path | None = None
    with tempfile.NamedTemporaryFile(
        prefix=f".{safe_name}.",
        dir=target_dir,
        delete=False,
    ) as temp_file:
        total = 0
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes and total > max_bytes:
                temp_path = Path(temp_file.name)
                temp_file.flush()
                temp_file.close()
                if temp_path.exists():
                    temp_path.unlink()
                raise HTTPException(status_code=413, detail="File too large")
            temp_file.write(chunk)
        temp_path = Path(temp_file.name)
    return temp_path


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


def _document_status(result: ExtractedTextRead) -> tuple[str, str | None]:
    if result.extraction_success:
        return "ready", None
    return "failed", result.error_message or "extraction failed"


def _upsert_cv_document(path: Path, extraction: ExtractedTextRead) -> CvDocumentRead:
    status, last_error = _document_status(extraction)
    with SessionLocal() as session:
        existing = session.scalar(
            select(CvDocument).where(CvDocument.path == str(path))
        )
        if existing:
            existing.content_hash = extraction.content_hash
            existing.status = status
            existing.last_error = last_error
            session.commit()
            session.refresh(existing)
            return CvDocumentRead.model_validate(existing)

        doc = CvDocument(
            path=str(path),
            content_hash=extraction.content_hash,
            status=status,
            last_error=last_error,
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return CvDocumentRead.model_validate(doc)


def _upsert_job_document(path: Path, extraction: ExtractedTextRead) -> JobDocumentRead:
    status, last_error = _document_status(extraction)
    with SessionLocal() as session:
        existing = session.scalar(
            select(JobDocument).where(JobDocument.path == str(path))
        )
        if existing:
            existing.content_hash = extraction.content_hash
            existing.status = status
            existing.last_error = last_error
            session.commit()
            session.refresh(existing)
            return JobDocumentRead.model_validate(existing)

        doc = JobDocument(
            path=str(path),
            content_hash=extraction.content_hash,
            status=status,
            last_error=last_error,
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return JobDocumentRead.model_validate(doc)


def _upsert_match_result(cv_id: int, job_id: int, score: float, common: list[str]) -> MatchRead:
    with SessionLocal() as session:
        existing = session.scalar(
            select(MatchResult).where(
                MatchResult.cv_id == cv_id,
                MatchResult.job_id == job_id,
            )
        )
        if existing:
            existing.score = score
            existing.common_keywords = serialize_keywords(common)
            session.commit()
            session.refresh(existing)
            return MatchRead(
                id=existing.id,
                cv_id=existing.cv_id,
                job_id=existing.job_id,
                score=existing.score,
                common_keywords=deserialize_keywords(existing.common_keywords),
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )

        match = MatchResult(
            cv_id=cv_id,
            job_id=job_id,
            score=score,
            common_keywords=serialize_keywords(common),
        )
        session.add(match)
        session.commit()
        session.refresh(match)
        return MatchRead(
            id=match.id,
            cv_id=match.cv_id,
            job_id=match.job_id,
            score=match.score,
            common_keywords=deserialize_keywords(match.common_keywords),
            created_at=match.created_at,
            updated_at=match.updated_at,
        )


def _upsert_cv_embedding(
    cv_id: int,
    content_hash: str | None,
    embedding: list[float],
    session: Session | None = None,
) -> None:
    if len(embedding) != settings.embedding_dim:
        logger.warning("embedding dim mismatch for cv %s", cv_id)
        return

    def _apply(target_session):
        existing = target_session.scalar(select(CvEmbedding).where(CvEmbedding.cv_id == cv_id))
        if existing and existing.content_hash == content_hash:
            return
        if existing:
            existing.content_hash = content_hash
            existing.embedding = embedding
            target_session.commit()
            return
        row = CvEmbedding(cv_id=cv_id, content_hash=content_hash, embedding=embedding)
        target_session.add(row)
        target_session.commit()

    if session is not None:
        _apply(session)
        return

    with SessionLocal() as local_session:
        _apply(local_session)


def _upsert_job_embedding(
    job_id: int,
    content_hash: str | None,
    embedding: list[float],
    session: Session | None = None,
) -> None:
    if len(embedding) != settings.embedding_dim:
        logger.warning("embedding dim mismatch for job %s", job_id)
        return

    def _apply(target_session):
        existing = target_session.scalar(select(JobEmbedding).where(JobEmbedding.job_id == job_id))
        if existing and existing.content_hash == content_hash:
            return
        if existing:
            existing.content_hash = content_hash
            existing.embedding = embedding
            target_session.commit()
            return
        row = JobEmbedding(job_id=job_id, content_hash=content_hash, embedding=embedding)
        target_session.add(row)
        target_session.commit()

    if session is not None:
        _apply(session)
        return

    with SessionLocal() as local_session:
        _apply(local_session)


def _vector_score(distance: float) -> float:
    similarity = max(0.0, 1.0 - distance)
    return round(similarity * 100, 2)


def _require_admin(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def _require_superadmin(request: Request) -> User:
    user = _require_admin(request)
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin role required")
    return user


def _hybrid_score(vector_score: float, lexical_score: float) -> float:
    if not settings.hybrid_scoring_enabled:
        return vector_score
    weight_sum = settings.hybrid_vector_weight + settings.hybrid_lexical_weight
    if weight_sum <= 0:
        return vector_score
    combined = (
        vector_score * settings.hybrid_vector_weight
        + lexical_score * settings.hybrid_lexical_weight
    ) / weight_sum
    return round(combined, 2)


def _hybrid_score_with_weights(
    vector_score: float,
    lexical_score: float,
    vector_weight: float,
    lexical_weight: float,
) -> float:
    weight_sum = vector_weight + lexical_weight
    if weight_sum <= 0:
        return vector_score
    combined = (vector_score * vector_weight + lexical_score * lexical_weight) / weight_sum
    return round(combined, 2)


def _vector_match_cv(
    cv_doc: CvDocumentRead,
    extraction: ExtractedTextRead,
) -> bool:
    text_value = (extraction.extracted_text or "").strip()
    if not text_value:
        return False

    try:
        vector = embed_text(text_value)
    except Exception as exc:
        logger.warning("embedding failed for cv %s: %s", cv_doc.id, exc)
        return False

    if not vector:
        return False

    _upsert_cv_embedding(cv_doc.id, extraction.content_hash, vector)

    with SessionLocal() as session:
        distance = JobEmbedding.embedding.cosine_distance(vector).label("distance")
        rows = session.execute(
            select(
                JobEmbedding.job_id,
                JobDocument.path,
                ExtractedText.extracted_text,
                distance,
            )
            .join(JobDocument, JobEmbedding.job_id == JobDocument.id)
            .join(ExtractedText, ExtractedText.file_path == JobDocument.path, isouter=True)
            .order_by(distance.asc())
            .limit(settings.embedding_top_k)
        ).all()

    if not rows:
        return False

    for row in rows:
        job_text = (row.extracted_text or "").strip()
        lexical_score = 0.0
        common: list[str] = []
        if job_text:
            lexical_score, common = score_texts(text_value, job_text)
        vector_score = _vector_score(float(row.distance))
        score = _hybrid_score(vector_score, lexical_score)
        _insert_score_result(Path(cv_doc.path), Path(row.path), score, common)
        _upsert_match_result(cv_doc.id, row.job_id, score, common)

    return True


def _vector_match_job(
    job_doc: JobDocumentRead,
    extraction: ExtractedTextRead,
) -> bool:
    text_value = (extraction.extracted_text or "").strip()
    if not text_value:
        return False

    try:
        vector = embed_text(text_value)
    except Exception as exc:
        logger.warning("embedding failed for job %s: %s", job_doc.id, exc)
        return False

    if not vector:
        return False

    _upsert_job_embedding(job_doc.id, extraction.content_hash, vector)

    with SessionLocal() as session:
        distance = CvEmbedding.embedding.cosine_distance(vector).label("distance")
        rows = session.execute(
            select(
                CvEmbedding.cv_id,
                CvDocument.path,
                ExtractedText.extracted_text,
                distance,
            )
            .join(CvDocument, CvEmbedding.cv_id == CvDocument.id)
            .join(ExtractedText, ExtractedText.file_path == CvDocument.path, isouter=True)
            .order_by(distance.asc())
            .limit(settings.embedding_top_k)
        ).all()

    if not rows:
        return False

    for row in rows:
        cv_text = (row.extracted_text or "").strip()
        lexical_score = 0.0
        common: list[str] = []
        if cv_text:
            lexical_score, common = score_texts(cv_text, text_value)
        vector_score = _vector_score(float(row.distance))
        score = _hybrid_score(vector_score, lexical_score)
        _insert_score_result(Path(row.path), Path(job_doc.path), score, common)
        _upsert_match_result(row.cv_id, job_doc.id, score, common)

    return True


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

    content_hash = file_sha256(path) if path.is_file() else None
    existing = None
    with SessionLocal() as session:
        existing = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == str(path))
        )
        if existing and existing.content_hash == content_hash and existing.extraction_success:
            return ExtractedTextRead.model_validate(existing)

    try:
        extracted = extract_text(path)
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
                content_hash=content_hash,
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
            doc = session.scalar(select(CvDocument).where(CvDocument.path == str(path)))
            if doc:
                session.execute(delete(MatchResult).where(MatchResult.cv_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.cv_path == str(path)))
        else:
            doc = session.scalar(select(JobDocument).where(JobDocument.path == str(path)))
            if doc:
                session.execute(delete(MatchResult).where(MatchResult.job_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.job_path == str(path)))
        session.commit()


def _score_against_counterparts(changed_path: Path, role: str) -> None:
    changed_result = _extract_and_persist(changed_path)
    if role == "cv":
        previous_hash = None
        with SessionLocal() as session:
            previous = session.scalar(
                select(CvDocument).where(CvDocument.path == str(changed_path))
            )
            previous_hash = previous.content_hash if previous else None
            previous_status = previous.status if previous else None

        cv_doc = _upsert_cv_document(changed_path, changed_result)
        if not changed_result.extraction_success:
            return

        if (
            previous_hash
            and changed_result.content_hash == previous_hash
            and previous_status == "ready"
        ):
            return

        if settings.embedding_enabled:
            if _vector_match_cv(cv_doc, changed_result):
                return

        changed_text = changed_result.extracted_text or ""
        for job_path in _list_candidate_files(Path(settings.watch_job_dir)):
            job_result = _extract_and_persist(job_path)
            job_doc = _upsert_job_document(job_path, job_result)
            if not job_result.extraction_success:
                continue
            score, common = score_texts(changed_text, job_result.extracted_text or "")
            _insert_score_result(changed_path, job_path, score, common)
            _upsert_match_result(cv_doc.id, job_doc.id, score, common)
    else:
        previous_hash = None
        with SessionLocal() as session:
            previous = session.scalar(
                select(JobDocument).where(JobDocument.path == str(changed_path))
            )
            previous_hash = previous.content_hash if previous else None
            previous_status = previous.status if previous else None

        job_doc = _upsert_job_document(changed_path, changed_result)
        if not changed_result.extraction_success:
            return

        if (
            previous_hash
            and changed_result.content_hash == previous_hash
            and previous_status == "ready"
        ):
            return

        if settings.embedding_enabled:
            if _vector_match_job(job_doc, changed_result):
                return

        changed_text = changed_result.extracted_text or ""
        for cv_path in _list_candidate_files(Path(settings.watch_cv_dir)):
            cv_result = _extract_and_persist(cv_path)
            cv_doc = _upsert_cv_document(cv_path, cv_result)
            if not cv_result.extraction_success:
                continue
            score, common = score_texts(cv_result.extracted_text or "", changed_text)
            _insert_score_result(cv_path, changed_path, score, common)
            _upsert_match_result(cv_doc.id, job_doc.id, score, common)


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
        if not enqueue_event(event):
            _process_watch_event(event)
    except Exception as exc:  # pragma: no cover
        logger.exception("watcher enqueue failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    init_db()
    with SessionLocal() as session:
        ensure_bootstrap_user(session)
    app.state.started_at = time()
    watched_folders = [Path(settings.watch_cv_dir), Path(settings.watch_job_dir)]
    watcher = LocalFolderWatcher(folders=watched_folders, callback=_on_watch_event)
    watcher.start()
    worker = EventWorker(
        handler=_process_watch_event,
        max_retries=settings.worker_max_retries,
        retry_base_delay=settings.worker_retry_base_delay,
        retry_max_delay=settings.worker_retry_max_delay,
        ack_on_failure=settings.queue_ack_on_failure,
    )
    worker.start()
    app.state.watcher = watcher
    app.state.worker = worker
    try:
        yield
    finally:
        worker.stop()
        watcher.stop()


_configure_logging()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
_configure_cors(app)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid4()))
    request.state.request_id = request_id
    start = perf_counter()
    try:
        enforce_security(request)
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        response.headers["x-request-id"] = request_id
        return response
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    duration_ms = (perf_counter() - start) * 1000
    route = request.scope.get("route")
    route_path = route.path if route and hasattr(route, "path") else request.url.path
    record_request(
        request.method,
        route_path,
        response.status_code,
        duration_ms / 1000,
    )
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
def metrics() -> dict[str, float | int | bool | str | None]:
    uptime = int(time() - app.state.started_at)
    queue_status = get_queue_status()
    worker = getattr(app.state, "worker", None)
    with SessionLocal() as session:
        events = session.scalar(select(func.count()).select_from(EventLog))
        extractions = session.scalar(select(func.count()).select_from(ExtractedText))
        scores = session.scalar(select(func.count()).select_from(ScoreResult))
    return {
        "uptime_seconds": uptime,
        "event_count": int(events or 0),
        "extraction_count": int(extractions or 0),
        "score_count": int(scores or 0),
        "redis_available": bool(queue_status.get("redis_available", False)),
        "redis_queue_length": int(queue_status.get("redis_queue_length", 0)),
        "memory_queue_length": int(queue_status.get("memory_queue_length", 0)),
        "worker_alive": bool(worker.is_running) if worker is not None else False,
        "worker_last_error": worker.last_error if worker is not None else None,
    }


@app.get("/metrics/prometheus")
def metrics_prometheus() -> Response:
    queue_status = get_queue_status()
    worker = getattr(app.state, "worker", None)
    with SessionLocal() as session:
        events = session.scalar(select(func.count()).select_from(EventLog))
        extractions = session.scalar(select(func.count()).select_from(ExtractedText))
        scores = session.scalar(select(func.count()).select_from(ScoreResult))
        matches = session.scalar(select(func.count()).select_from(MatchResult))
        cv_documents = session.scalar(select(func.count()).select_from(CvDocument))
        job_documents = session.scalar(select(func.count()).select_from(JobDocument))
        cv_embeddings = session.scalar(select(func.count()).select_from(CvEmbedding))
        job_embeddings = session.scalar(select(func.count()).select_from(JobEmbedding))

    update_runtime_metrics(
        queue_status,
        bool(worker.is_running) if worker is not None else False,
        {
            "events": int(events or 0),
            "extractions": int(extractions or 0),
            "scores": int(scores or 0),
            "matches": int(matches or 0),
            "cv_documents": int(cv_documents or 0),
            "job_documents": int(job_documents or 0),
            "cv_embeddings": int(cv_embeddings or 0),
            "job_embeddings": int(job_embeddings or 0),
        },
        settings.embedding_enabled,
    )
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.get("/queue-status")
def queue_status() -> dict[str, int | bool]:
    return get_queue_status()


@app.get("/worker-status")
def worker_status() -> dict[str, bool | str | None]:
    worker = getattr(app.state, "worker", None)
    if worker is None:
        raise HTTPException(status_code=503, detail="worker unavailable")
    return {
        "alive": worker.is_running,
        "last_error": worker.last_error,
    }


@app.post("/auth/login", response_model=AuthLoginResponse)
def login(payload: AuthLoginRequest) -> AuthLoginResponse:
    with SessionLocal() as session:
        user = authenticate_user(session, payload.email, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(user)
        return AuthLoginResponse(
            access_token=token,
            user=UserRead.model_validate(user),
        )


@app.get("/auth/me", response_model=UserRead)
def get_me(request: Request) -> UserRead:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserRead.model_validate(user)


@app.get("/auth/users", response_model=list[UserRead])
def list_users(request: Request) -> list[UserRead]:
    _require_admin(request)
    with SessionLocal() as session:
        rows = session.scalars(select(User).order_by(User.id.asc())).all()
        return [UserRead.model_validate(row) for row in rows]


@app.post("/auth/users", response_model=UserRead)
def create_user(payload: UserCreate, request: Request) -> UserRead:
    current_user = _require_admin(request)
    if current_user.role == "admin" and payload.role != "member":
        raise HTTPException(status_code=403, detail="Admin can only create member accounts")
    with SessionLocal() as session:
        existing = session.scalar(select(User).where(User.email == payload.email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="User already exists")
        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)


@app.patch("/auth/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserUpdate, request: Request) -> UserRead:
    current_user = _require_admin(request)
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role == "superadmin":
            raise HTTPException(status_code=403, detail="Superadmin account is protected")

        if current_user.role == "admin":
            if user.role != "member":
                raise HTTPException(status_code=403, detail="Admin can only manage member accounts")
            if payload.role is not None and payload.role != "member":
                raise HTTPException(status_code=403, detail="Admin can only keep member role")

        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active

        session.add(user)
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)


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


@app.post("/ingest")
def ingest_file(
    folder: str = Form(...),
    upload: UploadFile = File(...),
    filename: str | None = Form(None),
) -> dict[str, str]:
    if folder not in {"cv", "job"}:
        raise HTTPException(status_code=400, detail="Invalid folder")

    target_dir = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    raw_name = filename or upload.filename or ""
    safe_name = Path(raw_name).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    target_path = target_dir / safe_name
    temp_path: Path | None = None
    try:
        temp_path = _write_upload_to_temp(upload, target_dir, safe_name)
    finally:
        try:
            upload.file.close()
        except Exception:
            pass

    if temp_path is None:
        raise HTTPException(status_code=500, detail="Upload failed")

    try:
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    _on_watch_event(
        WatchEvent(
            path=target_path,
            event_type="ingest",
            observed_at=time(),
        )
    )
    return {
        "status": "stored",
        "path": str(target_path),
    }


@app.post("/ingest/delete")
def ingest_delete(payload: IngestDeleteRequest) -> dict[str, str]:
    folder = payload.folder
    target_dir = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(payload.filename).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    target_path = target_dir / safe_name
    status = "missing"
    if target_path.exists():
        target_path.unlink()
        status = "deleted"

    delete_event = WatchEvent(
        path=target_path,
        event_type="deleted",
        observed_at=time(),
    )
    try:
        _on_watch_event(delete_event)
    except Exception as exc:  # pragma: no cover
        logger.warning("ingest delete enqueue failed: %s", exc)

    return {
        "status": status,
        "path": str(target_path),
    }


@app.post("/ingest/delete-batch")
def ingest_delete_batch(payload: IngestDeleteBatchRequest) -> dict[str, list[dict[str, str]]]:
    folder = payload.folder
    target_dir = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, str]] = []
    for raw_name in payload.filenames:
        safe_name = Path(raw_name).name
        if not safe_name:
            results.append({"filename": raw_name, "status": "invalid"})
            continue

        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            results.append({"filename": safe_name, "status": "unsupported"})
            continue

        target_path = target_dir / safe_name
        status = "missing"
        if target_path.exists():
            target_path.unlink()
            status = "deleted"

        delete_event = WatchEvent(
            path=target_path,
            event_type="deleted",
            observed_at=time(),
        )
        try:
            _on_watch_event(delete_event)
        except Exception as exc:  # pragma: no cover
            logger.warning("ingest delete enqueue failed: %s", exc)

        results.append({"filename": safe_name, "status": status})

    return {"status": "ok", "results": results}




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


@app.get("/cv-documents", response_model=list[CvDocumentRead])
def list_cv_documents(
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    query: str | None = None,
) -> list[CvDocumentRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(CvDocument)
    if status:
        stmt = stmt.where(CvDocument.status == status)
    if query:
        search_expr = f"%{query}%"
        stmt = stmt.join(
            ExtractedText,
            ExtractedText.file_path == CvDocument.path,
            isouter=True,
        ).where(
            or_(
                CvDocument.path.ilike(search_expr),
                ExtractedText.extracted_text.ilike(search_expr),
            )
        )
    stmt = stmt.order_by(CvDocument.id.desc()).offset(safe_offset).limit(safe_size)
    with SessionLocal() as session:
        rows = session.scalars(stmt).all()
        return [CvDocumentRead.model_validate(row) for row in rows]


@app.get("/cv-documents/{doc_id}", response_model=CvDocumentRead)
def get_cv_document(doc_id: int) -> CvDocumentRead:
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")
        return CvDocumentRead.model_validate(doc)


@app.get("/cv-documents/{doc_id}/details", response_model=CvDocumentDetailRead)
def get_cv_document_details(doc_id: int, limit: int = 6) -> CvDocumentDetailRead:
    safe_limit = max(1, min(limit, 50))
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")

        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )
        match_rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.cv_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()

        match_count = session.scalar(
            select(func.count()).select_from(MatchResult).where(MatchResult.cv_id == doc_id)
        ) or 0
        average_score = session.scalar(
            select(func.avg(MatchResult.score)).where(MatchResult.cv_id == doc_id)
        )

        keyword_counts: dict[str, int] = {}
        for row in match_rows:
            for keyword in deserialize_keywords(row.common_keywords):
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        top_keywords = [
            keyword
            for keyword, _ in sorted(
                keyword_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:12]
        ]

        return CvDocumentDetailRead(
            id=doc.id,
            path=doc.path,
            content_hash=doc.content_hash,
            status=doc.status,
            last_error=doc.last_error,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            match_count=match_count,
            average_score=round(float(average_score), 2) if average_score is not None else None,
            top_keywords=top_keywords,
            extraction=ExtractedTextRead.model_validate(extraction) if extraction else None,
            top_matches=[
                MatchRead(
                    id=row.id,
                    cv_id=row.cv_id,
                    job_id=row.job_id,
                    score=row.score,
                    common_keywords=deserialize_keywords(row.common_keywords),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in match_rows
            ],
        )


@app.get("/cv-documents/{doc_id}/pdf")
def get_cv_document_pdf(doc_id: int) -> FileResponse:
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")

    pdf_path = _resolve_document_pdf_path(doc.path, "cv")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/job-documents", response_model=list[JobDocumentRead])
def list_job_documents(
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    query: str | None = None,
) -> list[JobDocumentRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(JobDocument)
    if status:
        stmt = stmt.where(JobDocument.status == status)
    if query:
        search_expr = f"%{query}%"
        stmt = stmt.join(
            ExtractedText,
            ExtractedText.file_path == JobDocument.path,
            isouter=True,
        ).where(
            or_(
                JobDocument.path.ilike(search_expr),
                ExtractedText.extracted_text.ilike(search_expr),
            )
        )
    stmt = stmt.order_by(JobDocument.id.desc()).offset(safe_offset).limit(safe_size)
    with SessionLocal() as session:
        rows = session.scalars(stmt).all()
        return [JobDocumentRead.model_validate(row) for row in rows]


@app.get("/job-documents/{doc_id}", response_model=JobDocumentRead)
def get_job_document(doc_id: int) -> JobDocumentRead:
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")
        return JobDocumentRead.model_validate(doc)


@app.get("/job-documents/{doc_id}/details", response_model=JobDocumentDetailRead)
def get_job_document_details(doc_id: int, limit: int = 6) -> JobDocumentDetailRead:
    safe_limit = max(1, min(limit, 50))
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")

        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )
        match_rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.job_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()

        match_count = session.scalar(
            select(func.count()).select_from(MatchResult).where(MatchResult.job_id == doc_id)
        ) or 0
        average_score = session.scalar(
            select(func.avg(MatchResult.score)).where(MatchResult.job_id == doc_id)
        )

        keyword_counts: dict[str, int] = {}
        for row in match_rows:
            for keyword in deserialize_keywords(row.common_keywords):
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        top_keywords = [
            keyword
            for keyword, _ in sorted(
                keyword_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:12]
        ]

        return JobDocumentDetailRead(
            id=doc.id,
            path=doc.path,
            content_hash=doc.content_hash,
            status=doc.status,
            last_error=doc.last_error,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            match_count=match_count,
            average_score=round(float(average_score), 2) if average_score is not None else None,
            top_keywords=top_keywords,
            extraction=ExtractedTextRead.model_validate(extraction) if extraction else None,
            top_matches=[
                MatchRead(
                    id=row.id,
                    cv_id=row.cv_id,
                    job_id=row.job_id,
                    score=row.score,
                    common_keywords=deserialize_keywords(row.common_keywords),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in match_rows
            ],
        )


@app.get("/job-documents/{doc_id}/pdf")
def get_job_document_pdf(doc_id: int) -> FileResponse:
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")

    pdf_path = _resolve_document_pdf_path(doc.path, "job")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/extractions/path", response_model=ExtractedTextRead)
def get_extraction_by_path(path: str) -> ExtractedTextRead:
    with SessionLocal() as session:
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == path)
        )
        if not extraction:
            raise HTTPException(status_code=404, detail="Extraction not found")
        return ExtractedTextRead.model_validate(extraction)


@app.get("/cv-documents/{doc_id}/matches", response_model=list[MatchRead])
def list_matches_for_cv(doc_id: int, limit: int = 50) -> list[MatchRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.cv_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@app.get("/job-documents/{doc_id}/matches", response_model=list[MatchRead])
def list_matches_for_job(doc_id: int, limit: int = 50) -> list[MatchRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.job_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@app.get("/matches", response_model=list[MatchRead])
def list_matches(
    page: int = 1,
    page_size: int = 25,
    cv_id: int | None = None,
    job_id: int | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    sort_by: str = "score_desc",
    search: str | None = None,
) -> list[MatchRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(MatchResult)
    if cv_id is not None:
        stmt = stmt.where(MatchResult.cv_id == cv_id)
    if job_id is not None:
        stmt = stmt.where(MatchResult.job_id == job_id)
    if min_score is not None:
        stmt = stmt.where(MatchResult.score >= min_score)
    if max_score is not None:
        stmt = stmt.where(MatchResult.score <= max_score)
    if search:
        search_expr = f"%{search}%"
        stmt = stmt.join(CvDocument, MatchResult.cv_id == CvDocument.id)
        stmt = stmt.join(JobDocument, MatchResult.job_id == JobDocument.id)
        stmt = stmt.where(
            or_(
                MatchResult.common_keywords.ilike(search_expr),
                CvDocument.path.ilike(search_expr),
                JobDocument.path.ilike(search_expr),
            )
        )

    if sort_by == "score_asc":
        stmt = stmt.order_by(MatchResult.score.asc())
    elif sort_by == "created_at_asc":
        stmt = stmt.order_by(MatchResult.created_at.asc())
    elif sort_by == "created_at_desc":
        stmt = stmt.order_by(MatchResult.created_at.desc())
    else:
        stmt = stmt.order_by(MatchResult.score.desc())

    with SessionLocal() as session:
        rows = session.scalars(stmt.offset(safe_offset).limit(safe_size)).all()
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@app.get("/matches/{match_id}", response_model=MatchRead)
def get_match(match_id: int) -> MatchRead:
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        return MatchRead(
            id=match.id,
            cv_id=match.cv_id,
            job_id=match.job_id,
            score=match.score,
            common_keywords=deserialize_keywords(match.common_keywords),
            created_at=match.created_at,
            updated_at=match.updated_at,
        )


@app.get("/matches/{match_id}/explain", response_model=MatchExplainRead)
def explain_match(match_id: int) -> MatchExplainRead:
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")

        cv_doc = session.get(CvDocument, match.cv_id)
        job_doc = session.get(JobDocument, match.job_id)
        if not cv_doc or not job_doc:
            raise HTTPException(status_code=404, detail="Document not found")

        cv_extract = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == cv_doc.path)
        )
        job_extract = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == job_doc.path)
        )

        cv_text = cv_extract.extracted_text if cv_extract else ""
        job_text = job_extract.extracted_text if job_extract else ""
        keywords = deserialize_keywords(match.common_keywords)

        details = build_match_explanation(cv_text, job_text, match.score, keywords)
        return MatchExplainRead(
            match_id=match.id,
            score=match.score,
            summary=str(details["summary"]),
            why_match=list(details["why_match"]),
            vigilance=list(details["vigilance"]),
            evidence=list(details["evidence"]),
            keyword_hits=list(details["keyword_hits"]),
        )


@app.post("/search", response_model=list[SearchHit])
def search_semantic(payload: SearchRequest) -> list[SearchHit]:
    if not settings.embedding_enabled:
        raise HTTPException(status_code=400, detail="embeddings disabled")

    query_text = payload.query.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query required")

    vector = embed_text(query_text)
    if not vector:
        return []

    top_k = max(1, min(payload.top_k, 100))

    vector_weight = (
        payload.vector_weight
        if payload.vector_weight is not None
        else settings.hybrid_vector_weight
    )
    lexical_weight = (
        payload.lexical_weight
        if payload.lexical_weight is not None
        else settings.hybrid_lexical_weight
    )
    vector_weight = max(0.0, vector_weight)
    lexical_weight = max(0.0, lexical_weight)
    use_hybrid = settings.hybrid_scoring_enabled or payload.vector_weight is not None or payload.lexical_weight is not None

    if payload.kind == "cv":
        distance = CvEmbedding.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(CvDocument, ExtractedText.extracted_text, distance)
            .join(CvEmbedding, CvEmbedding.cv_id == CvDocument.id)
            .join(ExtractedText, ExtractedText.file_path == CvDocument.path, isouter=True)
            .order_by(distance.asc())
            .limit(top_k)
        )
        if payload.status:
            stmt = stmt.where(CvDocument.status == payload.status)
    else:
        distance = JobEmbedding.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(JobDocument, ExtractedText.extracted_text, distance)
            .join(JobEmbedding, JobEmbedding.job_id == JobDocument.id)
            .join(ExtractedText, ExtractedText.file_path == JobDocument.path, isouter=True)
            .order_by(distance.asc())
            .limit(top_k)
        )
        if payload.status:
            stmt = stmt.where(JobDocument.status == payload.status)

    results: list[SearchHit] = []
    with SessionLocal() as session:
        rows = session.execute(stmt).all()

    for doc, extracted_text, distance_value in rows:
        vector_score = _vector_score(float(distance_value))
        score = vector_score
        if use_hybrid:
            lexical_score = 0.0
            if extracted_text:
                lexical_score, _ = score_texts(query_text, extracted_text)
            score = _hybrid_score_with_weights(
                vector_score,
                lexical_score,
                vector_weight,
                lexical_weight,
            )
        if payload.min_score is not None and score < payload.min_score:
            continue
        results.append(
            SearchHit(
                id=doc.id,
                path=doc.path,
                status=doc.status,
                score=score,
                updated_at=doc.updated_at,
            )
        )

    return results


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


@app.post("/maintenance/purge-orphans")
def purge_orphan_files() -> dict[str, int]:
    removed_files = 0
    removed_documents = 0

    cv_root = Path(settings.watch_cv_dir)
    job_root = Path(settings.watch_job_dir)

    with SessionLocal() as session:
        cv_paths = {
            Path(row)
            for row in session.scalars(select(CvDocument.path)).all()
            if row
        }
        job_paths = {
            Path(row)
            for row in session.scalars(select(JobDocument.path)).all()
            if row
        }

        for path in cv_paths:
            if not path.exists():
                _cleanup_removed_file(path, "cv")
                removed_documents += 1

        for path in job_paths:
            if not path.exists():
                _cleanup_removed_file(path, "job")
                removed_documents += 1

    for folder in (cv_root, job_root):
        if not folder.exists():
            continue
        for file_path in folder.iterdir():
            if not file_path.is_file():
                continue
            if not _is_supported_file(file_path):
                continue
            if file_path in cv_paths or file_path in job_paths:
                continue
            try:
                file_path.unlink()
                removed_files += 1
            except Exception as exc:  # pragma: no cover
                logger.warning("failed to remove orphan file %s: %s", file_path, exc)

    return {
        "removed_files": removed_files,
        "removed_documents": removed_documents,
    }


@app.post("/maintenance/backfill-embeddings")
def backfill_embeddings(
    scope: str = "all",
    limit: int | None = None,
    offset: int = 0,
    batch_size: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    if not settings.embedding_enabled:
        raise HTTPException(status_code=400, detail="embeddings disabled")

    normalized = scope.lower()
    if normalized not in {"all", "cv", "job"}:
        raise HTTPException(status_code=400, detail="invalid scope")

    processed = 0
    skipped = 0
    failed = 0
    total = 0

    def _apply_batch(batch: list[tuple[int, str | None, str]], kind: str) -> None:
        nonlocal processed, failed
        if not batch:
            return
        if dry_run:
            processed += len(batch)
            return
        try:
            vectors = embed_texts([item[2] for item in batch])
        except Exception as exc:
            logger.warning("embedding batch failed: %s", exc)
            failed += len(batch)
            return

        for idx, (doc_id, content_hash, _) in enumerate(batch):
            vector = vectors[idx] if idx < len(vectors) else []
            if not vector:
                failed += 1
                continue
            if kind == "cv":
                _upsert_cv_embedding(doc_id, content_hash, vector, session=session)
            else:
                _upsert_job_embedding(doc_id, content_hash, vector, session=session)
            processed += 1

    with SessionLocal() as session:
        if normalized in {"all", "cv"}:
            remaining = None if limit is None else max(limit - processed, 0)
            if remaining == 0:
                return {
                    "processed": processed,
                    "skipped": skipped,
                    "failed": failed,
                    "total": total,
                    "has_more": False,
                    "next_offset": offset,
                }

            total += session.scalar(select(func.count()).select_from(CvDocument)) or 0

            query = (
                select(
                    CvDocument.id,
                    ExtractedText.content_hash,
                    ExtractedText.extracted_text,
                )
                .join(ExtractedText, ExtractedText.file_path == CvDocument.path, isouter=True)
                .order_by(CvDocument.id)
            )
            if offset:
                query = query.offset(offset)
            if batch_size is not None:
                query = query.limit(batch_size)
            elif remaining is not None:
                query = query.limit(remaining)

            rows = session.execute(query)
            batch: list[tuple[int, str | None, str]] = []
            for cv_id, content_hash, extracted_text in rows:
                if limit is not None and processed >= limit:
                    break
                text_value = (extracted_text or "").strip()
                if not text_value:
                    skipped += 1
                    continue
                batch.append((cv_id, content_hash, text_value))
                if len(batch) >= settings.embedding_batch_size:
                    _apply_batch(batch, "cv")
                    batch = []

            _apply_batch(batch, "cv")
        if normalized in {"all", "job"}:
            remaining = None if limit is None else max(limit - processed, 0)
            if remaining == 0:
                return {
                    "processed": processed,
                    "skipped": skipped,
                    "failed": failed,
                    "total": total,
                    "has_more": False,
                    "next_offset": offset,
                }

            total += session.scalar(select(func.count()).select_from(JobDocument)) or 0

            query = (
                select(
                    JobDocument.id,
                    ExtractedText.content_hash,
                    ExtractedText.extracted_text,
                )
                .join(ExtractedText, ExtractedText.file_path == JobDocument.path, isouter=True)
                .order_by(JobDocument.id)
            )
            if offset:
                query = query.offset(offset)
            if batch_size is not None:
                query = query.limit(batch_size)
            elif remaining is not None:
                query = query.limit(remaining)

            rows = session.execute(query)
            batch: list[tuple[int, str | None, str]] = []
            for job_id, content_hash, extracted_text in rows:
                if limit is not None and processed >= limit:
                    break
                text_value = (extracted_text or "").strip()
                if not text_value:
                    skipped += 1
                    continue
                batch.append((job_id, content_hash, text_value))
                if len(batch) >= settings.embedding_batch_size:
                    _apply_batch(batch, "job")
                    batch = []

            _apply_batch(batch, "job")

    next_offset = offset
    if batch_size is not None:
        next_offset = offset + batch_size

    has_more = True
    if batch_size is None:
        has_more = False
    elif total and next_offset >= total:
        has_more = False

    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
    }

@app.post("/extract", response_model=ExtractedTextRead)
def ingest_and_extract(file_path: str) -> ExtractedTextRead:
    return _extract_and_persist(Path(file_path))
