"""Endpoints /matches/* et sous-routes /cv-documents/{id}/matches, /job-documents/{id}/matches."""
from __future__ import annotations
import csv
import io
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from ..db import SessionLocal
from ..deps import can_see_unclaimed_archives, owner_visible_to, require_user, visible_owner_ids
from ..models import AnalysisSession, CvDocument, ExtractedText, JobDocument, MatchFeedback, MatchResult, User


def _cv_label(path: str, parsed_profile: dict | None) -> str:
    name = (parsed_profile or {}).get("person_name") or ""
    return name.strip() if name.strip() else Path(path).stem


def _job_label(path: str, parsed_profile: dict | None) -> str:
    title = (parsed_profile or {}).get("job_title") or ""
    return title.strip() if title.strip() else Path(path).stem


def _build_labels(session, rows: list) -> tuple[dict[int, str], dict[int, str]]:
    """Retourne (cv_labels, job_labels) pour une liste de MatchResult."""
    cv_ids  = list({r.cv_id  for r in rows})
    job_ids = list({r.job_id for r in rows})

    cv_docs  = {d.id: d for d in session.scalars(select(CvDocument).where(CvDocument.id.in_(cv_ids))).all()}
    job_docs = {d.id: d for d in session.scalars(select(JobDocument).where(JobDocument.id.in_(job_ids))).all()}

    cv_paths  = [cv_docs[i].path  for i in cv_ids  if i in cv_docs]
    job_paths = [job_docs[i].path for i in job_ids if i in job_docs]

    cv_texts  = {e.file_path: e.parsed_profile for e in session.scalars(select(ExtractedText).where(ExtractedText.file_path.in_(cv_paths))).all()}
    job_texts = {e.file_path: e.parsed_profile for e in session.scalars(select(ExtractedText).where(ExtractedText.file_path.in_(job_paths))).all()}

    cv_labels  = {i: _cv_label(cv_docs[i].path,  cv_texts.get(cv_docs[i].path))  for i in cv_ids  if i in cv_docs}
    job_labels = {i: _job_label(job_docs[i].path, job_texts.get(job_docs[i].path)) for i in job_ids if i in job_docs}
    return cv_labels, job_labels


def _build_feedback_map(session, rows: list) -> dict[int, MatchFeedback]:
    """Return {match_id: latest MatchFeedback} for a list of MatchResult rows.

    The match list (GET /matches) never carried feedback, so the frontend's
    per-card evaluation bar only ever showed a decision the user had picked
    *in this page load* (a client-side cache populated lazily when the
    "Analyser" modal happens to fetch GET /matches/{id}/feedback) -- a saved
    evaluation looked like it had vanished after any page refresh, when in
    fact it was sitting untouched in the database the whole time. Fetching
    it here, batched, lets the list render the persisted state directly.
    """
    match_ids = [r.id for r in rows]
    if not match_ids:
        return {}
    all_feedback = session.scalars(
        select(MatchFeedback)
        .where(MatchFeedback.match_id.in_(match_ids))
        .order_by(MatchFeedback.created_at.desc(), MatchFeedback.id.desc())
    ).all()
    latest: dict[int, MatchFeedback] = {}
    for fb in all_feedback:
        latest.setdefault(fb.match_id, fb)
    return latest


