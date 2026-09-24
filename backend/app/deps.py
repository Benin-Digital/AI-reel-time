"""Dependencies et helpers reutilisables pour les routers.

Centralise les guards d'autorisation (admin/superadmin), l'acces a Redis,
et les operations de cleanup DB partagees entre plusieurs routers/workers.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
import redis
from sqlalchemy import delete, or_, select, true
from sqlalchemy.orm import Session as OrmSession

from .db import SessionLocal
from .models import (
    CvDocument,
    CvEmbedding,
    ExtractedText,
    JobDocument,
    JobEmbedding,
    MatchFeedback,
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


# Archive/session visibility hierarchy (reported bug, 2026-09-24): superadmin,
# admin and member all saw the exact same archive list regardless of who
# created it, because no endpoint ever recorded or checked an owner. The
# requested rule is strictly hierarchical: each role sees its own archives
# (private -- a peer or superior never sees them) plus every archive owned
# by a role strictly below it. member sees only its own; admin sees its own
# + every member's; superadmin sees its own + every admin's and member's.
_ROLE_RANK: dict[str, int] = {"member": 0, "admin": 1, "superadmin": 2}


def visible_owner_ids(session: OrmSession, current_user: User) -> set[int]:
    """User ids whose AnalysisSession rows `current_user` is allowed to see.

    Always includes the caller's own id. A legacy/system-created archive
    (created_by_user_id IS NULL, e.g. rows that predate this column, or a
    background process with no authenticated request) is treated
    separately by callers -- see `include_unclaimed` on the query helpers
    that use this set, not folded in here since "unclaimed" isn't really
    an owner id.
    """
    my_rank = _ROLE_RANK.get(current_user.role, 0)
    ids = {current_user.id}
    lower_roles = [role for role, rank in _ROLE_RANK.items() if rank < my_rank]
    if lower_roles:
        others = session.scalars(select(User.id).where(User.role.in_(lower_roles))).all()
        ids.update(others)
    return ids


def owner_visible_to(owner_id: int | None, current_user: User) -> bool:
    """Active-document visibility rule (2026-09-24, follow-up bug report):
    an active CV/job/match (not yet archived) is visible only to whoever
    created it, or to everyone if it's legacy/shared (no owner on record)
    -- unlike archives, there is NO role-hierarchy exception here: a
    superadmin does not see another profile's in-progress work either.
    Each profile is meant to be able to run its own analysis on the
    platform at the same time as everyone else without seeing theirs.
    """
    return owner_id is None or owner_id == current_user.id


def owners_eligible(owner_a: int | None, owner_b: int | None) -> bool:
    """Plain-Python counterpart to owner_eligibility_clause, for the
    in-process matching loop (_score_against_counterparts) rather than a
    SQL query: are a CV owned by `owner_a` and a job owned by `owner_b`
    allowed to be matched against each other at all?
    """
    return owner_a is None or owner_b is None or owner_a == owner_b


def owner_eligibility_clause(column, other_owner_id: int | None):
    """SQLAlchemy WHERE fragment: is `column` (a created_by_user_id column
    on the *other* side of a CV/job pair) an eligible counterpart for a
    document owned by `other_owner_id`? Used both to scope the matching
    engine itself (main.py's _vector_match_cv/_vector_match_job and the
    _score_against_counterparts candidate loops) and to filter what's
    displayed, so a private CV/job can never even get a MatchResult
    against another profile's private counterpart in the first place --
    legacy/shared (owner NULL) documents remain eligible with everyone.
    """
    if other_owner_id is None:
        return true()
    return or_(column.is_(None), column == other_owner_id)


def analysis_session_visible_to(session_owner_id: int | None, current_user: User, allowed_ids: set[int]) -> bool:
    """Archive-hierarchy visibility check for a single AnalysisSession,
    given its created_by_user_id and the caller's `visible_owner_ids()`
    set -- shared by routers/sessions.py and main.py so the two never
    silently drift on what "can see this archive" means.
    """
    if session_owner_id is None:
        return can_see_unclaimed_archives(current_user)
    return session_owner_id in allowed_ids


def can_see_unclaimed_archives(current_user: User) -> bool:
    """Legacy archives with no recorded owner (created before this feature,
    or by a background process) stay visible to elevated roles so existing
    data doesn't vanish, but not to a plain member -- that would leak
    unattributed archives into what's supposed to be a strictly private
    view for that role.
    """
    return _ROLE_RANK.get(current_user.role, 0) > 0


def cleanup_removed_file(path: Path, role: str) -> None:
    """Purge DB rows referencing a removed CV or Job file (path-based)."""
    with SessionLocal() as session:
        session.execute(
            delete(ExtractedText).where(ExtractedText.file_path == str(path))
        )
        if role == "cv":
            doc = session.scalar(select(CvDocument).where(CvDocument.path == str(path)))
            if doc:
                match_ids = session.scalars(
                    select(MatchResult.id).where(MatchResult.cv_id == doc.id)
                ).all()
                if match_ids:
                    session.execute(delete(MatchFeedback).where(MatchFeedback.match_id.in_(match_ids)))
                session.execute(delete(CvEmbedding).where(CvEmbedding.cv_id == doc.id))
                session.execute(delete(MatchResult).where(MatchResult.cv_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.cv_path == str(path)))
        else:
            doc = session.scalar(select(JobDocument).where(JobDocument.path == str(path)))
            if doc:
                match_ids = session.scalars(
                    select(MatchResult.id).where(MatchResult.job_id == doc.id)
                ).all()
                if match_ids:
                    session.execute(delete(MatchFeedback).where(MatchFeedback.match_id.in_(match_ids)))
                session.execute(delete(JobEmbedding).where(JobEmbedding.job_id == doc.id))
                session.execute(delete(MatchResult).where(MatchResult.job_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.job_path == str(path)))
        session.commit()
