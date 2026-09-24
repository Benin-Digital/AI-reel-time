"""Test de non-regression pour le suivi du bug d'isolation des archives
(2026-09-24) : une fois les archives correctement isolees par role, le
signalement suivant a ete "les correspondances ACTIVES restent visibles
sur tous les profils -- l'analyse en cours d'un profil ne doit etre vue
par personne d'autre, meme le superadmin ; seules les archives suivent la
hierarchie de roles. Chaque profil doit pouvoir mener sa propre analyse en
parallele sur la plateforme."

Regle retenue (voir deps.owner_visible_to / owner_eligibility_clause /
owners_eligible) : un CV/une offre/un match actif (non archive) est visible
uniquement par son createur, ou par tout le monde s'il est "legacy/partage"
(created_by_user_id NULL -- decision explicite : les ~13 715 CV deja
importes avant cette fonctionnalite restent un fonds commun). Aucune
exception de hierarchie ici, contrairement aux archives.

Le moteur de matching (_score_against_counterparts, _vector_match_cv/_job)
est lui-meme scope : un CV prive et une offre privee appartenant a deux
profils differents ne sont jamais matches entre eux.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from fastapi import UploadFile

from app.deps import owners_eligible, owner_visible_to
from app.models import AnalysisSession, Base, CvDocument, ExtractedText, JobDocument, MatchResult, ScoreResult, User
from app.schemas import ExtractedTextRead
import app.main as app_main


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
            MatchResult.__table__,
            ScoreResult.__table__,
            ExtractedText.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    return factory


def _make_user(factory: sessionmaker, email: str, role: str = "member") -> User:
    with factory() as session:
        user = User(email=email, password_hash="x", role=role)
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


# ---------------------------------------------------------------------------
# owner_visible_to / owners_eligible -- pure-function unit tests
# ---------------------------------------------------------------------------

def test_owner_visible_to_own_document():
    me = SimpleNamespace(id=1, role="member")
    assert owner_visible_to(1, me) is True


def test_owner_visible_to_legacy_shared_document():
    me = SimpleNamespace(id=1, role="member")
    assert owner_visible_to(None, me) is True


def test_owner_visible_to_someone_elses_document_even_for_superadmin():
    superadmin = SimpleNamespace(id=1, role="superadmin")
    assert owner_visible_to(2, superadmin) is False, (
        "contrairement aux archives, aucune exception de hierarchie pour "
        "les documents actifs"
    )


def test_owners_eligible_shared_and_private_combinations():
    assert owners_eligible(None, None) is True
    assert owners_eligible(None, 5) is True
    assert owners_eligible(5, None) is True
    assert owners_eligible(5, 5) is True
    assert owners_eligible(5, 6) is False


# ---------------------------------------------------------------------------
# GET /cv-documents, /job-documents visibility
# ---------------------------------------------------------------------------

def test_list_cv_documents_excludes_another_profiles_private_cv(session_factory):
    alice = _make_user(session_factory, "alice@test.local")
    bob = _make_user(session_factory, "bob@test.local", role="superadmin")
    with session_factory() as session:
        session.add(CvDocument(path="/cv/alice.pdf", status="ready", created_by_user_id=alice.id))
        session.add(CvDocument(path="/cv/legacy.pdf", status="ready", created_by_user_id=None))
        session.commit()

    result = app_main.list_cv_documents(_fake_request(bob))
    paths = {r.path for r in result}

    assert paths == {"/cv/legacy.pdf"}, (
        "bob (superadmin) ne doit voir ni le CV prive d'alice, seulement le "
        "fonds legacy partage"
    )


def test_list_cv_documents_includes_own_private_cv(session_factory):
    alice = _make_user(session_factory, "alice2@test.local")
    with session_factory() as session:
        session.add(CvDocument(path="/cv/alice.pdf", status="ready", created_by_user_id=alice.id))
        session.commit()

    result = app_main.list_cv_documents(_fake_request(alice))

    assert {r.path for r in result} == {"/cv/alice.pdf"}


def test_get_cv_document_404s_for_another_profiles_private_cv(session_factory):
    from fastapi import HTTPException

    alice = _make_user(session_factory, "alice3@test.local")
    bob = _make_user(session_factory, "bob3@test.local", role="superadmin")
    with session_factory() as session:
        cv = CvDocument(path="/cv/alice.pdf", status="ready", created_by_user_id=alice.id)
        session.add(cv)
        session.commit()
        session.refresh(cv)
        cv_id = cv.id

    with pytest.raises(HTTPException) as exc_info:
        app_main.get_cv_document(cv_id, _fake_request(bob))
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Matching engine scoping (_score_against_counterparts)
# ---------------------------------------------------------------------------

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


def test_two_different_profiles_private_documents_never_match(session_factory, tmp_path, monkeypatch):
    alice = _make_user(session_factory, "alice4@test.local")
    bob = _make_user(session_factory, "bob4@test.local")

    job_dir = tmp_path / "jobs"
    cv_dir = tmp_path / "cvs"
    job_dir.mkdir()
    cv_dir.mkdir()

    bobs_job_path = job_dir / "bob_job.txt"
    bobs_job_path.write_text("Offre de Bob")
    shared_job_path = job_dir / "shared_job.txt"
    shared_job_path.write_text("Offre partagee")
    alices_cv_path = cv_dir / "alice_cv.txt"
    alices_cv_path.write_text("CV d'Alice")

    with session_factory() as session:
        session.add(JobDocument(path=str(bobs_job_path), status="ready", created_by_user_id=bob.id))
        session.add(JobDocument(path=str(shared_job_path), status="ready", created_by_user_id=None))
        session.commit()

    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(job_dir))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(cv_dir))
    monkeypatch.setattr(app_main.settings, "embedding_enabled", False)

    def fake_extract_and_persist(path, force_docling=False, force=False):
        return _fake_extraction(path, "hash-new")

    monkeypatch.setattr(app_main, "_extract_and_persist", fake_extract_and_persist)
    monkeypatch.setattr(app_main, "score_texts", lambda cv_text, job_text, priority_keywords=None: (77.0, ["Python"]))

    with session_factory() as session:
        session.add(CvDocument(path=str(alices_cv_path), status="ready", created_by_user_id=alice.id))
        session.commit()

    app_main._score_against_counterparts(alices_cv_path, "cv")

    with session_factory() as session:
        matches = session.scalars(select(MatchResult)).all()
        matched_job_paths = {session.get(JobDocument, m.job_id).path for m in matches}

    assert str(shared_job_path) in matched_job_paths, "une offre partagee (legacy) doit matcher avec un CV prive"
    assert str(bobs_job_path) not in matched_job_paths, (
        "l'offre privee de bob ne doit jamais matcher avec le CV prive d'alice"
    )


# ---------------------------------------------------------------------------
# Filename-collision bug reported live (2026-09-24): two profiles uploading
# a same-named file (a very plausible case -- an identical CV/job pair
# tested from two different profiles) shared ONE CvDocument/JobDocument row
# (path is UNIQUE), so the second profile's "new" upload silently inherited
# the first's match history and priority keywords, and the re-upload's
# unarchive-on-reupload behavior ripped the document out of the first
# profile's archive, turning it into "0 CV, 0 offres".
# ---------------------------------------------------------------------------

def _make_upload(filename: str, content: bytes) -> UploadFile:
    import io
    return UploadFile(filename=filename, file=io.BytesIO(content))


@pytest.fixture
def ingest_env(session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(app_main.settings, "watch_job_dir", str(tmp_path / "jobs"))
    monkeypatch.setattr(app_main.settings, "watch_cv_dir", str(tmp_path / "cvs"))
    monkeypatch.setattr(app_main, "_on_watch_event", lambda event: None)
    return session_factory


def test_two_profiles_uploading_the_same_filename_get_two_separate_documents(session_factory, ingest_env):
    alice = _make_user(session_factory, "alice5@test.local")
    bob = _make_user(session_factory, "bob5@test.local")

    app_main.ingest_file(
        _fake_request(alice), folder="job", upload=_make_upload("offre.txt", b"Offre d'Alice"), filename=None, priority_keywords=None,
    )
    app_main.ingest_file(
        _fake_request(bob), folder="job", upload=_make_upload("offre.txt", b"Offre de Bob"), filename=None, priority_keywords=None,
    )

    with session_factory() as session:
        jobs = session.scalars(select(JobDocument)).all()
        assert len(jobs) == 2, "deux profils uploadant 'offre.txt' doivent obtenir deux documents distincts"
        owners = {j.created_by_user_id for j in jobs}
        assert owners == {alice.id, bob.id}


def test_same_profile_reuploading_the_same_filename_updates_in_place(session_factory, ingest_env):
    alice = _make_user(session_factory, "alice6@test.local")

    app_main.ingest_file(
        _fake_request(alice), folder="job", upload=_make_upload("offre.txt", b"V1"),
        filename=None, priority_keywords="gouvernance",
    )
    app_main.ingest_file(
        _fake_request(alice), folder="job", upload=_make_upload("offre.txt", b"V2"),
        filename=None, priority_keywords=None,
    )

    with session_factory() as session:
        jobs = session.scalars(select(JobDocument)).all()
        assert len(jobs) == 1, "re-uploader son propre fichier ne doit jamais creer un doublon"
        assert jobs[0].priority_keywords == "gouvernance", (
            "priority_keywords non fourni au second upload -> ne doit pas etre efface "
            "(comportement volontaire, voir _ensure_pending_document_and_unarchive)"
        )


def test_uploading_a_name_that_collides_with_a_legacy_document_does_not_hijack_it(session_factory, ingest_env, tmp_path):
    job_dir = tmp_path / "jobs"
    job_dir.mkdir(parents=True)
    legacy_path = job_dir / "offre.txt"
    legacy_path.write_text("Offre historique partagee")
    with session_factory() as session:
        session.add(JobDocument(path=str(legacy_path), status="ready", created_by_user_id=None))
        session.commit()

    alice = _make_user(session_factory, "alice7@test.local")
    app_main.ingest_file(
        _fake_request(alice), folder="job", upload=_make_upload("offre.txt", b"Nouvelle offre d'Alice"), filename=None, priority_keywords=None,
    )

    with session_factory() as session:
        jobs = session.scalars(select(JobDocument)).all()
        assert len(jobs) == 2, "l'upload d'Alice ne doit pas ecraser le document legacy partage"
        legacy = session.scalar(select(JobDocument).where(JobDocument.path == str(legacy_path)))
        assert legacy is not None and legacy.created_by_user_id is None, (
            "le document legacy doit rester intact, toujours sans proprietaire"
        )


def test_uploading_a_colliding_filename_does_not_empty_another_profiles_archive(session_factory, ingest_env, tmp_path):
    """Reproduit exactement le second symptome rapporte en direct : l'archive
    d'un profil tombait a '0 CV, 0 offres' des qu'un autre profil uploadait
    un fichier de meme nom, parce que les deux profils partageaient la
    meme ligne CvDocument/JobDocument (re-upload = desarchivage automatique
    -- voir _ensure_pending_document_and_unarchive)."""
    alice = _make_user(session_factory, "alice8@test.local")
    bob = _make_user(session_factory, "bob8@test.local")

    app_main.ingest_file(
        _fake_request(alice), folder="job", upload=_make_upload("offre.txt", b"Offre d'Alice"), filename=None, priority_keywords=None,
    )
    with session_factory() as session:
        alice_job = session.scalar(select(JobDocument).where(JobDocument.created_by_user_id == alice.id))
        archive = AnalysisSession(name="Lot d'Alice", status="closed", created_by_user_id=alice.id)
        session.add(archive)
        session.commit()
        session.refresh(archive)
        alice_job_obj = session.get(JobDocument, alice_job.id)
        alice_job_obj.session_id = archive.id
        session.commit()
        archive_id = archive.id

    app_main.ingest_file(
        _fake_request(bob), folder="job", upload=_make_upload("offre.txt", b"Offre de Bob"), filename=None, priority_keywords=None,
    )

    with session_factory() as session:
        alice_job_after = session.scalar(select(JobDocument).where(JobDocument.created_by_user_id == alice.id))
        assert alice_job_after.session_id == archive_id, (
            "l'archive d'alice ne doit pas etre videe par l'upload de bob"
        )
