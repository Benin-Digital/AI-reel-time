"""Tests : mots-cles prioritaires renseignes AVANT l'import d'une offre.

Avant cette fonctionnalite, le panneau "Mots-cles prioritaires" n'existait
que sur la fiche d'une offre deja importee (JobDocument.priority_keywords).
Le recruteur qui les connaissait a l'avance devait donc importer l'offre,
attendre le premier calcul de scores (sans les mots-cles), puis les
renseigner -- ce qui declenchait un second recalcul complet (PATCH
/job-documents/{id}/priority-keywords).

POST /ingest accepte desormais un champ priority_keywords optionnel (offres
uniquement) : applique sur la ligne JobDocument des sa creation, avant que
l'evenement "ingest" ne mette en file l'extraction + le tout premier calcul
de scores -- qui les prend donc deja en compte, sans second recalcul.
"""
from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, JobDocument, MatchResult, ExtractedText
import app.main as app_main


@pytest.fixture
def session_factory(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CvDocument.__table__,
            JobDocument.__table__,
            MatchResult.__table__,
            ExtractedText.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(tmp_path / "jobs"))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(tmp_path / "cvs"))
    # Isolate from the real extraction/scoring pipeline -- covered
    # separately in test_priority_keywords_persistence.py.
    monkeypatch.setattr(app_main, "_on_watch_event", lambda event: None)
    return factory


def _make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


def test_ingest_job_with_priority_keywords_sets_them_on_creation(session_factory):
    upload = _make_upload("offre.txt", b"Poste: Analyste risque.")
    app_main.ingest_file(
        folder="job", upload=upload, filename=None,
        priority_keywords="gouvernance\nLOD2\nISO 27001",
    )

    with session_factory() as session:
        job = session.scalar(select(JobDocument))
        assert job.priority_keywords == "gouvernance\nLOD2\nISO 27001"


def test_ingest_job_without_priority_keywords_is_unchanged(session_factory):
    upload = _make_upload("offre.txt", b"Poste: Analyste risque.")
    app_main.ingest_file(folder="job", upload=upload, filename=None, priority_keywords=None)

    with session_factory() as session:
        job = session.scalar(select(JobDocument))
        assert job.priority_keywords is None


def test_ingest_job_with_blank_priority_keywords_stores_none(session_factory):
    upload = _make_upload("offre.txt", b"Poste: Analyste risque.")
    app_main.ingest_file(folder="job", upload=upload, filename=None, priority_keywords="   \n  ")

    with session_factory() as session:
        job = session.scalar(select(JobDocument))
        assert job.priority_keywords is None


def test_ingest_cv_with_priority_keywords_is_rejected(session_factory):
    upload = _make_upload("cv.txt", b"Consultant.")
    with pytest.raises(Exception) as exc_info:
        app_main.ingest_file(folder="cv", upload=upload, filename=None, priority_keywords="gouvernance")
    assert getattr(exc_info.value, "status_code", None) == 400


def test_reupload_updates_priority_keywords_on_existing_document(session_factory, tmp_path):
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    job_path = job_dir / "offre.txt"
    job_path.write_text("Poste: Analyste risque.")
    with session_factory() as session:
        session.add(JobDocument(
            path=str(job_path), status="ready", session_id="archived-session",
            priority_keywords="gouvernance",
        ))
        session.commit()

    upload = _make_upload("offre.txt", b"Poste: Analyste risque, mis a jour.")
    app_main.ingest_file(
        folder="job", upload=upload, filename="offre.txt", priority_keywords="DORA\nTRM",
    )

    with session_factory() as session:
        job = session.scalar(select(JobDocument))
        assert job.priority_keywords == "DORA\nTRM"
        assert job.session_id is None, "re-upload doit aussi desarchiver le document"


def test_extract_preview_reads_upload_without_requiring_a_job_document(session_factory):
    """La modale de pre-import extrait le texte d'un fichier Mots Cles.docx
    sans qu'aucune offre n'existe encore en base -- contrairement a
    /job-documents/{id}/priority-keywords/extract qui exige un doc_id."""
    upload = _make_upload("Mots Clés.txt", "Chef de projet\nLOD2\n".encode("utf-8"))
    result = app_main.extract_priority_keywords_preview(upload)
    assert "Chef de projet" in result.keywords
    assert "LOD2" in result.keywords

    with session_factory() as session:
        assert session.scalar(select(JobDocument)) is None, "aucune offre ne doit avoir ete creee"
