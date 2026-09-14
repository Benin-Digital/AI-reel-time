"""Test de non-regression : un match reste bloque a un score provisoire
(cheap vector-only, tous les composants a NULL) pour toujours si
_matched_all_active_counterparts() le compte comme "deja matche".

Contexte reel (production, decouvert le 2026-09-14) : 3 MatchResult
crees le 2026-09-11 (cv Guillaume Saha, cv Jules Pountougnigni contre
l'offre "Data Analyst Expert SAS") sont restes avec score_semantic/
skills/experience/etc. tous NULL pendant plus de 3 jours, survivant a
plusieurs deploiements et evenements d'ingestion sans rapport. Cause :
un candidat au-dela de embedding_top_k recoit d'abord un score "cheap"
vectoriel seul (cs={}), avec un evenement de rescore de rattrapage mis
en file pour le completer -- mais _matched_all_active_counterparts()
comptait CETTE ligne cheap comme "deja matche" des sa creation, donc le
raccourci "rien a refaire" pouvait se declencher avant meme que le
rattrapage n'ait eu lieu (ou si la contrepartie etait archivee entre
les deux), gelant le score incomplet pour toujours -- rien ne le
retouchera plus jamais tant que ce raccourci le protege.

Fix : la verification exige desormais score_skills IS NOT NULL, un
marqueur fiable de "est passe par le pipeline complet au moins une
fois" (toujours un vrai float depuis ce pipeline, toujours NULL depuis
la branche vectorielle cheap).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, JobDocument, MatchResult
import app.main as app_main


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CvDocument.__table__, JobDocument.__table__, MatchResult.__table__],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    return factory


def test_cheap_only_match_does_not_count_as_fully_matched(session_factory):
    """Regression reelle : un candidat dont l'UNIQUE match actif est un
    score cheap (composants NULL) ne doit jamais etre considere comme
    'deja matche' -- sinon rien ne le retouchera plus jamais."""
    with session_factory() as session:
        cv = CvDocument(path="/cv/1.pdf", status="ready", session_id=None)
        job = JobDocument(path="/job/1.docx", status="ready", session_id=None)
        session.add_all([cv, job])
        session.commit()
        # Score "cheap" vectoriel seul, exactement comme _upsert_match_result
        # le produit quand cs={} (voir le commentaire dans main.py) :
        # score_skills (et tous les autres composants) restent NULL.
        session.add(MatchResult(cv_id=cv.id, job_id=job.id, score=42.0, score_skills=None))
        session.commit()
        cv_id, job_id = cv.id, job.id

    assert app_main._matched_all_active_counterparts(cv_id, "cv") is False
    assert app_main._matched_all_active_counterparts(job_id, "job") is False


def test_complete_match_still_counts_as_fully_matched(session_factory):
    """Non-regression : un match ayant reellement traverse le pipeline
    complet (score_skills renseigne) continue de compter normalement."""
    with session_factory() as session:
        cv = CvDocument(path="/cv/1.pdf", status="ready", session_id=None)
        job = JobDocument(path="/job/1.docx", status="ready", session_id=None)
        session.add_all([cv, job])
        session.commit()
        session.add(MatchResult(cv_id=cv.id, job_id=job.id, score=77.0, score_skills=0.9))
        session.commit()
        cv_id, job_id = cv.id, job.id

    assert app_main._matched_all_active_counterparts(cv_id, "cv") is True
    assert app_main._matched_all_active_counterparts(job_id, "job") is True


def test_mix_of_complete_and_cheap_matches_is_not_fully_matched(session_factory):
    """Un CV matche completement contre une offre mais seulement au
    stade cheap contre une seconde offre active ne doit pas etre
    considere comme entierement matche."""
    with session_factory() as session:
        cv = CvDocument(path="/cv/1.pdf", status="ready", session_id=None)
        job_complete = JobDocument(path="/job/complete.docx", status="ready", session_id=None)
        job_cheap = JobDocument(path="/job/cheap.docx", status="ready", session_id=None)
        session.add_all([cv, job_complete, job_cheap])
        session.commit()
        session.add(MatchResult(cv_id=cv.id, job_id=job_complete.id, score=80.0, score_skills=0.8))
        session.add(MatchResult(cv_id=cv.id, job_id=job_cheap.id, score=30.0, score_skills=None))
        session.commit()
        cv_id = cv.id

    assert app_main._matched_all_active_counterparts(cv_id, "cv") is False
