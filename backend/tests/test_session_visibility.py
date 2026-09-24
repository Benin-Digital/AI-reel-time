"""Test de non-regression pour un bug rapporte en direct (2026-09-24) :
superadmin/admin/member voyaient tous exactement la meme liste d'archives
et de correspondances, quel que soit qui les avait creees -- aucune table
ne portait de colonne "cree par" et aucun endpoint ne filtrait par
utilisateur, seulement par role pour decider quels endpoints sont
appelables du tout (deps.require_admin/require_superadmin).

Regle demandee, strictement hierarchique par role (member < admin <
superadmin) : chacun voit ses propres archives (jamais visibles a un pair
ou un superieur) plus celles de tout role strictement inferieur au sien.
- member : uniquement les siennes.
- admin : les siennes + celles de tous les member.
- superadmin : les siennes + celles de tous les admin et member.

Une archive sans proprietaire enregistre (colonne NULL, cree avant ce
correctif ou par un processus systeme) reste visible aux roles eleves
(admin/superadmin) mais pas a un member -- voir
deps.can_see_unclaimed_archives.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.models import AnalysisSession, Base, CvDocument, ExtractedText, JobDocument, MatchFeedback, MatchResult, User
import app.routers.matches as matches_router
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
            MatchFeedback.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(sessions_router, "SessionLocal", factory)
    monkeypatch.setattr(matches_router, "SessionLocal", factory)
    return factory


def _make_user(factory: sessionmaker, email: str, role: str) -> User:
    with factory() as session:
        user = User(email=email, password_hash="x", role=role)
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def _make_archive(factory: sessionmaker, name: str, owner: User | None) -> int:
    with factory() as session:
        archive = AnalysisSession(
            name=name,
            status="closed",
            created_by_user_id=owner.id if owner else None,
        )
        session.add(archive)
        session.commit()
        session.refresh(archive)
        return archive.id


@pytest.fixture
def roles(session_factory):
    member = _make_user(session_factory, "member@test.local", "member")
    admin = _make_user(session_factory, "admin@test.local", "admin")
    superadmin = _make_user(session_factory, "superadmin@test.local", "superadmin")
    return SimpleNamespace(member=member, admin=admin, superadmin=superadmin)


def test_member_sees_only_their_own_archive(session_factory, roles):
    _make_archive(session_factory, "Archive du member", roles.member)
    _make_archive(session_factory, "Archive de l'admin", roles.admin)
    _make_archive(session_factory, "Archive du superadmin", roles.superadmin)

    result = sessions_router.list_analysis_sessions(_fake_request(roles.member))

    assert [s.name for s in result] == ["Archive du member"]


def test_admin_sees_own_plus_every_member_archive_but_not_other_admins_or_superadmin(session_factory, roles):
    other_admin = _make_user(session_factory, "admin2@test.local", "admin")
    _make_archive(session_factory, "Archive du member", roles.member)
    _make_archive(session_factory, "Archive de cet admin", roles.admin)
    _make_archive(session_factory, "Archive d'un autre admin", other_admin)
    _make_archive(session_factory, "Archive du superadmin", roles.superadmin)

    result = sessions_router.list_analysis_sessions(_fake_request(roles.admin))
    names = {s.name for s in result}

    assert names == {"Archive du member", "Archive de cet admin"}


def test_superadmin_sees_everyone_elses_archives(session_factory, roles):
    _make_archive(session_factory, "Archive du member", roles.member)
    _make_archive(session_factory, "Archive de l'admin", roles.admin)
    _make_archive(session_factory, "Archive du superadmin", roles.superadmin)

    result = sessions_router.list_analysis_sessions(_fake_request(roles.superadmin))
    names = {s.name for s in result}

    assert names == {"Archive du member", "Archive de l'admin", "Archive du superadmin"}


def test_nobody_but_the_superadmin_themself_sees_their_own_archive(session_factory, roles):
    other_superadmin = _make_user(session_factory, "superadmin2@test.local", "superadmin")
    _make_archive(session_factory, "Archive prive du superadmin", roles.superadmin)

    result = sessions_router.list_analysis_sessions(_fake_request(other_superadmin))

    assert result == [], "un pair superadmin ne doit jamais voir l'archive d'un autre superadmin"


def test_list_includes_owner_label_for_someone_elses_archive(session_factory, roles):
    roles.member.first_name, roles.member.last_name = "Awa", "Diallo"
    with session_factory() as session:
        session.merge(roles.member)
        session.commit()
    _make_archive(session_factory, "Archive du member", roles.member)

    result = sessions_router.list_analysis_sessions(_fake_request(roles.admin))

    assert result[0].created_by_label == "Awa Diallo"
    assert result[0].created_by_role == "utilisateur"


def test_get_session_404s_instead_of_403_for_an_invisible_archive(session_factory, roles):
    """404, pas 403 : un member ne doit meme pas pouvoir deduire qu'une
    archive existe a cet id en observant un code d'erreur different."""
    archive_id = _make_archive(session_factory, "Archive de l'admin", roles.admin)

    with pytest.raises(HTTPException) as exc_info:
        sessions_router.get_analysis_session(archive_id, _fake_request(roles.member))

    assert exc_info.value.status_code == 404


