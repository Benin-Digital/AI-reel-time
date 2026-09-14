"""Test de non-regression : un CV/offre archive(e) (assigne a une session
fermee) ne doit plus jamais etre passe a _extract_and_persist() du tout.

Contexte reel (production, 2026-09-14) : le recruteur signale qu'une
offre avec seulement 2 CV actifs reste "en cours de recalcul" bien plus
longtemps que ce que 2 CV justifieraient. Cause : la boucle de matching
parcourt TOUS les fichiers presents sur le disque de la CV/offre
concernee, et n'excluait les documents archives qu'APRES les avoir
extraits -- avec force=True (tout evenement de "rescore" : sauvegarde
des mots-cles prioritaires, changement de profil de ponderation,
/matches/recompute), _extract_and_persist ignore completement son cache
par hash de contenu, donc CHAQUE document archive accumule au fil de la
session etait entierement ré-extrait a chaque rescore, pour un travail
toujours jete a la poubelle juste apres (le "continue" sur session_id
n'intervenait qu'apres coup).

Fix : une verification legere (une seule colonne, pas d'extraction) du
session_id existant AVANT tout appel a _extract_and_persist -- un
document deja connu comme archive ne declenche plus aucune extraction.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
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


def _fake_extraction(path, content_hash: str = "hash") -> ExtractedTextRead:
    now = datetime.utcnow()
    return ExtractedTextRead(
        id=1, file_path=str(path), content_hash=content_hash,
        extracted_text="Développeur Python, compétences : Python, Django.",
        extraction_method="txt", extraction_success=True, error_message=None,
        created_at=now, updated_at=now,
    )


def test_archived_cv_is_never_passed_to_extract_and_persist_from_a_job_upload(
    session_factory, tmp_path, monkeypatch
):
    """Un evenement cote OFFRE (upload/rescore) parcourt le dossier CV --
    un CV archive present sur le disque ne doit jamais etre extrait."""
    job_dir, cv_dir = tmp_path / "jobs", tmp_path / "cvs"
    job_dir.mkdir(); cv_dir.mkdir()

    active_cv_path = cv_dir / "active.txt"
    active_cv_path.write_text("CV actif")
    archived_cv_path = cv_dir / "archived.txt"
    archived_cv_path.write_text("CV archive")
    job_path = job_dir / "job.txt"
    job_path.write_text("Offre")

    with session_factory() as session:
        session.add(CvDocument(path=str(active_cv_path), status="ready", session_id=None))
        session.add(CvDocument(path=str(archived_cv_path), status="ready", session_id=42))
        session.add(JobDocument(path=str(job_path), status="ready", session_id=None))
        session.commit()

    extracted_paths: list[str] = []

    def fake_extract_and_persist(path, force_docling=False, force=False):
        extracted_paths.append(str(path))
        return _fake_extraction(path)

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)
    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    fake_match_result = MatchScore(
        score=80.0, score_semantic=0.8, score_skills=0.8, score_experience=0.8,
        score_education=0.8, score_languages=0.8, score_contract=0.8,
        domain="tech", common_skills=[], missing_skills=[], weights={},
    )
    monkeypatch.setattr(
        app_main, "match_cv_to_job",
        lambda cv_text, job_text, priority_keywords=None, scoring_profile=None: fake_match_result,
    )

    app_main._score_against_counterparts(job_path, "job", force=True)

    assert str(job_path) in extracted_paths, "l'offre elle-meme (declencheur) doit toujours etre extraite"
    assert str(active_cv_path) in extracted_paths, "le CV actif doit etre extrait et matche"
    assert str(archived_cv_path) not in extracted_paths, (
        "un CV archive ne doit JAMAIS etre passe a _extract_and_persist, "
        f"obtenu extracted_paths={extracted_paths}"
    )


def test_archived_job_is_never_passed_to_extract_and_persist_from_a_cv_upload(
    session_factory, tmp_path, monkeypatch
):
    """Symetrique : un evenement cote CV ne doit pas extraire une offre archivee."""
    job_dir, cv_dir = tmp_path / "jobs", tmp_path / "cvs"
    job_dir.mkdir(); cv_dir.mkdir()

    cv_path = cv_dir / "cv.txt"
    cv_path.write_text("CV")
    active_job_path = job_dir / "active.txt"
    active_job_path.write_text("Offre active")
    archived_job_path = job_dir / "archived.txt"
    archived_job_path.write_text("Offre archivee")

    with session_factory() as session:
        session.add(CvDocument(path=str(cv_path), status="ready", session_id=None))
        session.add(JobDocument(path=str(active_job_path), status="ready", session_id=None))
        session.add(JobDocument(path=str(archived_job_path), status="ready", session_id=7))
        session.commit()

    extracted_paths: list[str] = []

    def fake_extract_and_persist(path, force_docling=False, force=False):
        extracted_paths.append(str(path))
        return _fake_extraction(path)

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)
    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    fake_match_result = MatchScore(
        score=80.0, score_semantic=0.8, score_skills=0.8, score_experience=0.8,
        score_education=0.8, score_languages=0.8, score_contract=0.8,
        domain="tech", common_skills=[], missing_skills=[], weights={},
    )
    monkeypatch.setattr(
        app_main, "match_cv_to_job",
        lambda cv_text, job_text, priority_keywords=None, scoring_profile=None: fake_match_result,
    )

    app_main._score_against_counterparts(cv_path, "cv", force=True)

    assert str(cv_path) in extracted_paths
    assert str(active_job_path) in extracted_paths
    assert str(archived_job_path) not in extracted_paths, (
        "une offre archivee ne doit JAMAIS etre passee a _extract_and_persist, "
        f"obtenu extracted_paths={extracted_paths}"
    )