def _to_match_read(
    row: MatchResult,
    cv_labels: dict[int, str],
    job_labels: dict[int, str],
    feedback_map: dict[int, MatchFeedback],
) -> MatchRead:
    fb = feedback_map.get(row.id)
    return MatchRead(
        id=row.id,
        cv_id=row.cv_id,
        job_id=row.job_id,
        cv_label=cv_labels.get(row.cv_id),
        job_label=job_labels.get(row.job_id),
        score=row.score,
        common_keywords=deserialize_keywords(row.common_keywords),
        # Never populated here before (2026-09-14 audit): the per-component
        # breakdown bars in the frontend's match card (_renderComponentScores)
        # checked for these fields but this endpoint never sent them, so
        # that breakdown silently rendered empty for every match, not just
        # incomplete ones -- and score_skills specifically is also the
        # frontend's marker for "still a cheap vector-only provisional
        # score" (see the matching backend marker in
        # _matched_all_active_counterparts), which needs this to actually
        # distinguish a provisional match from a complete one.
        score_semantic=row.score_semantic,
        score_skills=row.score_skills,
        score_experience=row.score_experience,
        score_education=row.score_education,
        score_languages=row.score_languages,
        score_contract=row.score_contract,
        match_domain=row.match_domain,
        score_priority_keywords=row.score_priority_keywords,
        priority_keywords_matched_count=row.priority_keywords_matched_count,
        priority_keywords_total=row.priority_keywords_total,
        priority_keywords_missing=deserialize_keywords(row.priority_keywords_missing),
        feedback_decision=fb.decision if fb else None,
        feedback_rating=fb.rating if fb else None,
        feedback_comment=fb.comment if fb else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
from ..schemas import (
    AnalyzeRequest,
    MatchExplainRead,
    MatchProgressRead,
    MatchRead,
)
from ..services import deserialize_keywords
from ..services.explain import build_match_explanation
from ..services.matcher import match_cv_to_job

router = APIRouter(tags=["matches"])


@router.post("/matches/analyze")
def analyze_texts(payload: AnalyzeRequest) -> JSONResponse:
    result = match_cv_to_job(payload.cv_text or "", payload.job_text or "")
    return JSONResponse(
        content={
            "score": result.score,
            "score_semantic": result.score_semantic,
            "score_skills": result.score_skills,
            "score_experience": result.score_experience,
            "score_education": result.score_education,
            "score_languages": result.score_languages,
            "score_contract": result.score_contract,
            "domain": result.domain,
            "common_skills": result.common_skills,
            "missing_skills": result.missing_skills,
            "weights": result.weights,
            "low_confidence_components": result.low_confidence_components,
        }
    )


@router.get("/cv-documents/{doc_id}/matches", response_model=list[MatchRead])
def list_matches_for_cv(doc_id: int, request: Request, limit: int = 50) -> list[MatchRead]:
    current_user = require_user(request)
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        stmt = _apply_archive_visibility(
            select(MatchResult).where(MatchResult.cv_id == doc_id), session, current_user
        )
        rows = session.scalars(stmt.order_by(MatchResult.score.desc()).limit(safe_limit)).all()
        cv_labels, job_labels = _build_labels(session, rows)
        feedback_map = _build_feedback_map(session, rows)
        return [_to_match_read(row, cv_labels, job_labels, feedback_map) for row in rows]


@router.get("/job-documents/{doc_id}/matches", response_model=list[MatchRead])
def list_matches_for_job(doc_id: int, request: Request, limit: int = 50) -> list[MatchRead]:
    current_user = require_user(request)
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        stmt = _apply_archive_visibility(
            select(MatchResult).where(MatchResult.job_id == doc_id), session, current_user
        )
        rows = session.scalars(stmt.order_by(MatchResult.score.desc()).limit(safe_limit)).all()
        cv_labels, job_labels = _build_labels(session, rows)
        feedback_map = _build_feedback_map(session, rows)
        return [_to_match_read(row, cv_labels, job_labels, feedback_map) for row in rows]


@router.get("/matches/progress", response_model=MatchProgressRead)
def get_match_progress() -> MatchProgressRead:
    """Lets the frontend distinguish "nothing to match yet" from "matching
    is still being computed" -- CvDocument/JobDocument.status flips to
    "ready" as soon as extraction succeeds, BEFORE _score_against_
    counterparts()'s matching loop runs (see main.py), so a document can
    show "Prêt" while its matches against the active library are still
    trickling in one by one with no indication anything is happening.
    Correspondances rendered "Aucune correspondance" (the same empty state
    as "you haven't imported anything yet") for that whole window, then
    matches appeared with no explanation. expected_pairs is an upper bound
    (every active CV against every active job) -- some pairs are legitimately
    never scored (a failed extraction), so 100% is not always reachable,
    but it's enough to know "more are still coming" vs "this is everything".
    """
    with SessionLocal() as session:
        active_cv_count = session.scalar(
            select(func.count()).select_from(CvDocument).where(CvDocument.session_id.is_(None))
        ) or 0
        active_job_count = session.scalar(
            select(func.count()).select_from(JobDocument).where(JobDocument.session_id.is_(None))
        ) or 0
        computed_pairs = session.scalar(
            select(func.count())
            .select_from(MatchResult)
            .join(CvDocument, MatchResult.cv_id == CvDocument.id)
            .join(JobDocument, MatchResult.job_id == JobDocument.id)
            .where(CvDocument.session_id.is_(None), JobDocument.session_id.is_(None))
        ) or 0
        # Active matches with no feedback row at all -- feeds the
        # "Correspondances" sidebar badge, distinct from computed_pairs
        # above (which is "matching is done", not "a recruiter has looked
        # at it yet").
        has_feedback = (
            select(MatchFeedback.id).where(MatchFeedback.match_id == MatchResult.id).exists()
        )
        unreviewed_count = session.scalar(
            select(func.count())
            .select_from(MatchResult)
            .join(CvDocument, MatchResult.cv_id == CvDocument.id)
            .join(JobDocument, MatchResult.job_id == JobDocument.id)
            .where(
                CvDocument.session_id.is_(None),
                JobDocument.session_id.is_(None),
                ~has_feedback,
            )
        ) or 0
    return MatchProgressRead(
        active_cv_count=active_cv_count,
        active_job_count=active_job_count,
        expected_pairs=active_cv_count * active_job_count,
        computed_pairs=computed_pairs,
        unreviewed_count=unreviewed_count,
    )


def _apply_archive_visibility(stmt, db_session: OrmSession, current_user: User):
    """Exclude any MatchResult the caller's role isn't allowed to see, on
    either side of the archived/active split (2026-09-24 fix, extended
    from the original archive-only version) -- shared by every /matches*
    read path so visibility can't be bypassed through a side door (a
    specific match id, a CV's own match list, etc.) that happens to skip
    _build_match_filter_stmt.

    - Archived (session_id set): role-hierarchy rule, same as GET /sessions
      (deps.visible_owner_ids) -- a superadmin sees an admin's archive.
    - Active (session_id NULL): stricter, no hierarchy exception -- visible
      only to the document's own uploader, or to everyone if legacy/shared
      (created_by_user_id NULL). The matching engine itself
      (_score_against_counterparts) never creates a MatchResult between two
      different profiles' private documents, so it's enough to exclude an
      active document owned by someone else entirely; there's no case where
      that hides a pair that should stay visible to `current_user`.
    """
    visible_sessions = _visible_analysis_session_ids_subq(db_session, current_user)
    return stmt.where(
        MatchResult.cv_id.notin_(
            select(CvDocument.id).where(
                CvDocument.session_id.isnot(None),
                CvDocument.session_id.notin_(visible_sessions),
            )
        ),
        MatchResult.job_id.notin_(
            select(JobDocument.id).where(
                JobDocument.session_id.isnot(None),
                JobDocument.session_id.notin_(visible_sessions),
            )
        ),
        MatchResult.cv_id.notin_(
            select(CvDocument.id).where(
                CvDocument.session_id.is_(None),
                CvDocument.created_by_user_id.isnot(None),
                CvDocument.created_by_user_id != current_user.id,
            )
        ),
        MatchResult.job_id.notin_(
            select(JobDocument.id).where(
                JobDocument.session_id.is_(None),
                JobDocument.created_by_user_id.isnot(None),
                JobDocument.created_by_user_id != current_user.id,
            )
        ),
    )


def _visible_analysis_session_ids_subq(db_session: OrmSession, current_user: User):
    """Sub-select of AnalysisSession.id the caller's role hierarchy allows
    seeing -- same rule as sessions.py's archive list (deps.visible_owner_ids),
    applied here so an archived match can't leak through GET /matches or
    the CSV export just because the Archives page itself is filtered.
    """
    allowed_ids = visible_owner_ids(db_session, current_user)
    owner_filter = AnalysisSession.created_by_user_id.in_(allowed_ids)
    if can_see_unclaimed_archives(current_user):
        owner_filter = or_(owner_filter, AnalysisSession.created_by_user_id.is_(None))
    return select(AnalysisSession.id).where(owner_filter)


def _build_match_filter_stmt(
    *,
    db_session: OrmSession,
    current_user: User,
    cv_id: int | None,
    job_id: int | None,
    session_id: int | None,
    unassigned_only: bool,
    min_score: float | None,
    max_score: float | None,
    sort_by: str,
    search: str | None,
):
    """Shared WHERE/ORDER BY builder for GET /matches and GET /matches/export.csv
    -- kept in one place so the CSV export can never silently drift from
    what the recruiter sees on screen (same filters, same sort).

    Also where archive-visibility is enforced (2026-09-24 fix): a match
    whose CV or job sits in an AnalysisSession the caller's role can't see
    is excluded, the same way it's excluded from GET /sessions -- without
    this, toggling "inclure les archives" on the Correspondances page
    would still show every archived match to every role.
    """
    stmt = _apply_archive_visibility(select(MatchResult), db_session, current_user)
    if session_id is not None or unassigned_only or search:
        stmt = stmt.join(CvDocument, MatchResult.cv_id == CvDocument.id)
        stmt = stmt.join(JobDocument, MatchResult.job_id == JobDocument.id)
    if cv_id is not None:
        stmt = stmt.where(MatchResult.cv_id == cv_id)
    if job_id is not None:
        stmt = stmt.where(MatchResult.job_id == job_id)
    if session_id is not None:
        stmt = stmt.where(
            CvDocument.session_id == session_id,
            JobDocument.session_id == session_id,
        )
    if unassigned_only:
        stmt = stmt.where(
            CvDocument.session_id.is_(None),
            JobDocument.session_id.is_(None),
        )
    if min_score is not None:
        stmt = stmt.where(MatchResult.score >= min_score)
    if max_score is not None:
        stmt = stmt.where(MatchResult.score <= max_score)
    if search:
        search_expr = f"%{search}%"
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
    return stmt


@router.get("/matches", response_model=list[MatchRead])
def list_matches(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    cv_id: int | None = None,
    job_id: int | None = None,
    session_id: int | None = None,
    unassigned_only: bool = False,
    min_score: float | None = None,
    max_score: float | None = None,
    sort_by: str = "score_desc",
    search: str | None = None,
) -> list[MatchRead]:
    current_user = require_user(request)
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)

    with SessionLocal() as session:
        stmt = _build_match_filter_stmt(
            db_session=session, current_user=current_user,
            cv_id=cv_id, job_id=job_id, session_id=session_id,
            unassigned_only=unassigned_only, min_score=min_score, max_score=max_score,
            sort_by=sort_by, search=search,
        )
        rows = session.scalars(stmt.offset(safe_offset).limit(safe_size)).all()
        cv_labels, job_labels = _build_labels(session, rows)
        feedback_map = _build_feedback_map(session, rows)
        return [_to_match_read(row, cv_labels, job_labels, feedback_map) for row in rows]