def test_unclaimed_legacy_archive_visible_to_admin_not_to_member(session_factory, roles):
    _make_archive(session_factory, "Archive sans proprietaire", None)

    admin_result = sessions_router.list_analysis_sessions(_fake_request(roles.admin))
    member_result = sessions_router.list_analysis_sessions(_fake_request(roles.member))

    assert [s.name for s in admin_result] == ["Archive sans proprietaire"]
    assert member_result == []


def test_matches_in_an_invisible_archive_are_excluded_from_the_match_list(session_factory, roles):
    """Le bug original s'etendait aux correspondances : cocher 'inclure
    les archives' sur la page Correspondances montrait tout le monde,
    peu importe le role -- ce test verifie que GET /matches respecte
    desormais la meme regle que GET /sessions."""
    other_admin = _make_user(session_factory, "admin3@test.local", "admin")
    hidden_archive_id = _make_archive(session_factory, "Archive d'un autre admin", other_admin)

    with session_factory() as session:
        cv = CvDocument(path="/cv/hidden.pdf", status="ready", session_id=hidden_archive_id)
        job = JobDocument(path="/job/hidden.pdf", status="ready", session_id=hidden_archive_id)
        session.add_all([cv, job])
        session.commit()
        session.add(MatchResult(cv_id=cv.id, job_id=job.id, score=90.0))
        session.commit()

    results = matches_router.list_matches(_fake_request(roles.admin), unassigned_only=False)

    assert results == [], "un match archive dans une session invisible ne doit jamais apparaitre"


def test_matches_in_a_visible_archive_still_appear(session_factory, roles):
    own_archive_id = _make_archive(session_factory, "Archive de cet admin", roles.admin)

    with session_factory() as session:
        cv = CvDocument(path="/cv/own.pdf", status="ready", session_id=own_archive_id)
        job = JobDocument(path="/job/own.pdf", status="ready", session_id=own_archive_id)
        session.add_all([cv, job])
        session.commit()
        session.add(MatchResult(cv_id=cv.id, job_id=job.id, score=90.0))
        session.commit()

    results = matches_router.list_matches(_fake_request(roles.admin), unassigned_only=False)

    assert len(results) == 1


def test_unarchived_matches_remain_visible_to_everyone(session_factory, roles):
    """Le champ d'application du fix est explicitement les archives -- un
    match encore actif (session_id NULL des deux cotes) ne doit pas
    devenir invisible pour un member juste parce que la fonctionnalite
    d'archivage existe."""
    with session_factory() as session:
        cv = CvDocument(path="/cv/active.pdf", status="ready", session_id=None)
        job = JobDocument(path="/job/active.pdf", status="ready", session_id=None)
        session.add_all([cv, job])
        session.commit()
        session.add(MatchResult(cv_id=cv.id, job_id=job.id, score=90.0))
        session.commit()

    results = matches_router.list_matches(_fake_request(roles.member), unassigned_only=False)

    assert len(results) == 1
