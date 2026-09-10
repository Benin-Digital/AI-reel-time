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


def test_match_progress_reflects_active_counts_and_computed_pairs(session_factory):
    """GET /matches/progress lets the frontend show 'calcul en cours' instead
    of 'aucune correspondance' while documents are "ready" but their
    matching loop hasn't finished (status flips to ready before matching
    runs -- see _score_against_counterparts in main.py)."""
    with session_factory() as session:
        cv1 = CvDocument(path="/cv/1.pdf", status="ready", session_id=None)
        cv2 = CvDocument(path="/cv/2.pdf", status="ready", session_id=None)
        archived_cv = CvDocument(path="/cv/archived.pdf", status="ready", session_id=99)
        job1 = JobDocument(path="/job/1.pdf", status="ready", session_id=None)
        session.add_all([cv1, cv2, archived_cv, job1])
        session.commit()
        # Seulement 1 des 2 paires actives attendues a ete matchee.
        session.add(MatchResult(cv_id=cv1.id, job_id=job1.id, score=80.0))
        # Un match contre un CV archive ne doit pas compter dans le calcul.
        session.add(MatchResult(cv_id=archived_cv.id, job_id=job1.id, score=50.0))
        session.commit()

    progress = matches_router.get_match_progress()

    assert progress.active_cv_count == 2
    assert progress.active_job_count == 1
    assert progress.expected_pairs == 2
    assert progress.computed_pairs == 1, "le match contre le CV archive ne doit pas etre compte"


def test_match_progress_unreviewed_count_excludes_matches_with_feedback(session_factory):
    """unreviewed_count alimente le badge "Correspondances" de la barre
    laterale -- ne doit compter que les matches actifs sans AUCUNE ligne
    de feedback, jamais ceux deja evalues ni ceux contre un document
    archive."""
    with session_factory() as session:
        cv1 = CvDocument(path="/cv/1.pdf", status="ready", session_id=None)
        cv2 = CvDocument(path="/cv/2.pdf", status="ready", session_id=None)
        archived_cv = CvDocument(path="/cv/archived.pdf", status="ready", session_id=99)
        job1 = JobDocument(path="/job/1.pdf", status="ready", session_id=None)
        session.add_all([cv1, cv2, archived_cv, job1])
        session.commit()
        reviewed = MatchResult(cv_id=cv1.id, job_id=job1.id, score=80.0)
        unreviewed = MatchResult(cv_id=cv2.id, job_id=job1.id, score=70.0)
        archived_match = MatchResult(cv_id=archived_cv.id, job_id=job1.id, score=60.0)
        session.add_all([reviewed, unreviewed, archived_match])
        session.commit()
        session.add(MatchFeedback(match_id=reviewed.id, decision="accept"))
        session.commit()

    progress = matches_router.get_match_progress()

    assert progress.unreviewed_count == 1


def test_get_match_includes_persisted_feedback(session_factory):
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="reject", rating=1, comment="Pas assez d'experience"))
        session.commit()

    result = matches_router.get_match(match_id)

    assert result.feedback_decision == "reject"
    assert result.feedback_rating == 1
    assert result.feedback_comment == "Pas assez d'experience"
