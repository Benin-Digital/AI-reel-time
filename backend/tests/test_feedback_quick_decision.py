"""Test de non-regression : un clic de decision rapide (liste des matches)
n'envoie que {decision}, sans rating ni commentaire. Comme chaque feedback
cree une nouvelle ligne MatchFeedback (le GET renvoie toujours la plus
recente), ce clic ecrasait silencieusement un commentaire deja saisi
depuis la page d'evaluation en creant une ligne avec comment=None.

Le fix fait remonter rating/comment de la derniere ligne existante quand
ces champs sont absents du payload (feedback rapide), tout en laissant un
envoi explicite a null (formulaire complet, champ vide) effacer la valeur.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, CvDocument, ExtractedText, JobDocument, MatchFeedback, MatchResult
from app.schemas import MatchFeedbackCreate
import app.routers.feedback as feedback_router


class _FakeState:
    user = object()


class _FakeRequest:
    state = _FakeState()


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
    monkeypatch.setattr(feedback_router, "SessionLocal", factory)
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


def test_quick_decision_preserves_previous_comment_and_rating(session_factory):
    match_id = _seed_match(session_factory)

    feedback_router.create_match_feedback(
        match_id,
        MatchFeedbackCreate(decision="review", rating=4, comment="Bon profil, manque Docker"),
        _FakeRequest(),
    )

    # Quick decision button: only "decision" is set on the model, rating/comment
    # were never touched — model_fields_set must reflect that.
    quick_payload = MatchFeedbackCreate(decision="accept")
    assert quick_payload.model_fields_set == {"decision"}

    result = feedback_router.create_match_feedback(match_id, quick_payload, _FakeRequest())

    assert result.decision == "accept"
    assert result.comment == "Bon profil, manque Docker", "le commentaire precedent doit survivre a un clic rapide"
    assert result.rating == 4, "la note precedente doit survivre a un clic rapide"

    latest = feedback_router.get_match_feedback(match_id, _FakeRequest())
    assert latest.comment == "Bon profil, manque Docker"
    assert latest.rating == 4


def test_full_form_can_explicitly_clear_comment(session_factory):
    match_id = _seed_match(session_factory)

    feedback_router.create_match_feedback(
        match_id,
        MatchFeedbackCreate(decision="review", rating=3, comment="A verifier"),
        _FakeRequest(),
    )

    # Full evaluation form always sends comment/rating explicitly, even when
    # cleared — this must NOT be treated as "omitted" and must actually clear.
    cleared_payload = MatchFeedbackCreate(decision="accept", rating=None, comment=None)
    assert cleared_payload.model_fields_set == {"decision", "rating", "comment"}

    result = feedback_router.create_match_feedback(match_id, cleared_payload, _FakeRequest())

    assert result.comment is None
    assert result.rating is None