# Hard cap on a single CSV export -- this table can realistically reach
# hundreds of thousands of rows (every active CV scored against every
# active job), and an unfiltered "export everything" click shouldn't be
# able to run an unbounded query or hand back a multi-hundred-MB file.
# A recruiter exporting for one job/CV (the common case) stays far under
# this; exporting the whole unfiltered library is expected to need the
# score/cv_id/job_id filters already available on the page.
_CSV_EXPORT_MAX_ROWS = 20_000

_CSV_COLUMNS = [
    "match_id", "score", "cv_id", "cv_label", "job_id", "job_label",
    "match_domain", "score_skills", "score_semantic", "score_experience",
    "score_education", "score_languages", "score_contract",
    "score_priority_keywords", "priority_keywords_matched_count",
    "priority_keywords_total", "priority_keywords_missing",
    "common_keywords", "feedback_decision", "feedback_rating",
    "feedback_comment", "created_at", "updated_at",
]


def _match_csv_row(row: MatchResult, cv_labels: dict, job_labels: dict, feedback_map: dict) -> list:
    fb = feedback_map.get(row.id)
    return [
        row.id,
        row.score,
        row.cv_id,
        cv_labels.get(row.cv_id, ""),
        row.job_id,
        job_labels.get(row.job_id, ""),
        row.match_domain or "",
        row.score_skills,
        row.score_semantic,
        row.score_experience,
        row.score_education,
        row.score_languages,
        row.score_contract,
        row.score_priority_keywords,
        row.priority_keywords_matched_count,
        row.priority_keywords_total,
        "; ".join(deserialize_keywords(row.priority_keywords_missing)),
        "; ".join(deserialize_keywords(row.common_keywords)),
        fb.decision if fb else "",
        fb.rating if fb else "",
        fb.comment if fb else "",
        row.created_at.isoformat() if row.created_at else "",
        row.updated_at.isoformat() if row.updated_at else "",
    ]


