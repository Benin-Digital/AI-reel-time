"""Tests de non-regression : un document archive (session_id defini sur une
session d'analyse fermee) restait matche contre chaque nouveau CV/offre
ajoute -- des "matches fantomes" dans les termes du rapport utilisateur.

Root cause : l'archivage (POST /sessions/{id}/assign) ne fait que definir
CvDocument.session_id / JobDocument.session_id, ce qui filtre uniquement le
listage du dashboard (GET /cv-documents, /job-documents avec
session_id IS NULL par defaut). Le moteur de matching lui-meme --
_score_against_counterparts() (boucle sur les fichiers du dossier surveille)
et _vector_match_cv()/_vector_match_job() (requete par similarite
d'embeddings) -- ignorait entierement session_id et matchait donc tout
nouveau document contre l'integralite des fichiers/embeddings presents,
archives ou non.

Fix : _score_against_counterparts() ignore desormais tout candidat dont le
document (apres upsert) a un session_id non nul ; _vector_match_cv()/
_vector_match_job() filtrent leur requete d'embeddings sur
session_id IS NULL.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, JobDocument, MatchResult, ScoreResult
from app.schemas import ExtractedTextRead
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
        id=1,
        file_path=str(path),
        content_hash=content_hash,
        extracted_text="Développeur Python, compétences : Python, Django.",
        extraction_method="txt",
        extraction_success=True,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def test_archived_job_is_excluded_when_a_new_cv_is_added(session_factory, tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    archived_job_path = job_dir / "archived.txt"
    archived_job_path.write_text("Offre archivée")
    active_job_path = job_dir / "active.txt"
    active_job_path.write_text("Offre active")
    cv_path = cv_dir / "cv.txt"
    cv_path.write_text("CV candidat")

    with session_factory() as session:
        session.add(JobDocument(
            path=str(archived_job_path), content_hash="same-hash",
            status="ready", session_id=42,
        ))
        session.commit()

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)

    def fake_extract_and_persist(path, force_docling=False, force=False):
        # Le job archive garde exactement le meme hash pour que l'upsert ne
        # le desarchive pas malgre lui (voir le commentaire de
        # _upsert_job_document sur content_changed).
        content_hash = "same-hash" if path == archived_job_path else "hash-new"
        return _fake_extraction(path, content_hash)

    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    monkeypatch.setattr(app_main, "score_texts", lambda cv_text, job_text: (77.0, ["Python"]))

    app_main._score_against_counterparts(cv_path, "cv")

    with session_factory() as session:
        matches = session.scalars(select(MatchResult)).all()
        matched_job_paths = {session.get(JobDocument, m.job_id).path for m in matches}

    assert str(active_job_path) in matched_job_paths, "l'offre active doit etre matchee normalement"
    assert str(archived_job_path) not in matched_job_paths, (
        "l'offre archivee ne doit jamais recevoir de nouveau match (match fantome)"
    )


def test_archived_cv_is_excluded_when_a_new_job_is_added(session_factory, tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    archived_cv_path = cv_dir / "archived.txt"
    archived_cv_path.write_text("CV archivé")
    active_cv_path = cv_dir / "active.txt"
    active_cv_path.write_text("CV actif")
    job_path = job_dir / "job.txt"
    job_path.write_text("Offre candidate")

    with session_factory() as session:
        session.add(CvDocument(
            path=str(archived_cv_path), content_hash="same-hash",
            status="ready", session_id=7,
        ))
        session.commit()

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)
    monkeypatch.setattr(app_main.settings, "auto_create_job_offer", False)

    def fake_extract_and_persist(path, force_docling=False, force=False):
        content_hash = "same-hash" if path == archived_cv_path else "hash-new"
        return _fake_extraction(path, content_hash)

    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    monkeypatch.setattr(app_main, "score_texts", lambda cv_text, job_text: (77.0, ["Python"]))

    app_main._score_against_counterparts(job_path, "job")

    with session_factory() as session:
        matches = session.scalars(select(MatchResult)).all()
        matched_cv_paths = {session.get(CvDocument, m.cv_id).path for m in matches}

    assert str(active_cv_path) in matched_cv_paths, "le CV actif doit etre matche normalement"
    assert str(archived_cv_path) not in matched_cv_paths, (
        "le CV archive ne doit jamais recevoir de nouveau match (match fantome)"
    )
