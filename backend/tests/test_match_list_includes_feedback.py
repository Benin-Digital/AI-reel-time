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

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.models import AnalysisSession, Base, CvDocument, ExtractedText, JobDocument, MatchFeedback, MatchResult, User
import app.routers.matches as matches_router


def _fake_request(user: User) -> SimpleNamespace:
    """Every /matches* endpoint now needs request.state.user (2026-09-24
    archive-visibility fix) -- a bare SimpleNamespace is enough since these
    endpoints only ever read that one attribute off the request."""
    return SimpleNamespace(state=SimpleNamespace(user=user))


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            AnalysisSession.__table__,
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


@pytest.fixture
def member_user(session_factory) -> User:
    with session_factory() as session:
        user = User(email="member@test.local", password_hash="x", role="member")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


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


def test_list_matches_includes_persisted_feedback(session_factory, member_user):
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="accept", rating=5, comment="Tres bon profil"))
        session.commit()

    results = matches_router.list_matches(_fake_request(member_user))

    assert len(results) == 1
    assert results[0].feedback_decision == "accept"
    assert results[0].feedback_rating == 5
    assert results[0].feedback_comment == "Tres bon profil"


def test_list_matches_returns_none_when_no_feedback_yet(session_factory, member_user):
    _seed_match(session_factory)

    results = matches_router.list_matches(_fake_request(member_user))

    assert len(results) == 1
    assert results[0].feedback_decision is None
    assert results[0].feedback_rating is None
    assert results[0].feedback_comment is None


def test_list_matches_uses_the_most_recent_feedback_row(session_factory, member_user):
    """Chaque feedback cree une nouvelle ligne (jamais un update) -- la plus
    recente doit gagner, exactement comme GET /matches/{id}/feedback."""
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="review", rating=3, comment="A verifier"))
        session.commit()
        session.add(MatchFeedback(match_id=match_id, decision="accept", rating=5, comment="Finalement excellent"))
        session.commit()

    results = matches_router.list_matches(_fake_request(member_user))

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


def test_get_match_includes_persisted_feedback(session_factory, member_user):
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="reject", rating=1, comment="Pas assez d'experience"))
        session.commit()

    result = matches_router.get_match(match_id, _fake_request(member_user))

    assert result.feedback_decision == "reject"
    assert result.feedback_rating == 1
    assert result.feedback_comment == "Pas assez d'experience"


def test_list_matches_includes_component_scores(session_factory, member_user):
    """Regression reelle (2026-09-14) : GET /matches ne renvoyait jamais
    score_skills/score_semantic/etc. -- le detail par composant du
    frontend (_renderComponentScores) restait donc vide pour TOUS les
    matches, pas seulement les scores provisoires, et le frontend n'avait
    aucun moyen de distinguer un score complet d'un score cheap
    (vectoriel seul, tous les composants a NULL -- voir le meme marqueur
    dans _matched_all_active_counterparts, main.py)."""
    with session_factory() as session:
        cv = CvDocument(path="/cv/1.pdf", status="ready")
        job = JobDocument(path="/job/1.pdf", status="ready")
        session.add_all([cv, job])
        session.commit()
        session.add(MatchResult(
            cv_id=cv.id, job_id=job.id, score=80.0,
            score_semantic=0.7, score_skills=0.9, score_experience=0.6,
            score_education=0.5, score_languages=1.0, score_contract=0.8,
            match_domain="tech",
        ))
        session.commit()

    results = matches_router.list_matches(_fake_request(member_user))

    assert results[0].score_skills == 0.9
    assert results[0].score_semantic == 0.7
    assert results[0].score_experience == 0.6
    assert results[0].score_education == 0.5
    assert results[0].score_languages == 1.0
    assert results[0].score_contract == 0.8
    assert results[0].match_domain == "tech"


