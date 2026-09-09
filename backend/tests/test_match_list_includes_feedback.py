"""Test de non-regression : la liste des matches (GET /matches) ne renvoyait
aucune information de feedback -- seule l'action explicite d'ouvrir la modale
"Analyser" pour un match precis declenchait un GET /matches/{id}/feedback
cote frontend, qui alimentait un cache en memoire (_feedbackCache, cote JS).

Consequence reelle observee en production : une evaluation deja enregistree
(decision/note/commentaire) redevenait invisible des qu'on rechargeait la
page ou revenait sur l'onglet Correspondances -- pas parce que la donnee
etait perdue en base, mais parce que la liste ne l'a jamais transportee.

Le fix ajoute feedback_decision/feedback_rating/feedback_comment a MatchRead,
peuples par un batch-fetch (_build_feedback_map) de la derniere ligne
MatchFeedback par match_id, cote /matches, /cv-documents/{id}/matches,
/job-documents/{id}/matches et /matches/{id}.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.models import Base, CvDocument, ExtractedText, JobDocument, MatchFeedback, MatchResult
import app.routers.matches as matches_router


@pytest.fixture
def session_factory(monkeypatch):
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
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(matches_router, "SessionLocal", factory)
    return factory


def _seed_match(factory: sessionmaker) -> int:
    with factory() as session:
        cv = CvDocument(path="/cv/1.pdf", status="ready")
        job = JobDocument(path="/job/1.pdf", status="ready")
        session.add_all([cv, job])
        session.commit()
        match = MatchResult(cv_id=cv.id, job_id=job.id, score=80.0)
        session.add(match)
        session.commit()
        return match.id


def test_list_matches_includes_persisted_feedback(session_factory):
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="accept", rating=5, comment="Tres bon profil"))
        session.commit()

    results = matches_router.list_matches()

    assert len(results) == 1
    assert results[0].feedback_decision == "accept"
    assert results[0].feedback_rating == 5
    assert results[0].feedback_comment == "Tres bon profil"


def test_list_matches_returns_none_when_no_feedback_yet(session_factory):
    _seed_match(session_factory)

    results = matches_router.list_matches()

    assert len(results) == 1
    assert results[0].feedback_decision is None
    assert results[0].feedback_rating is None
    assert results[0].feedback_comment is None


def test_list_matches_uses_the_most_recent_feedback_row(session_factory):
    """Chaque feedback cree une nouvelle ligne (jamais un update) -- la plus
    recente doit gagner, exactement comme GET /matches/{id}/feedback."""
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="review", rating=3, comment="A verifier"))
        session.commit()
        session.add(MatchFeedback(match_id=match_id, decision="accept", rating=5, comment="Finalement excellent"))
        session.commit()

    results = matches_router.list_matches()

    assert results[0].feedback_decision == "accept"
    assert results[0].feedback_comment == "Finalement excellent"


def test_get_match_includes_persisted_feedback(session_factory):
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="reject", rating=1, comment="Pas assez d'experience"))
        session.commit()

    result = matches_router.get_match(match_id)

    assert result.feedback_decision == "reject"
    assert result.feedback_rating == 1
    assert result.feedback_comment == "Pas assez d'experience"
