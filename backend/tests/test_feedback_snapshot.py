"""Tests de non-regression pour l'instantane de feedback (MatchFeedback).

Contexte : deps.cleanup_removed_file supprime en cascade les MatchResult
lies a un CV ou une offre supprime(e). Sans instantane, un MatchFeedback
(l'avis + commentaire d'un RH) se retrouvait orpheline dans ce cas : plus
aucun moyen de savoir quel CV/offre/score elle concernait.

Ce test verifie que le feedback (et son instantane CV/offre/scores) reste
lisible meme apres suppression du MatchResult, du CvDocument et du
JobDocument d'origine.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    CvDocument,
    ExtractedText,
    JobDocument,
    MatchFeedback,
    MatchResult,
)
from app.schemas import MatchFeedbackExportRead


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CvDocument.__table__,
            JobDocument.__table__,
            ExtractedText.__table__,
            MatchResult.__table__,
            MatchFeedback.__table__,
        ],
    )
    with Session(engine) as s:
        yield s


def _seed_match(session: Session) -> MatchResult:
    cv = CvDocument(path="/cv/1.pdf", status="ready")
    job = JobDocument(path="/job/1.pdf", status="ready")
    session.add_all([cv, job])
    session.commit()

    session.add_all([
        ExtractedText(file_path="/cv/1.pdf", extracted_text="CV: Python Django"),
        ExtractedText(file_path="/job/1.pdf", extracted_text="Job: Python Kubernetes"),
    ])
    session.commit()

    match = MatchResult(
        cv_id=cv.id, job_id=job.id, score=42.0, common_keywords="python",
        score_semantic=0.5, score_skills=0.5, score_experience=0.5,
        score_education=0.5, score_languages=0.5, score_contract=0.5,
        match_domain="tech",
    )
    session.add(match)
    session.commit()
    return match


def test_feedback_snapshot_survives_source_deletion(session: Session):
    match = _seed_match(session)

    feedback = MatchFeedback(
        match_id=match.id,
        decision="reject",
        rating=2,
        comment="Manque Kubernetes",
        cv_text_snapshot="CV: Python Django",
        job_text_snapshot="Job: Python Kubernetes",
        scores_snapshot={"score": 42.0, "domain": "tech", "score_skills": 0.5},
    )
    session.add(feedback)
    session.commit()
    feedback_id = feedback.id

    # Simulate deps.cleanup_removed_file: the CV/job files are removed,
    # cascading to delete their CvDocument/JobDocument/MatchResult rows.
    session.query(MatchResult).delete()
    session.query(CvDocument).delete()
    session.query(JobDocument).delete()
    session.commit()

    survivor = session.get(MatchFeedback, feedback_id)
    assert survivor is not None, "le feedback ne doit pas etre supprime en cascade"
    assert survivor.cv_text_snapshot == "CV: Python Django"
    assert survivor.job_text_snapshot == "Job: Python Kubernetes"
    assert survivor.scores_snapshot == {"score": 42.0, "domain": "tech", "score_skills": 0.5}

    exported = MatchFeedbackExportRead.model_validate(survivor)
    assert exported.decision == "reject"
    assert exported.comment == "Manque Kubernetes"
    assert exported.cv_text_snapshot == "CV: Python Django"
