"""Test : le composant score_priority_keywords est bien persiste sur
MatchResult, pas seulement calcule en memoire.

_score_against_counterparts() appelait score_texts() (score, common
keywords seulement -- tout le detail des composantes, y compris les
mots-cles prioritaires, etait jete) au lieu de match_cv_to_job() (le
MatchScore complet). Corrige en meme temps que l'ajout de la composante
mots-cles prioritaires -- ce test verifie que les colonnes
score_priority_keywords / priority_keywords_matched_count /
priority_keywords_total arrivent bien jusqu'en base, avec le vrai moteur
de scoring (pas de mock sur match_cv_to_job)."""
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


def test_bulk_ingestion_persists_priority_keywords_columns(session_factory, tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    cv_path = cv_dir / "cv.txt"
    cv_path.write_text("CV")
    job_path = job_dir / "job.txt"
    job_path.write_text("Offre")

    with session_factory() as session:
        job = JobDocument(
            path=str(job_path), status="ready", session_id=None,
            priority_keywords="gouvernance\nLOD2\nISO 27001",
        )
        session.add(job)
        session.commit()

    def fake_extract_and_persist(path, force_docling=False, force=False):
        now = datetime.utcnow()
        text = (
            "Consultant gouvernance et LOD2, tres experimente."
            if path == cv_path
            else "Poste: Analyste risque. Compétences requises: gouvernance."
        )
        return ExtractedTextRead(
            id=1, file_path=str(path), content_hash="hash",
            extracted_text=text, extraction_method="txt",
            extraction_success=True, error_message=None,
            created_at=now, updated_at=now,
        )

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)
    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)

    app_main._score_against_counterparts(cv_path, "cv")

    with session_factory() as session:
        match = session.scalar(select(MatchResult))

    assert match.priority_keywords_total == 3
    assert match.priority_keywords_matched_count == 2, "gouvernance et LOD2 presents, ISO 27001 absent"
    assert match.score_priority_keywords == pytest.approx(2 / 3, abs=1e-3)
