"""Test de non-regression : desarchiver une session (POST
/sessions/{id}/unassign) detachait bien ses CV/offres mais laissait
toujours la session elle-meme en base, vide (status="open", 0 CV/0
offre/0 match) -- signale en direct par l'utilisateur (2026-09-15) : la
page Archives continuait d'afficher ce lot ("Lot rhconsole - Session 2,
Ouverte, 0 CV, 0 offres, 0 matches") indefiniment apres chaque
desarchivage, puisque seuls les documents etaient detaches, jamais
l'enregistrement de session lui-meme.

Le correctif supprime la session (comme delete_analysis_session le fait
deja quand on la ferme definitivement, sans toucher aux fichiers) une
fois ses documents detaches.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import pytest

from app.models import AnalysisSession, Base, CvDocument, JobDocument, User
import app.routers.sessions as sessions_router


def _fake_request(user: User) -> SimpleNamespace:
    """Every /sessions/* mutation now needs request.state.user (2026-09-24
    archive-visibility fix)."""
    return SimpleNamespace(state=SimpleNamespace(user=user))


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, AnalysisSession.__table__, CvDocument.__table__, JobDocument.__table__],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(sessions_router, "SessionLocal", factory)
    return factory


@pytest.fixture
def admin_user(session_factory) -> User:
    # admin (not member): the seeded archive below has no created_by_user_id
    # (legacy/unclaimed) -- deps.can_see_unclaimed_archives only grants
    # visibility to admin/superadmin, matching this test's actual intent
    # (can an authenticated caller unarchive this session), not the
    # separate ownership-visibility rules exercised in test_session_visibility.py.
    with session_factory() as session:
        user = User(email="admin@test.local", password_hash="x", role="admin")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def test_unassign_deletes_the_now_empty_session(session_factory, admin_user):
    with session_factory() as session:
        archive = AnalysisSession(name="Lot rhconsole - Session 2", status="closed")
        session.add(archive)
        session.commit()
        session.refresh(archive)
        session_id = archive.id
        session.add(CvDocument(path="/cv/1.pdf", status="ready", session_id=session_id))
        session.add(JobDocument(path="/job/1.pdf", status="ready", session_id=session_id))
        session.commit()

    result = sessions_router.unassign_session_documents(session_id, _fake_request(admin_user))

    assert result.cv_count == 0
    assert result.job_count == 0
    assert result.status == "open"

    with session_factory() as session:
        assert session.get(AnalysisSession, session_id) is None, (
            "la session vide doit disparaitre completement, pas juste "
            "rester avec des compteurs a zero"
        )
        cv = session.scalars(select(CvDocument)).one()
        job = session.scalars(select(JobDocument)).one()
        assert cv.session_id is None, "le CV doit redevenir actif (session_id NULL)"
        assert job.session_id is None, "l'offre doit redevenir active (session_id NULL)"


def test_unassign_missing_session_raises_404(session_factory, admin_user):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        sessions_router.unassign_session_documents(999, _fake_request(admin_user))
    assert exc_info.value.status_code == 404
