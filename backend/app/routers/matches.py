"""Endpoints /matches/* et sous-routes /cv-documents/{id}/matches, /job-documents/{id}/matches."""
from __future__ import annotations
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select

from ..db import SessionLocal
from ..models import CvDocument, ExtractedText, JobDocument, MatchResult


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
from ..schemas import (
    AnalyzeRequest,
    MatchExplainRead,
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
def list_matches_for_cv(doc_id: int, limit: int = 50) -> list[MatchRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.cv_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()
        cv_labels, job_labels = _build_labels(session, rows)
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                cv_label=cv_labels.get(row.cv_id),
                job_label=job_labels.get(row.job_id),
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@router.get("/job-documents/{doc_id}/matches", response_model=list[MatchRead])
def list_matches_for_job(doc_id: int, limit: int = 50) -> list[MatchRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.job_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()
        cv_labels, job_labels = _build_labels(session, rows)
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                cv_label=cv_labels.get(row.cv_id),
                job_label=job_labels.get(row.job_id),
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@router.get("/matches", response_model=list[MatchRead])
def list_matches(
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
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(MatchResult)
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

    with SessionLocal() as session:
        rows = session.scalars(stmt.offset(safe_offset).limit(safe_size)).all()
        cv_labels, job_labels = _build_labels(session, rows)
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                cv_label=cv_labels.get(row.cv_id),
                job_label=job_labels.get(row.job_id),
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@router.get("/matches/{match_id}", response_model=MatchRead)
def get_match(match_id: int) -> MatchRead:
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        cv_labels, job_labels = _build_labels(session, [match])
        return MatchRead(
            id=match.id,
            cv_id=match.cv_id,
            job_id=match.job_id,
            cv_label=cv_labels.get(match.cv_id),
            job_label=job_labels.get(match.job_id),
            score=match.score,
            common_keywords=deserialize_keywords(match.common_keywords),
            created_at=match.created_at,
            updated_at=match.updated_at,
        )


@router.get("/matches/{match_id}/explain", response_model=MatchExplainRead)
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
            score_semantic=match.score_semantic,
            score_skills=match.score_skills,
            score_experience=match.score_experience,
            score_education=match.score_education,
            score_languages=match.score_languages,
            score_contract=match.score_contract,
            match_domain=match.match_domain,
        )
