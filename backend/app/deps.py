"""Dependencies et helpers reutilisables pour les routers.

Centralise les guards d'autorisation (admin/superadmin), l'acces a Redis,
et les operations de cleanup DB partagees entre plusieurs routers/workers.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
import redis
from sqlalchemy import delete, select

from .db import SessionLocal
from .models import (
    CvDocument,
    CvEmbedding,
    ExtractedText,
    JobDocument,
    JobEmbedding,
    MatchResult,
    ScoreResult,
    User,
)
from .settings import get_settings

settings = get_settings()


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def require_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(request: Request) -> User:
    user = require_user(request)
    if user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def require_superadmin(request: Request) -> User:
    user = require_admin(request)
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin role required")
    return user


def cleanup_removed_file(path: Path, role: str) -> None:
    """Purge DB rows referencing a removed CV or Job file (path-based)."""
    with SessionLocal() as session:
        session.execute(
            delete(ExtractedText).where(ExtractedText.file_path == str(path))
        )
        if role == "cv":
            doc = session.scalar(select(CvDocument).where(CvDocument.path == str(path)))
            if doc:
                session.execute(delete(CvEmbedding).where(CvEmbedding.cv_id == doc.id))
                session.execute(delete(MatchResult).where(MatchResult.cv_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.cv_path == str(path)))
        else:
            doc = session.scalar(select(JobDocument).where(JobDocument.path == str(path)))
            if doc:
                session.execute(delete(JobEmbedding).where(JobEmbedding.job_id == doc.id))
                session.execute(delete(MatchResult).where(MatchResult.job_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.job_path == str(path)))
        session.commit()
