"""Test de non-regression pour un bug rapporte en direct (2026-10-05) :
un admin desarchivait l'archive d'un autre admin (ou d'un utilisateur),
visible via la hierarchie de roles (deps.visible_owner_ids) -- mais
l'ancien comportement mutait CvDocument/JobDocument.session_id en place,
ce qui retirait les documents de l'archive de son VRAI proprietaire au
lieu de les faire apparaitre uniquement dans l'espace de travail de
l'admin. L'archive d'origine se retrouvait vide ("0 CV, 0 offres") pour
son proprietaire, exactement le meme symptome que le bug de collision de
noms de fichiers corrige plus tot dans la session.

Fix retenu (confirme avec l'utilisateur) : copie independante. Quand le
demandeur n'est PAS proprietaire de l'archive (deps.is_archive_owner),
POST /sessions/{id}/unassign clone chaque document (deps.
clone_document_for_new_owner) dans son propre espace actif -- fichier
copie sur disque sous un nom desambiguise, nouvelle ligne CvDocument/
JobDocument avec created_by_user_id = demandeur, session_id = NULL.
L'archive d'origine et ses documents ne sont jamais touches.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import AnalysisSession, Base, CvDocument, ExtractedText, JobDocument, MatchResult, User
import app.main as app_main
import app.routers.sessions as sessions_router


def _fake_request(user: User) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=user))


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            AnalysisSession.__table__,
            CvDocument.__table__,
            JobDocument.__table__,
            ExtractedText.__table__,
            MatchResult.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(sessions_router, "SessionLocal", factory)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    monkeypatch.setattr(app_main, "_on_watch_event", lambda event: None)
    return factory


def _make_user(factory: sessionmaker, email: str, role: str) -> User:
    with factory() as session:
        user = User(email=email, password_hash="x", role=role)
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def test_non_owner_unarchive_clones_instead_of_mutating_the_original(session_factory, tmp_path):
    member = _make_user(session_factory, "member@test.local", "member")
    admin = _make_user(session_factory, "admin@test.local", "admin")

    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("CV du membre")
    job_path = tmp_path / "job.txt"
    job_path.write_text("Offre du membre")

    with session_factory() as session:
        archive = AnalysisSession(name="Lot du membre", status="closed", created_by_user_id=member.id)
        session.add(archive)
        session.commit()
        session.refresh(archive)
        archive_id = archive.id

        cv = CvDocument(path=str(cv_path), status="ready", session_id=archive_id, created_by_user_id=member.id)
        job = JobDocument(
            path=str(job_path), status="ready", session_id=archive_id, created_by_user_id=member.id,
            priority_keywords="gouvernance",
        )
        session.add_all([cv, job])
        session.commit()
        session.add(ExtractedText(
            file_path=str(cv_path), content_hash="hash-cv", extracted_text="CV du membre",
            extraction_method="txt", extraction_success=True,
        ))
        session.commit()

    result = sessions_router.unassign_session_documents(archive_id, _fake_request(admin))

    assert result.mode == "copied"
    assert result.cv_count == 1
    assert result.job_count == 1

    with session_factory() as session:
        # L'archive et ses documents d'origine : totalement intacts.
        original_archive = session.get(AnalysisSession, archive_id)
        assert original_archive is not None, "l'archive d'origine ne doit jamais etre supprimee"
        original_cv = session.scalar(select(CvDocument).where(CvDocument.path == str(cv_path)))
        original_job = session.scalar(select(JobDocument).where(JobDocument.path == str(job_path)))
        assert original_cv.session_id == archive_id, "le CV d'origine doit rester dans l'archive du membre"
        assert original_job.session_id == archive_id, "l'offre d'origine doit rester dans l'archive du membre"
        assert original_cv.created_by_user_id == member.id
        assert original_job.created_by_user_id == member.id

        # Les clones : actifs, appartenant a l'admin, fichiers separes.
        cloned_cv = session.scalar(select(CvDocument).where(CvDocument.created_by_user_id == admin.id))
        cloned_job = session.scalar(select(JobDocument).where(JobDocument.created_by_user_id == admin.id))
        assert cloned_cv is not None and cloned_job is not None
        assert cloned_cv.session_id is None, "le clone doit etre actif, pas archive"
        assert cloned_job.session_id is None
        assert cloned_cv.path != str(cv_path), "le clone doit avoir son propre fichier, pas partager celui du membre"
        assert cloned_job.priority_keywords == "gouvernance", "les mots-cles prioritaires doivent etre copies"

        # Le fichier clone existe reellement sur disque avec le meme contenu.
        from pathlib import Path
        assert Path(cloned_cv.path).read_text() == "CV du membre"

        # L'extraction en cache a ete clonee aussi (pas de re-extraction a refaire).
        cloned_extract = session.scalar(select(ExtractedText).where(ExtractedText.file_path == cloned_cv.path))
        assert cloned_extract is not None
        assert cloned_extract.extracted_text == "CV du membre"


def test_owner_unarchive_still_mutates_in_place_not_clones(session_factory, tmp_path):
    """Non-regression du comportement existant : le PROPRIETAIRE de
    l'archive continue de la desarchiver normalement (mutation en place),
    pas de clonage inutile."""
    member = _make_user(session_factory, "member2@test.local", "member")

    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("Mon CV")

    with session_factory() as session:
        archive = AnalysisSession(name="Mon lot", status="closed", created_by_user_id=member.id)
        session.add(archive)
        session.commit()
        session.refresh(archive)
        archive_id = archive.id
        session.add(CvDocument(path=str(cv_path), status="ready", session_id=archive_id, created_by_user_id=member.id))
        session.commit()

    result = sessions_router.unassign_session_documents(archive_id, _fake_request(member))

    assert result.mode == "unarchived"
    with session_factory() as session:
        assert session.get(AnalysisSession, archive_id) is None, "l'archive du proprietaire doit etre dissoute"
        all_cvs = session.scalars(select(CvDocument)).all()
        assert len(all_cvs) == 1, "aucun clone ne doit etre cree quand c'est le proprietaire qui desarchive"
        assert all_cvs[0].session_id is None
