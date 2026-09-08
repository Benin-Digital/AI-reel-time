"""Test de non-regression : re-ingerer un fichier dont le chemin appartenait
a un document archive (session_id defini) le laissait silencieusement
rattache a cette ancienne archive. Un nouveau CV/Job uploade sous un nom de
fichier deja utilise disparaissait donc de l'onglet "Actifs" sans que rien
ne l'indique, et n'apparaissait que dans l'archive.

Le fix remet session_id a None quand le contenu du fichier a reellement
change (nouveau hash) pour un document jusque-la archive. Si le contenu
est identique (meme hash), le document doit rester archive.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CvDocument, JobDocument
from app.schemas import ExtractedTextRead
import app.main as app_main


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[CvDocument.__table__, JobDocument.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    return factory


def _extraction(path: str, content_hash: str) -> ExtractedTextRead:
    now = datetime.utcnow()
    return ExtractedTextRead(
        id=1,
        file_path=path,
        content_hash=content_hash,
        extracted_text="some text",
        extraction_method="pdf",
        extraction_success=True,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def test_reingest_with_new_content_clears_archived_session(session_factory):
    with session_factory() as session:
        cv = CvDocument(path="/cv/reused.pdf", content_hash="old-hash", status="ready", session_id=42)
        session.add(cv)
        session.commit()

    result = app_main._upsert_cv_document(app_main.Path("/cv/reused.pdf"), _extraction("/cv/reused.pdf", "new-hash"))

    assert result.session_id is None, "un nouveau contenu doit sortir le document de l'archive"


def test_reingest_with_unchanged_content_stays_archived(session_factory):
    with session_factory() as session:
        cv = CvDocument(path="/cv/reused.pdf", content_hash="same-hash", status="ready", session_id=42)
        session.add(cv)
        session.commit()

    result = app_main._upsert_cv_document(app_main.Path("/cv/reused.pdf"), _extraction("/cv/reused.pdf", "same-hash"))

    assert result.session_id == 42, "un simple re-traitement sans changement ne doit pas desarchiver"


def test_job_document_same_behavior(session_factory):
    with session_factory() as session:
        job = JobDocument(path="/job/reused.pdf", content_hash="old-hash", status="ready", session_id=7)
        session.add(job)
        session.commit()

    result = app_main._upsert_job_document(app_main.Path("/job/reused.pdf"), _extraction("/job/reused.pdf", "new-hash"))

    assert result.session_id is None
