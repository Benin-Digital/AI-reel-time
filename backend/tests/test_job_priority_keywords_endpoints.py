"""Tests : endpoints de sauvegarde/extraction des mots-cles prioritaires.

PATCH /job-documents/{id}/priority-keywords sauvegarde le texte edite par le
recruteur (tape directement, ou pre-rempli depuis un fichier importe) et
declenche un rescoring de cette offre. POST .../extract lit un fichier
uploade (memes formats que CV/offres : pdf/docx/txt) et renvoie son texte
sans rien sauvegarder -- seul PATCH persiste.
"""
from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, JobDocument, MatchResult, ExtractedText
from app.schemas import JobPriorityKeywordsUpdate
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
            ExtractedText.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    # The endpoint queues a rescore after saving -- isolate this test from
    # the real watcher/queue pipeline (covered separately in
    # test_priority_keywords.py / test_recompute_matches.py).
    monkeypatch.setattr(app_main, "_on_watch_event", lambda event: None)
    return factory


def test_patch_saves_keywords_and_returns_updated_detail(session_factory, tmp_path):
    job_path = tmp_path / "offre.docx"
    job_path.write_text("Offre")
    with session_factory() as session:
        job = JobDocument(path=str(job_path), status="ready", session_id=None)
        session.add(job)
        session.commit()
        job_id = job.id

    result = app_main.update_job_priority_keywords(
        job_id, JobPriorityKeywordsUpdate(keywords="LOD2\nDORA\nTRM")
    )
    assert result.priority_keywords == "LOD2\nDORA\nTRM"

    with session_factory() as session:
        refreshed = session.get(JobDocument, job_id)
        assert refreshed.priority_keywords == "LOD2\nDORA\nTRM"


def test_patch_with_blank_text_clears_keywords(session_factory, tmp_path):
    job_path = tmp_path / "offre.docx"
    job_path.write_text("Offre")
    with session_factory() as session:
        job = JobDocument(path=str(job_path), status="ready", session_id=None, priority_keywords="LOD2")
        session.add(job)
        session.commit()
        job_id = job.id

    app_main.update_job_priority_keywords(job_id, JobPriorityKeywordsUpdate(keywords="   "))

    with session_factory() as session:
        assert session.get(JobDocument, job_id).priority_keywords is None


def test_patch_unknown_job_raises_404(session_factory):
    with pytest.raises(Exception) as exc_info:
        app_main.update_job_priority_keywords(9999, JobPriorityKeywordsUpdate(keywords="LOD2"))
    assert getattr(exc_info.value, "status_code", None) == 404


def _make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


def test_extract_reads_txt_upload_without_saving(session_factory, tmp_path):
    job_path = tmp_path / "offre.docx"
    job_path.write_text("Offre")
    with session_factory() as session:
        job = JobDocument(path=str(job_path), status="ready", session_id=None)
        session.add(job)
        session.commit()
        job_id = job.id

    upload = _make_upload("Mots Clés.txt", "Chef de projet\nLOD2\n".encode("utf-8"))
    result = app_main.extract_job_priority_keywords(job_id, upload)
    assert "Chef de projet" in result.keywords
    assert "LOD2" in result.keywords

    # Nothing persisted -- extraction is a preview, not a save.
    with session_factory() as session:
        assert session.get(JobDocument, job_id).priority_keywords is None


def test_extract_rejects_unsupported_file_type(session_factory, tmp_path):
    job_path = tmp_path / "offre.docx"
    job_path.write_text("Offre")
    with session_factory() as session:
        job = JobDocument(path=str(job_path), status="ready", session_id=None)
        session.add(job)
        session.commit()
        job_id = job.id

    upload = _make_upload("mots-cles.xlsx", b"not a supported format")
    with pytest.raises(Exception) as exc_info:
        app_main.extract_job_priority_keywords(job_id, upload)
    assert getattr(exc_info.value, "status_code", None) == 400