def test_list_matches_leaves_component_scores_null_for_a_provisional_match(session_factory, member_user):
    """Non-regression : un match encore au stade cheap-vectoriel (voir
    matcher.py's embedding_top_k) doit continuer a montrer des
    composants a None, pas des zeros -- c'est ce qui permet au frontend
    de distinguer 'pas encore calcule' de 'calcule et faible'."""
    _seed_match(session_factory)  # score=80.0, aucun composant fourni

    results = matches_router.list_matches(_fake_request(member_user))

    assert results[0].score_skills is None
    assert results[0].score_semantic is None


def test_list_matches_includes_priority_keywords_missing(session_factory, member_user):
    """La carte de correspondance (frontend) affiche desormais le NOM de
    chaque mot-cle prioritaire manquant, pas seulement le compte -- sans
    passer par GET /matches/{id}/explain (recalcul complet, couteux).
    Necessite que GET /matches transporte bien la colonne persistee."""
    with session_factory() as session:
        cv = CvDocument(path="/cv/1.pdf", status="ready")
        job = JobDocument(path="/job/1.pdf", status="ready")
        session.add_all([cv, job])
        session.commit()
        session.add(MatchResult(
            cv_id=cv.id, job_id=job.id, score=80.0, score_skills=0.9,
            priority_keywords_matched_count=1, priority_keywords_total=3,
            priority_keywords_missing="DORA,TRM",
        ))
        session.commit()

    results = matches_router.list_matches(_fake_request(member_user))

    assert set(results[0].priority_keywords_missing) == {"DORA", "TRM"}


def test_list_matches_priority_keywords_missing_defaults_to_empty_list(session_factory, member_user):
    _seed_match(session_factory)

    results = matches_router.list_matches(_fake_request(member_user))

    assert results[0].priority_keywords_missing == []


def _read_csv_body(response) -> str:
    import asyncio

    async def _collect():
        return "".join([chunk async for chunk in response.body_iterator])

    return asyncio.run(_collect())


def test_export_matches_csv_includes_header_and_row(session_factory, member_user):
    match_id = _seed_match(session_factory)
    with session_factory() as session:
        session.add(MatchFeedback(match_id=match_id, decision="accept", rating=4, comment="Bon profil"))
        session.commit()

    response = matches_router.export_matches_csv(_fake_request(member_user))
    body = _read_csv_body(response)
    lines = body.lstrip("﻿").splitlines()

    assert lines[0].split(",")[:3] == ["match_id", "score", "cv_id"]
    assert len(lines) == 2, "une ligne d'en-tete + une ligne de donnees"
    assert "accept" in lines[1]
    assert "Bon profil" in lines[1]


def test_export_matches_csv_has_utf8_bom_for_excel(session_factory, member_user):
    _seed_match(session_factory)

    response = matches_router.export_matches_csv(_fake_request(member_user))
    body = _read_csv_body(response)

    assert body.startswith("﻿"), "sans BOM, Excel affiche des accents corrompus (mojibake)"


def test_export_matches_csv_respects_the_same_filters_as_list_matches(session_factory, member_user):
    """L'export doit refleter exactement ce que le recruteur voit a l'ecran
    -- pas de derive possible entre GET /matches et /matches/export.csv
    puisque les deux partagent _build_match_filter_stmt."""
    with session_factory() as session:
        cv = CvDocument(path="/cv/1.pdf", status="ready")
        job1 = JobDocument(path="/job/1.pdf", status="ready")
        job2 = JobDocument(path="/job/2.pdf", status="ready")
        session.add_all([cv, job1, job2])
        session.commit()
        session.add_all([
            MatchResult(cv_id=cv.id, job_id=job1.id, score=90.0),
            MatchResult(cv_id=cv.id, job_id=job2.id, score=10.0),
        ])
        session.commit()

    response = matches_router.export_matches_csv(_fake_request(member_user), min_score=50.0)
    body = _read_csv_body(response)
    lines = body.lstrip("﻿").splitlines()

    assert len(lines) == 2, "seul le match >= 50 doit apparaitre dans l'export"
    assert "90.0" in lines[1] or "90" in lines[1]
