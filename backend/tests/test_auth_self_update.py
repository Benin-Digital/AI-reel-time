"""Tests pour PATCH /auth/me : changement self-service d'email/mot de passe.

Contexte : PATCH /users/{id} bloque TOUTE modification d'un compte
superadmin (y compris par lui-meme -- la garde ne distingue pas "un autre
utilisateur essaie de le modifier" de "le superadmin modifie son propre
compte"), et aucune route n'a jamais permis a un utilisateur de changer son
propre email/mot de passe de toute facon (UserUpdate n'expose que role et
is_active). Ce nouvel endpoint comble ce trou, reserve au superadmin.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.routers.auth as auth_router
from app.auth import hash_password, verify_password
from app.models import Base, User
from app.schemas import UserSelfUpdate


class _FakeState:
    def __init__(self, user):
        self.user = user


class _FakeRequest:
    def __init__(self, user):
        self.state = _FakeState(user)


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth_router, "SessionLocal", factory)
    return factory


def _make_user(session_factory, role="superadmin", email="admin@example.com", password="old-password-123"):
    with session_factory() as session:
        user = User(email=email, password_hash=hash_password(password), role=role, is_active=True)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def _status(exc_info) -> int | None:
    return getattr(exc_info.value, "status_code", None)


def test_non_superadmin_cannot_use_self_service_endpoint(session_factory):
    user = _make_user(session_factory, role="admin")
    payload = UserSelfUpdate(current_password="old-password-123", new_password="new-password-123")
    with pytest.raises(Exception) as exc_info:
        auth_router.update_me(payload, _FakeRequest(user))
    assert _status(exc_info) == 403


def test_wrong_current_password_is_rejected(session_factory):
    user = _make_user(session_factory)
    payload = UserSelfUpdate(current_password="wrong-password", new_password="new-password-123")
    with pytest.raises(Exception) as exc_info:
        auth_router.update_me(payload, _FakeRequest(user))
    assert _status(exc_info) == 401


def test_requires_at_least_one_field_to_change(session_factory):
    user = _make_user(session_factory)
    payload = UserSelfUpdate(current_password="old-password-123")
    with pytest.raises(Exception) as exc_info:
        auth_router.update_me(payload, _FakeRequest(user))
    assert _status(exc_info) == 400


def test_superadmin_can_change_own_password(session_factory):
    user = _make_user(session_factory)
    payload = UserSelfUpdate(current_password="old-password-123", new_password="new-password-456")

    result = auth_router.update_me(payload, _FakeRequest(user))

    assert result.id == user.id
    with session_factory() as session:
        refreshed = session.get(User, user.id)
        assert verify_password("new-password-456", refreshed.password_hash)
        assert not verify_password("old-password-123", refreshed.password_hash)


def test_superadmin_can_change_own_email(session_factory):
    user = _make_user(session_factory)
    payload = UserSelfUpdate(current_password="old-password-123", new_email="new-email@example.com")

    result = auth_router.update_me(payload, _FakeRequest(user))

    assert result.email == "new-email@example.com"


def test_cannot_change_email_to_one_already_in_use(session_factory):
    _make_user(session_factory, email="taken@example.com", password="whatever-123")
    user2 = _make_user(session_factory, email="me@example.com", password="old-password-123")
    payload = UserSelfUpdate(current_password="old-password-123", new_email="taken@example.com")

    with pytest.raises(Exception) as exc_info:
        auth_router.update_me(payload, _FakeRequest(user2))
    assert _status(exc_info) == 409


def test_new_password_below_minimum_length_is_rejected():
    with pytest.raises(Exception):
        UserSelfUpdate(current_password="old-password-123", new_password="short")
