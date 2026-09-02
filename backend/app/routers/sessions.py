"""Endpoints /sessions/* — gestion des sessions d'analyse CV/Job."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..deps import cleanup_removed_file
from ..models import AnalysisSession, CvDocument, JobDocument, MatchResult
from ..schemas import (
    AnalysisSessionCreate,
    AnalysisSessionDetailRead,
    AnalysisSessionRead,
    AnalysisSessionUpdate,
    CvDocumentRead,
    JobDocumentRead,
    SessionAssignRequest,
)

router = APIRouter(tags=["sessions"])


def _calculate_session_counts(session: Session, session_id: int) -> tuple[int, int, int]:
    cv_count = session.scalar(
        select(func.count()).select_from(CvDocument).where(CvDocument.session_id == session_id)
    ) or 0
    job_count = session.scalar(
        select(func.count()).select_from(JobDocument).where(JobDocument.session_id == session_id)
    ) or 0
    match_count = session.scalar(
        select(func.count()).select_from(MatchResult)
        .join(CvDocument, MatchResult.cv_id == CvDocument.id)
        .join(JobDocument, MatchResult.job_id == JobDocument.id)
        .where(CvDocument.session_id == session_id, JobDocument.session_id == session_id)
    ) or 0
    return int(cv_count), int(job_count), int(match_count)


@router.get("/sessions", response_model=list[AnalysisSessionRead])
def list_analysis_sessions(
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    search: str | None = None,
) -> list[AnalysisSessionRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(AnalysisSession)
    if status:
        stmt = stmt.where(AnalysisSession.status == status)
    if search:
        search_expr = f"%{search}%"
        stmt = stmt.where(
            or_(
                AnalysisSession.name.ilike(search_expr),
                AnalysisSession.description.ilike(search_expr),
            )
        )
    stmt = stmt.order_by(AnalysisSession.id.desc()).offset(safe_offset).limit(safe_size)
    with SessionLocal() as session:
        rows = session.scalars(stmt).all()
        result = []
        for row in rows:
            cv_count, job_count, match_count = _calculate_session_counts(session, row.id)
            result.append(
                AnalysisSessionRead(
                    id=row.id,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                    closed_at=row.closed_at,
                    cv_count=cv_count,
                    job_count=job_count,
                    match_count=match_count,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return result


@router.post("/sessions", response_model=AnalysisSessionRead)
def create_analysis_session(payload: AnalysisSessionCreate) -> AnalysisSessionRead:
    with SessionLocal() as session:
        new_session = AnalysisSession(
            name=payload.name.strip(),
            description=payload.description.strip() if payload.description else None,
            status=payload.status,
            closed_at=datetime.utcnow() if payload.status == "closed" else None,
        )
        session.add(new_session)
        session.commit()
        session.refresh(new_session)
        cv_count, job_count, match_count = _calculate_session_counts(session, new_session.id)
        return AnalysisSessionRead(
            id=new_session.id,
            name=new_session.name,
            description=new_session.description,
            status=new_session.status,
            closed_at=new_session.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=new_session.created_at,
            updated_at=new_session.updated_at,
        )


@router.get("/sessions/{session_id}", response_model=AnalysisSessionDetailRead)
def get_analysis_session(session_id: int) -> AnalysisSessionDetailRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Analyse session not found")

        cv_docs = session.scalars(
            select(CvDocument)
            .where(CvDocument.session_id == session_id)
            .order_by(CvDocument.id.desc())
        ).all()
        job_docs = session.scalars(
            select(JobDocument)
            .where(JobDocument.session_id == session_id)
            .order_by(JobDocument.id.desc())
        ).all()
        cv_count, job_count, match_count = _calculate_session_counts(session, session_id)
        return AnalysisSessionDetailRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
            cv_documents=[CvDocumentRead.model_validate(doc) for doc in cv_docs],
            job_documents=[JobDocumentRead.model_validate(doc) for doc in job_docs],
        )


@router.patch("/sessions/{session_id}", response_model=AnalysisSessionRead)
def update_analysis_session(session_id: int, payload: AnalysisSessionUpdate) -> AnalysisSessionRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Analyse session not found")

        if payload.name is not None:
            session_obj.name = payload.name.strip()
        if payload.description is not None:
            session_obj.description = payload.description.strip() if payload.description else None
        if payload.status is not None:
            session_obj.status = payload.status
            if payload.status == "closed" and session_obj.closed_at is None:
                session_obj.closed_at = datetime.utcnow()
            elif payload.status == "open":
                session_obj.closed_at = None
        session.commit()
        session.refresh(session_obj)
        cv_count, job_count, match_count = _calculate_session_counts(session, session_id)
        return AnalysisSessionRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
        )


@router.post("/sessions/{session_id}/assign", response_model=AnalysisSessionDetailRead)
def assign_documents_to_session(session_id: int, payload: SessionAssignRequest) -> AnalysisSessionDetailRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Analyse session not found")

        if payload.cv_ids:
            cv_rows = session.scalars(select(CvDocument).where(CvDocument.id.in_(payload.cv_ids))).all()
            if len(cv_rows) != len(payload.cv_ids):
                raise HTTPException(status_code=404, detail="Un ou plusieurs CV n'ont pas été trouvés")
            for doc in cv_rows:
                doc.session_id = session_id

        if payload.job_ids:
            job_rows = session.scalars(select(JobDocument).where(JobDocument.id.in_(payload.job_ids))).all()
            if len(job_rows) != len(payload.job_ids):
                raise HTTPException(status_code=404, detail="Une ou plusieurs offres n'ont pas été trouvées")
            for doc in job_rows:
                doc.session_id = session_id

        session.commit()
        session.refresh(session_obj)
        cv_docs = session.scalars(
            select(CvDocument).where(CvDocument.session_id == session_id).order_by(CvDocument.id.desc())
        ).all()
        job_docs = session.scalars(
            select(JobDocument).where(JobDocument.session_id == session_id).order_by(JobDocument.id.desc())
        ).all()
        cv_count, job_count, match_count = _calculate_session_counts(session, session_id)
        return AnalysisSessionDetailRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
            cv_documents=[CvDocumentRead.model_validate(doc) for doc in cv_docs],
            job_documents=[JobDocumentRead.model_validate(doc) for doc in job_docs],
        )


@router.post("/sessions/{session_id}/unassign", response_model=AnalysisSessionDetailRead)
def unassign_session_documents(session_id: int) -> AnalysisSessionDetailRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")
        session.execute(
            update(CvDocument).where(CvDocument.session_id == session_id).values(session_id=None)
        )
        session.execute(
            update(JobDocument).where(JobDocument.session_id == session_id).values(session_id=None)
        )
        session_obj.status = "open"
        session_obj.closed_at = None
        session.commit()
        session.refresh(session_obj)
        return AnalysisSessionDetailRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=0,
            job_count=0,
            match_count=0,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
            cv_documents=[],
            job_documents=[],
        )


@router.delete("/sessions/{session_id}", status_code=204, response_model=None)
def delete_analysis_session(session_id: int, delete_documents: bool = False) -> None:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

        if delete_documents:
            cv_docs  = session.scalars(select(CvDocument).where(CvDocument.session_id == session_id)).all()
            job_docs = session.scalars(select(JobDocument).where(JobDocument.session_id == session_id)).all()
            for doc in cv_docs:
                cleanup_removed_file(Path(doc.path), "cv")
                try: Path(doc.path).unlink(missing_ok=True)
                except Exception: pass
            for doc in job_docs:
                cleanup_removed_file(Path(doc.path), "job")
                try: Path(doc.path).unlink(missing_ok=True)
                except Exception: pass

        session.delete(session_obj)
        session.commit()
