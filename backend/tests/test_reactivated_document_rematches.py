"""Test de non-regression : un CV/offre reactive depuis une archive (meme
contenu, meme statut "ready") sautait la boucle de matching entiere des
qu'une NOUVELLE offre/CV apparaissait, a cause du raccourci "rien n'a
change, ne refais pas le travail" de _score_against_counterparts().

Root cause : ce raccourci se declenchait sur
`_match_count_for_document(doc_id, role) > 0` -- qui compte N'IMPORTE QUEL
match existant, y compris ceux obtenus AVANT l'archivage, contre un
contrepartie qui est peut-etre elle-meme desormais archivee. Un document
reimporte depuis une archive garde le meme hash de contenu et le meme
statut "ready", et a presque toujours deja au moins un match historique
-- donc la condition de saut se declenchait a tort, meme quand une
toute nouvelle offre/CV, jamais matchee, venait d'etre ajoutee a l'espace
actif.

Repro reelle en production : un CV reimporte depuis l'archive passait
"Pret" tres rapidement (cache d'extraction), mais n'apparaissait jamais
dans Correspondances face a une offre fraichement ajoutee, alors que des
CV jamais archives matchaient normalement.

Fix : _matched_all_active_counterparts() ne compte que les matches contre
des contreparties actuellement actives (session_id IS NULL) et compare ce
compte au nombre total de contreparties actives -- le saut ne se
declenche desormais que si le document a deja ete matche contre TOUTES
les contreparties actives, pas juste "au moins une, un jour".
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


def test_reactivated_cv_still_matches_a_brand_new_job(session_factory, tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    reactivated_cv_path = cv_dir / "reactivated.txt"
    reactivated_cv_path.write_text("CV reimporte")
    new_job_path = job_dir / "new_job.txt"
    new_job_path.write_text("Offre toute nouvelle")

    with session_factory() as session:
        # Simule un CV reimporte depuis une archive : deja "ready", meme
        # hash qu'avant, session_id deja remis a None (fait par /ingest),
        # et un match HISTORIQUE contre une offre qui n'existe plus dans
        # le dossier surveille (deja supprimee/archivee).
        cv = CvDocument(
            path=str(reactivated_cv_path), content_hash="same-hash",
            status="ready", session_id=None,
        )
        old_job = JobDocument(
            path=str(job_dir / "old_job_now_gone.txt"), content_hash="old-hash",
            status="ready", session_id=99,  # archivee
        )
        # POST /ingest cree toujours une ligne "pending" des la reception du
        # fichier, avant meme que le worker ne le traite -- reproduit ici
        # pour que le compte de contreparties actives voie bien cette
        # nouvelle offre.
        new_job = JobDocument(path=str(new_job_path), status="pending", session_id=None)
        session.add_all([cv, old_job, new_job])
        session.commit()
        session.add(MatchResult(cv_id=cv.id, job_id=old_job.id, score=50.0))
        session.commit()

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)

    def fake_extract_and_persist(path, force_docling=False, force=False):
        content_hash = "same-hash" if path == reactivated_cv_path else "hash-new"
        return _fake_extraction(path, content_hash)

    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    monkeypatch.setattr(app_main, "score_texts", lambda cv_text, job_text, priority_keywords=None: (77.0, ["Python"]))

    app_main._score_against_counterparts(reactivated_cv_path, "cv")

    with session_factory() as session:
        matches = session.scalars(
            select(MatchResult).where(MatchResult.job_id == session.scalar(
                select(JobDocument.id).where(JobDocument.path == str(new_job_path))
            ))
        ).all()

    assert len(matches) == 1, (
        "le CV reactive doit etre matche contre la nouvelle offre active, "
        "pas saute a cause d'un ancien match contre une offre desormais archivee"
    )


def test_reactivated_job_still_matches_a_brand_new_cv(session_factory, tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    reactivated_job_path = job_dir / "reactivated.txt"
    reactivated_job_path.write_text("Offre reimportee")
    new_cv_path = cv_dir / "new_cv.txt"
    new_cv_path.write_text("CV tout nouveau")

    with session_factory() as session:
        job = JobDocument(
            path=str(reactivated_job_path), content_hash="same-hash",
            status="ready", session_id=None,
        )
        old_cv = CvDocument(
            path=str(cv_dir / "old_cv_now_gone.txt"), content_hash="old-hash",
            status="ready", session_id=99,
        )
        new_cv = CvDocument(path=str(new_cv_path), status="pending", session_id=None)
        session.add_all([job, old_cv, new_cv])
        session.commit()
        session.add(MatchResult(cv_id=old_cv.id, job_id=job.id, score=50.0))
        session.commit()

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)
    monkeypatch.setattr(app_main.settings, "auto_create_job_offer", False)

    def fake_extract_and_persist(path, force_docling=False, force=False):
        content_hash = "same-hash" if path == reactivated_job_path else "hash-new"
        return _fake_extraction(path, content_hash)

    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    monkeypatch.setattr(app_main, "score_texts", lambda cv_text, job_text, priority_keywords=None: (77.0, ["Python"]))

    app_main._score_against_counterparts(reactivated_job_path, "job")

    with session_factory() as session:
        matches = session.scalars(
            select(MatchResult).where(MatchResult.cv_id == session.scalar(
                select(CvDocument.id).where(CvDocument.path == str(new_cv_path))
            ))
        ).all()

    assert len(matches) == 1, (
        "l'offre reactivee doit etre matchee contre le nouveau CV actif, "
        "pas sautee a cause d'un ancien match contre un CV desormais archive"
    )
