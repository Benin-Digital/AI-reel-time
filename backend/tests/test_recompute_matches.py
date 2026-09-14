"""Tests : rescoring force via POST /matches/recompute.

Contexte : apres un deploy qui change matcher.py/parser.py/taxonomy.py
(un fix de scoring, par exemple), les MatchResult existants restent
calcules avec l'ANCIEN code tant que rien ne "change" cote document --
_score_against_counterparts() saute deliberement tout document dont le
contenu est inchange et deja matche contre toutes ses contreparties
actives (voir test_reactivated_document_rematches.py). Un recruteur n'a
alors aucun moyen de voir l'effet d'un fix de scoring sur des matches
deja calcules sans re-uploader chaque document.

_score_against_counterparts(force=True) contourne ce saut -- et le
raccourci d'embedding (top-K vectoriel) -- pour que chaque paire repasse
par le pipeline complet match_cv_to_job(), peu importe si le contenu ou le
statut de matching n'a pas change.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, JobDocument, MatchResult, ScoreResult
from app.schemas import ExtractedTextRead
from app.services.matcher import MatchScore
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


def _setup(session_factory, tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    cv_path = cv_dir / "cv.txt"
    cv_path.write_text("CV")
    job_path = job_dir / "job.txt"
    job_path.write_text("Offre")

    with session_factory() as session:
        cv = CvDocument(path=str(cv_path), content_hash="same-hash", status="ready", session_id=None)
        job = JobDocument(path=str(job_path), content_hash="job-hash", status="ready", session_id=None)
        session.add_all([cv, job])
        session.commit()
        # Deja matche contre TOUTE contrepartie active -> le raccourci de
        # saut se declenche normalement (voir _matched_all_active_counterparts).
        session.add(MatchResult(cv_id=cv.id, job_id=job.id, score=55.0))
        session.commit()

    extract_calls: list[bool] = []

    def fake_extract_and_persist(path, force_docling=False, force=False):
        extract_calls.append(force)
        return _fake_extraction(path, "same-hash")

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)
    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    fake_match_result = MatchScore(
        score=91.0, score_semantic=0.9, score_skills=0.9, score_experience=0.9,
        score_education=0.9, score_languages=0.9, score_contract=0.9,
        domain="tech", common_skills=["Python"], missing_skills=[], weights={},
    )
    monkeypatch.setattr(
        app_main, "match_cv_to_job",
        lambda cv_text, job_text, priority_keywords=None: fake_match_result,
    )

    return cv_path, job_path, extract_calls


def test_unchanged_fully_matched_document_is_skipped_without_force(session_factory, tmp_path, monkeypatch):
    cv_path, job_path, extract_calls = _setup(session_factory, tmp_path, monkeypatch)

    app_main._score_against_counterparts(cv_path, "cv")

    with session_factory() as session:
        match = session.scalar(select(MatchResult))
    assert match.score == 55.0, "sans force, le score inchange ne doit pas etre recalcule"


def test_force_recomputes_even_when_unchanged_and_fully_matched(session_factory, tmp_path, monkeypatch):
    cv_path, job_path, extract_calls = _setup(session_factory, tmp_path, monkeypatch)

    app_main._score_against_counterparts(cv_path, "cv", force=True)

    with session_factory() as session:
        match = session.scalar(select(MatchResult))
    assert match.score == 91.0, (
        "force=True doit ignorer le raccourci 'rien n'a change' et recalculer "
        "le score avec le code de matching actuel"
    )


def test_force_reextracts_every_document_instead_of_using_the_cache(session_factory, tmp_path, monkeypatch):
    """Une amelioration du modele d'extraction (ex: l'ordonnancement des
    colonnes PDF) ne change pas les octets du fichier sur disque -- sans
    force=True propage jusqu'a _extract_and_persist, le cache par hash de
    contenu continuerait a servir l'ancien texte extrait indefiniment."""
    cv_path, job_path, extract_calls = _setup(session_factory, tmp_path, monkeypatch)

    app_main._score_against_counterparts(cv_path, "cv", force=True)

    assert extract_calls, "_extract_and_persist doit avoir ete appele"
    assert all(extract_calls), (
        "force=True doit se propager a CHAQUE appel a _extract_and_persist "
        f"(le CV change et chaque offre active parcourue), obtenu {extract_calls}"
    )


def test_force_preserves_the_match_row_id(session_factory, tmp_path, monkeypatch):
    """Le rescoring force met a jour la ligne MatchResult existante (upsert
    sur cv_id/job_id) plutot que de la supprimer et la recreer -- un
    feedback deja laisse sur ce match doit rester rattache."""
    cv_path, job_path, extract_calls = _setup(session_factory, tmp_path, monkeypatch)

    with session_factory() as session:
        original_id = session.scalar(select(MatchResult.id))

    app_main._score_against_counterparts(cv_path, "cv", force=True)

    with session_factory() as session:
        rows = session.scalars(select(MatchResult)).all()

    assert len(rows) == 1, "aucune ligne dupliquee"
    assert rows[0].id == original_id, "l'id de la ligne doit rester stable pour ne pas casser un feedback existant"
