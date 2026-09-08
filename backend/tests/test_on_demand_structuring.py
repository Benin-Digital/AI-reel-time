"""Tests de non-regression pour la structuration Docling a la demande.

Contexte : Docling (analyse de mise en page + tableaux, modeles de vision
tournant sur CPU) rendait le traitement de documents un peu longs (ex: un
CV de 11 pages) trop lent pour de l'ingestion automatique, causant des 502
nginx. L'extraction automatique est desormais TOUJOURS rapide (PyMuPDF +
OCR plafonne) ; Docling ne tourne plus que sur demande explicite via
POST /{cv,job}-documents/{id}/structure.

Ces tests verifient :
- l'extraction automatique (force_docling=False, valeur par defaut) n'appelle
  jamais Docling, meme si un cache Docling existe deja pour ce fichier ;
- force_docling=True declenche bien Docling, sauf si le cache est deja une
  extraction Docling du meme contenu (pas de re-travail inutile) ;
- le changement de methode d'extraction invalide le profil structure mis en
  cache, meme si le hash de contenu (le fichier) n'a pas change ;
- _structure_document met a jour structuring_status et relance le scoring
  seulement en cas de succes.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, ExtractedText, JobDocument, MatchResult
import app.main as app_main
import app.services.conversion as conversion


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CvDocument.__table__,
            JobDocument.__table__,
            ExtractedText.__table__,
            MatchResult.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    return factory


@pytest.fixture
def cv_file(tmp_path):
    path = tmp_path / "cv.txt"
    path.write_text("Développeur Python, 5 ans d'expérience. Compétences : Python, Django.")
    return path


def test_default_extraction_never_calls_docling(cv_file, monkeypatch, session_factory):
    def _boom(path):
        raise AssertionError("Docling must not run for the default (auto-ingest) extraction path")

    monkeypatch.setattr(conversion, "convert_document", _boom)

    result = app_main._extract_and_persist(cv_file)

    assert result.extraction_success
    assert result.extraction_method != "docling"


def test_cached_docling_result_is_reused_without_setting(cv_file, monkeypatch, session_factory):
    calls = {"n": 0}

    def _fake_convert(path):
        calls["n"] += 1
        from app.services.conversion import ConvertedDocument
        return ConvertedDocument(full_text="structured text", sections={"skills": "Python"})

    monkeypatch.setattr(conversion, "convert_document", _fake_convert)

    first = app_main._extract_and_persist(cv_file, force_docling=True)
    assert first.extraction_method == "docling"
    assert calls["n"] == 1

    # Auto-ingest call (force_docling=False) on the same unchanged file must
    # reuse the cached Docling extraction, not silently downgrade it.
    second = app_main._extract_and_persist(cv_file)
    assert second.extraction_method == "docling"
    assert second.extracted_text == "structured text"
    assert calls["n"] == 1, "no re-extraction should happen on an unchanged, already-cached file"

    # A second forced structuring request on unchanged content must not
    # re-run Docling either.
    third = app_main._extract_and_persist(cv_file, force_docling=True)
    assert calls["n"] == 1


def test_forcing_docling_over_a_plain_text_cache_invalidates_parsed_profile(cv_file, monkeypatch, session_factory):
    # First, a normal fast extraction (simulates automatic ingestion).
    plain = app_main._extract_and_persist(cv_file)
    assert plain.extraction_method != "docling"

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_file)).one()
        row.parsed_profile = {"full_name": "stale"}
        row.parsed_profile_hash = row.content_hash
        session.commit()

    def _fake_convert(path):
        from app.services.conversion import ConvertedDocument
        return ConvertedDocument(full_text="richer structured text", sections={})

    monkeypatch.setattr(conversion, "convert_document", _fake_convert)

    app_main._extract_and_persist(cv_file, force_docling=True)

    with session_factory() as session:
        row = session.query(ExtractedText).filter_by(file_path=str(cv_file)).one()
        assert row.extraction_method == "docling"
        assert row.extracted_text == "richer structured text"
        assert row.parsed_profile is None, "changing extraction method must invalidate the stale cached profile"
        assert row.parsed_profile_hash is None


def test_structure_document_marks_ready_and_rescopes_on_success(cv_file, monkeypatch, session_factory):
    with session_factory() as session:
        doc = CvDocument(path=str(cv_file), status="ready")
        session.add(doc)
        session.commit()

    def _fake_convert(path):
        from app.services.conversion import ConvertedDocument
        return ConvertedDocument(full_text="structured text", sections={})

    monkeypatch.setattr(conversion, "convert_document", _fake_convert)

    rescored = {"called": False}
    monkeypatch.setattr(app_main, "_score_against_counterparts", lambda path, role: rescored.__setitem__("called", True))

    app_main._structure_document(cv_file, "cv")

    with session_factory() as session:
        doc = session.query(CvDocument).filter_by(path=str(cv_file)).one()
        assert doc.structuring_status == "ready"
        assert doc.structuring_error is None
    assert rescored["called"] is True


def test_structure_document_marks_failed_without_rescoring(tmp_path, monkeypatch, session_factory):
    missing_path = tmp_path / "missing.txt"  # file does not exist -> extraction fails

    with session_factory() as session:
        doc = CvDocument(path=str(missing_path), status="ready")
        session.add(doc)
        session.commit()

    rescored = {"called": False}
    monkeypatch.setattr(app_main, "_score_against_counterparts", lambda path, role: rescored.__setitem__("called", True))

    app_main._structure_document(missing_path, "cv")

    with session_factory() as session:
        doc = session.query(CvDocument).filter_by(path=str(missing_path)).one()
        assert doc.structuring_status == "failed"
        assert doc.structuring_error
    assert rescored["called"] is False
