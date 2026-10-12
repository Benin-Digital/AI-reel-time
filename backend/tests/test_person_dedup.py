"""Doublons de personnes dans le classement d'une offre.

Une meme personne apparaissait plusieurs fois (constate le 2026-10-12 sur la
plateforme soeur Keoni : rangs 7, 8 et 9, "OUENJLI ABDELGHAFOUR" /
"ABDELGHAFOUR OUENJLI"). GET /matches et son export CSV, filtres sur une offre,
ne gardent maintenant que la meilleure candidature de chaque personne.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.routers.matches as matches_router
from app.models import (
    AnalysisSession, Base, CvDocument, ExtractedText, JobDocument, MatchFeedback, MatchResult, User,
)
from app.services.identity import normalize_person_name


# ── Doublons de personnes ────────────────────────────────────────────────────

def test_person_name_ignores_order_accents_and_case():
    assert normalize_person_name("Abdelghafour OUENJLI") == normalize_person_name("ouenjli abdelghafour")
    assert normalize_person_name("Hélène Müller") == normalize_person_name("MULLER helene")


def test_a_single_word_name_identifies_nobody():
    assert normalize_person_name("Dupont") is None
    assert normalize_person_name(None) is None
    assert normalize_person_name("") is None


def _fake_request(user: User) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=user))


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, AnalysisSession.__table__, CvDocument.__table__, JobDocument.__table__,
                ExtractedText.__table__, MatchResult.__table__, MatchFeedback.__table__],
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


def _seed_ranking(factory):
    """Une offre ; 5 CV : trois candidatures de la meme personne (nom dans un
    ordre different), une autre personne, un CV sans nom exploitable."""
    with factory() as session:
        job = JobDocument(path="/job/devsecops.pdf", status="ready")
        session.add(job)
        people = [
            ("/cv/a1.pdf", "Abdelghafour Ouenjli", 70.0),
            ("/cv/a2.pdf", "OUENJLI Abdelghafour", 72.0),   # meme personne, meilleur score
            ("/cv/a3.pdf", "Ouenjli Abdelghafour", 69.0),
            ("/cv/b1.pdf", "Marie Curie", 71.0),
            ("/cv/c1.pdf", None, 68.0),                       # pas de nom : jamais fusionne
        ]
        session.flush()
        for path, name, score in people:
            cv = CvDocument(path=path, status="ready")
            session.add(cv)
            session.flush()
            session.add(ExtractedText(file_path=path, parsed_profile={"person_name": name} if name else {}))
            session.add(MatchResult(cv_id=cv.id, job_id=job.id, score=score))
        session.commit()
        return job.id


def test_a_job_ranking_lists_each_person_once_with_their_best_score(session_factory, member_user):
    job_id = _seed_ranking(session_factory)
    result = matches_router.list_matches(_fake_request(member_user), job_id=job_id, page=1, page_size=10)
    assert [r.score for r in result] == [72.0, 71.0, 68.0]


def test_dedup_pagination_is_applied_after_merging(session_factory, member_user):
    job_id = _seed_ranking(session_factory)
    first = matches_router.list_matches(_fake_request(member_user), job_id=job_id, page=1, page_size=2)
    second = matches_router.list_matches(_fake_request(member_user), job_id=job_id, page=2, page_size=2)
    assert [r.score for r in first] == [72.0, 71.0]
    assert [r.score for r in second] == [68.0]


def test_dedup_can_be_switched_off(session_factory, member_user, monkeypatch):
    job_id = _seed_ranking(session_factory)
    monkeypatch.setattr(matches_router, "get_settings", lambda: SimpleNamespace(match_dedupe_persons=False))
    result = matches_router.list_matches(_fake_request(member_user), job_id=job_id, page=1, page_size=10)
    assert len(result) == 5


def test_csv_export_of_a_job_is_deduplicated_too(session_factory, member_user):
    job_id = _seed_ranking(session_factory)
    response = matches_router.export_matches_csv(_fake_request(member_user), job_id=job_id)
    async def _collect():
        return [chunk async for chunk in response.body_iterator]

    body = "".join(c.decode() if isinstance(c, bytes) else c for c in asyncio.run(_collect()))
    # En-tete + 3 lignes.
    assert len([line for line in body.strip().splitlines() if line]) == 4
