"""Endpoints de sante, readiness et metriques."""
from __future__ import annotations

import logging
from time import time

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select, text

from ..db import SessionLocal
from ..models import (
    CvDocument,
    CvEmbedding,
    EventLog,
    ExtractedText,
    JobDocument,
    JobEmbedding,
    MatchResult,
    ScoreResult,
)
from ..deps import get_redis_client
from ..observability import CONTENT_TYPE_LATEST, render_metrics, update_runtime_metrics
from ..services import get_queue_status
from ..settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": settings.app_version,
    }


@router.get("/ready")
def readiness() -> dict[str, str]:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        logger.error("db readiness failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")

    try:
        client = get_redis_client()
        client.ping()
    except Exception as exc:  # pragma: no cover
        logger.error("redis readiness failed: %s", exc)
        raise HTTPException(status_code=503, detail="redis unavailable")

    return {"status": "ready"}


@router.get("/metrics")
def metrics(request: Request) -> dict[str, float | int | bool | str | None]:
    app = request.app
    uptime = int(time() - app.state.started_at)
    queue_status = get_queue_status()
    worker = getattr(app.state, "worker", None)
    with SessionLocal() as session:
        events = session.scalar(select(func.count()).select_from(EventLog))
        extractions = session.scalar(select(func.count()).select_from(ExtractedText))
        scores = session.scalar(select(func.count()).select_from(ScoreResult))

        # "event_count"/"extraction_count"/"score_count" above are lifetime
        # totals -- they only ever grow and say nothing about the platform's
        # current state (archiving doesn't delete history), which read as
        # a "primitive", uninformative dashboard. These give an actual
        # snapshot: how much is active right now, vs sitting in an archive.
        active_cv_count = session.scalar(
            select(func.count()).select_from(CvDocument).where(CvDocument.session_id.is_(None))
        ) or 0
        archived_cv_count = session.scalar(
            select(func.count()).select_from(CvDocument).where(CvDocument.session_id.is_not(None))
        ) or 0
        active_job_count = session.scalar(
            select(func.count()).select_from(JobDocument).where(JobDocument.session_id.is_(None))
        ) or 0
        archived_job_count = session.scalar(
            select(func.count()).select_from(JobDocument).where(JobDocument.session_id.is_not(None))
        ) or 0

        active_match_count = session.scalar(
            select(func.count())
            .select_from(MatchResult)
            .join(CvDocument, MatchResult.cv_id == CvDocument.id)
            .join(JobDocument, MatchResult.job_id == JobDocument.id)
            .where(CvDocument.session_id.is_(None), JobDocument.session_id.is_(None))
        ) or 0

    return {
        "uptime_seconds": uptime,
        "event_count": int(events or 0),
        "extraction_count": int(extractions or 0),
        "score_count": int(scores or 0),
        "active_cv_count": int(active_cv_count),
        "archived_cv_count": int(archived_cv_count),
        "active_job_count": int(active_job_count),
        "archived_job_count": int(archived_job_count),
        "active_match_count": int(active_match_count),
        "redis_available": bool(queue_status.get("redis_available", False)),
        "redis_queue_length": int(queue_status.get("redis_queue_length", 0)),
        "memory_queue_length": int(queue_status.get("memory_queue_length", 0)),
        "worker_alive": bool(worker.is_running) if worker is not None else False,
        "worker_last_error": worker.last_error if worker is not None else None,
    }


@router.get("/metrics/prometheus")
def metrics_prometheus(request: Request) -> Response:
    app = request.app
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


@router.get("/queue-status")
def queue_status() -> dict[str, int | bool]:
    return get_queue_status()


@router.get("/worker-status")
def worker_status(request: Request) -> dict[str, bool | str | None]:
    worker = getattr(request.app.state, "worker", None)
    if worker is None:
        raise HTTPException(status_code=503, detail="worker unavailable")
    return {
        "alive": worker.is_running,
        "last_error": worker.last_error,
    }
