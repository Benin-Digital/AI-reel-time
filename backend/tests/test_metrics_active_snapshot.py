"""Test de non-regression : /metrics ne renvoyait que des compteurs
cumules a vie (event_count, extraction_count, score_count), qui ne
baissent jamais meme apres archivage -- rendant le Tableau de bord
incapable de refleter l'etat reel de la plateforme a un instant donne.

Ajoute : compteurs actifs vs archives (CV, offres) et le nombre de
correspondances actives (excluant tout match impliquant un document
archive).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.models import Base, CvDocument, EventLog, ExtractedText, JobDocument, MatchResult, ScoreResult
import app.routers.health as health_router


class _FakeAppState:
    started_at = 0
    worker = None


class _FakeApp:
    state = _FakeAppState()


class _FakeRequest:
    app = _FakeApp()


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CvDocument.__table__,
            JobDocument.__table__,
            MatchResult.__table__,
            EventLog.__table__,
            ExtractedText.__table__,
            ScoreResult.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(health_router, "SessionLocal", factory)
    return factory


def test_metrics_reports_active_vs_archived_counts_and_score_tiers(session_factory):
    with session_factory() as session:
        active_cv = CvDocument(path="/cv/active.pdf", status="ready", session_id=None)
        archived_cv = CvDocument(path="/cv/archived.pdf", status="ready", session_id=42)
        active_job = JobDocument(path="/job/active.pdf", status="ready", session_id=None)
        active_job_2 = JobDocument(path="/job/active2.pdf", status="ready", session_id=None)
        archived_job = JobDocument(path="/job/archived.pdf", status="ready", session_id=42)
        session.add_all([active_cv, archived_cv, active_job, active_job_2, archived_job])
        session.commit()

        # Deux matches actif <-> actif : doivent compter dans la repartition des scores.
        session.add(MatchResult(cv_id=active_cv.id, job_id=active_job.id, score=85.0))  # Fort
        session.add(MatchResult(cv_id=active_cv.id, job_id=active_job_2.id, score=65.0))  # Moyen
        # Match impliquant un document archive : ne doit PAS compter.
        session.add(MatchResult(cv_id=archived_cv.id, job_id=active_job.id, score=95.0))
        session.commit()

    result = health_router.metrics(_FakeRequest())

    assert result["active_cv_count"] == 1
    assert result["archived_cv_count"] == 1
    assert result["active_job_count"] == 2
    assert result["archived_job_count"] == 1
    assert result["active_match_count"] == 2, "le match contre un document archive ne doit pas compter"