@router.get("/matches/export.csv")
def export_matches_csv(
    request: Request,
    cv_id: int | None = None,
    job_id: int | None = None,
    session_id: int | None = None,
    unassigned_only: bool = False,
    min_score: float | None = None,
    max_score: float | None = None,
    sort_by: str = "score_desc",
    search: str | None = None,
) -> StreamingResponse:
    """Export the current filtered/sorted match list as CSV -- same filters
    as GET /matches (see _build_match_filter_stmt), no pagination.
    """
    current_user = require_user(request)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)

    with SessionLocal() as session:
        stmt = _build_match_filter_stmt(
            db_session=session, current_user=current_user,
            cv_id=cv_id, job_id=job_id, session_id=session_id,
            unassigned_only=unassigned_only, min_score=min_score, max_score=max_score,
            sort_by=sort_by, search=search,
        )
        rows = session.scalars(stmt.limit(_CSV_EXPORT_MAX_ROWS)).all()
        cv_labels, job_labels = _build_labels(session, rows)
        feedback_map = _build_feedback_map(session, rows)
        for row in rows:
            writer.writerow(_match_csv_row(row, cv_labels, job_labels, feedback_map))

    buffer.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="correspondances.csv"'}
    # UTF-8 BOM so Excel (the realistic recruiter workflow) auto-detects the
    # encoding instead of mangling accented names/keywords into mojibake.
    content = "\ufeff" + buffer.getvalue()
    return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8", headers=headers)


