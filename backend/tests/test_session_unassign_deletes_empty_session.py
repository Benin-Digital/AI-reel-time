"""Test de non-regression : desarchiver une session (POST
/sessions/{id}/unassign) detachait bien ses CV/offres mais laissait
toujours la session elle-meme en base, vide (status="open", 0 CV/0
offre/0 match) -- signale en direct par l'utilisateur (2026-09-15) : la
page Archives continuait d'afficher ce lot ("Lot rhconsole - Session 2,
Ouverte, 0 CV, 0 offres, 0 matches") indefiniment apres chaque
desarchivage, puisque seuls les documents etaient detaches, jamais
l'enregistrement de session lui-meme.

Le correctif supprime la session (comme delete_analysis_session le fait
deja quand on la ferme definitivement, sans toucher aux fichiers) une
fois ses documents detaches.
"""
from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import pytest

from app.models import AnalysisSession, Base, CvDocument, JobDocument
import app.routers.sessions as sessions_router


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[AnalysisSession.__table__, CvDocument.__table__, JobDocument.__table__],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(sessions_router, "SessionLocal", factory)
    return factory


def test_unassign_deletes_the_now_empty_session(session_factory):
    with session_factory() as session:
        archive = AnalysisSession(name="Lot rhconsole - Session 2", status="closed")
        session.add(archive)
        session.commit()
        session.refresh(archive)
        session_id = archive.id
        session.add(CvDocument(path="/cv/1.pdf", status="ready", session_id=session_id))
        session.add(JobDocument(path="/job/1.pdf", status="ready", session_id=session_id))
        session.commit()

    result = sessions_router.unassign_session_documents(session_id)

    assert result.cv_count == 0
    assert result.job_count == 0
    assert result.status == "open"

    with session_factory() as session:
        assert session.get(AnalysisSession, session_id) is None, (
            "la session vide doit disparaitre completement, pas juste "
            "rester avec des compteurs a zero"
        )
        cv = session.scalars(select(CvDocument)).one()
        job = session.scalars(select(JobDocument)).one()
        assert cv.session_id is None, "le CV doit redevenir actif (session_id NULL)"
        assert job.session_id is None, "l'offre doit redevenir active (session_id NULL)"


def test_unassign_missing_session_raises_404(session_factory):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        sessions_router.unassign_session_documents(999)
    assert exc_info.value.status_code == 404
