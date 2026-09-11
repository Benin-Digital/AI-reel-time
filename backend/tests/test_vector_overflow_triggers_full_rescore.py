"""Test : les correspondances "vectoriel seulement" (au-dela du top-k par
similarite d'embedding) ne doivent jamais rester figees a ce score bon
marche -- un rescore complet doit se declencher automatiquement peu apres.

Contexte reel (production) : _vector_match_cv()/_vector_match_job() ne
lancent le moteur complet (cross-encoder + scoring structure) que pour les
`embedding_top_k` documents les plus proches par similarite vectorielle ;
le reste recoit un score "bon marche" (_vector_score(), une similarite
cosinus brute convertie en pourcentage, sans aucune decomposition par
composante). Cette similarite d'embedding-document-entier est un tres
mauvais proxy de la pertinence reelle (le style generique d'un CV/offre
professionnel en francais domine l'embedding, pas les competences
precises) : observe en production avec plusieurs candidats sans AUCUNE
des competences requises scores a 90%+ par ce chemin bon marche, restes
ainsi jusqu'a ce qu'un humain declenche manuellement "Relancer l'IA".

Desormais, des qu'au moins un candidat passe par le chemin bon marche,
un evenement "rescore" est mis en file pour le document qui vient d'etre
traite -- "rescore" force le moteur complet sur TOUS ses homologues (voir
_process_watch_event), remplacant le score bon marche sans intervention
humaine.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, JobDocument, MatchResult, ScoreResult
from app.schemas import ExtractedTextRead
from app.services.watcher import WatchEvent
import app.main as app_main


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CvDocument.__table__,
            JobDocument.__table__,
            MatchResult.__table__,
            ScoreResult.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    return factory


def _fake_extraction(path, content_hash: str) -> ExtractedTextRead:
    now = datetime.utcnow()
    return ExtractedTextRead(
        id=1, file_path=str(path), content_hash=content_hash,
        extracted_text="Développeur Python, compétences : Python, Django.",
        extraction_method="txt", extraction_success=True, error_message=None,
        created_at=now, updated_at=now,
    )


def test_new_cv_with_vector_overflow_queues_a_followup_rescore(tmp_path, monkeypatch, session_factory):
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    job_path = job_dir / "job.txt"
    job_path.write_text("Offre")
    cv_path = cv_dir / "cv.txt"
    cv_path.write_text("CV")

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", True)

    def fake_extract_and_persist(path, force_docling=False, force=False):
        return _fake_extraction(path, "hash-new")
    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)

    # Simulate this job landing beyond the CV's embedding_top_k: no job gets
    # the expensive full match, this one job_id is returned purely as a
    # vector distance for the cheap fallback.
    def fake_vector_match_cv(cv_doc, extraction):
        return set(), {1: 0.05}  # cosine distance 0.05 -> _vector_score ~95%
    monkeypatch.setattr(app_main, "_vector_match_cv", fake_vector_match_cv)

    with session_factory() as session:
        session.add(JobDocument(id=1, path=str(job_path), status="ready"))
        session.commit()

    rescore_calls = []
    monkeypatch.setattr(app_main, "_on_watch_event", lambda event: rescore_calls.append(event))

    app_main._score_against_counterparts(cv_path, "cv")

    with session_factory() as session:
        match = session.scalar(select(MatchResult))
        assert match is not None
        assert match.score == pytest.approx(95.0), "cheap vector score should have been persisted first"
        assert match.score_semantic is None, "no component breakdown from the cheap path"

    assert len(rescore_calls) == 1, "exactly one follow-up rescore must be queued for the overflow"
    queued = rescore_calls[0]
    assert isinstance(queued, WatchEvent)
    assert queued.path == cv_path
    assert queued.event_type == "rescore"


def test_no_overflow_means_no_followup_rescore(tmp_path, monkeypatch, session_factory):
    """When every counterpart got the full match (no vector overflow), no
    follow-up event should be queued -- would otherwise double-process
    every single upload for nothing."""
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    job_path = job_dir / "job.txt"
    job_path.write_text("Offre")
    cv_path = cv_dir / "cv.txt"
    cv_path.write_text("CV")

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", True)

    def fake_extract_and_persist(path, force_docling=False, force=False):
        return _fake_extraction(path, "hash-new")
    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)

    # This job is well within the top-k: fully matched, no overflow.
    def fake_vector_match_cv(cv_doc, extraction):
        return {1}, {}
    monkeypatch.setattr(app_main, "_vector_match_cv", fake_vector_match_cv)

    with session_factory() as session:
        session.add(JobDocument(id=1, path=str(job_path), status="ready"))
        session.commit()

    rescore_calls = []
    monkeypatch.setattr(app_main, "_on_watch_event", lambda event: rescore_calls.append(event))

    app_main._score_against_counterparts(cv_path, "cv")

    assert rescore_calls == []