def _match_is_archive_visible(session: OrmSession, match: MatchResult, current_user: User) -> bool:
    """See _apply_archive_visibility's docstring for the two-tier rule this
    mirrors for a single already-fetched MatchResult (GET /matches/{id} and
    /matches/{id}/explain, which fetch by id directly rather than through
    _build_match_filter_stmt).
    """
    allowed_ids = visible_owner_ids(session, current_user)
    include_unclaimed = can_see_unclaimed_archives(current_user)

    def _side_visible(session_id: int | None, owner_id: int | None) -> bool:
        if session_id is None:
            return owner_visible_to(owner_id, current_user)
        archive_owner = session.scalar(
            select(AnalysisSession.created_by_user_id).where(AnalysisSession.id == session_id)
        )
        if archive_owner is None:
            return include_unclaimed
        return archive_owner in allowed_ids

    cv_session_id, cv_owner_id = session.execute(
        select(CvDocument.session_id, CvDocument.created_by_user_id).where(CvDocument.id == match.cv_id)
    ).first() or (None, None)
    job_session_id, job_owner_id = session.execute(
        select(JobDocument.session_id, JobDocument.created_by_user_id).where(JobDocument.id == match.job_id)
    ).first() or (None, None)
    return _side_visible(cv_session_id, cv_owner_id) and _side_visible(job_session_id, job_owner_id)


@router.get("/matches/{match_id}", response_model=MatchRead)
def get_match(match_id: int, request: Request) -> MatchRead:
    current_user = require_user(request)
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match or not _match_is_archive_visible(session, match, current_user):
            raise HTTPException(status_code=404, detail="Match not found")
        cv_labels, job_labels = _build_labels(session, [match])
        feedback_map = _build_feedback_map(session, [match])
        return _to_match_read(match, cv_labels, job_labels, feedback_map)


@router.get("/matches/{match_id}/explain", response_model=MatchExplainRead)
def explain_match(match_id: int, request: Request) -> MatchExplainRead:
    current_user = require_user(request)
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match or not _match_is_archive_visible(session, match, current_user):
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

        details = build_match_explanation(
            cv_text, job_text, match.score, keywords, job_doc.priority_keywords
        )
        return MatchExplainRead(
            match_id=match.id,
            score=match.score,
            summary=str(details["summary"]),
            why_match=list(details["why_match"]),
            vigilance=list(details["vigilance"]),
            evidence=list(details["evidence"]),
            keyword_hits=list(details["keyword_hits"]),
            score_semantic=match.score_semantic,
            score_skills=match.score_skills,
            score_experience=match.score_experience,
            score_education=match.score_education,
            score_languages=match.score_languages,
            score_contract=match.score_contract,
            score_priority_keywords=match.score_priority_keywords,
            priority_keywords_matched=list(details["priority_keywords_matched"]),
            priority_keywords_missing=list(details["priority_keywords_missing"]),
            match_domain=match.match_domain,
        )
