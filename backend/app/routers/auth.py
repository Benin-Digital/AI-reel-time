"""Endpoints d'authentification et gestion utilisateurs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..auth import authenticate_user, create_access_token, hash_password, verify_password
from ..db import SessionLocal
from ..deps import require_admin, require_superadmin
from ..models import User
from ..schemas import (
    AuthLoginRequest,
    AuthLoginResponse,
    UserCreate,
    UserRead,
    UserSelfUpdate,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthLoginResponse)
def login(payload: AuthLoginRequest) -> AuthLoginResponse:
    with SessionLocal() as session:
        user = authenticate_user(session, payload.email, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(user)
        return AuthLoginResponse(
            access_token=token,
            user=UserRead.model_validate(user),
        )


@router.get("/me", response_model=UserRead)
def get_me(request: Request) -> UserRead:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead)
def update_me(payload: UserSelfUpdate, request: Request) -> UserRead:
    """Self-service email/password change. Superadmin-only for now: the
    superadmin account is otherwise fully locked out of PATCH /users/{id}
    (see the blanket "Superadmin account is protected" guard there), which
    left it with no way to ever change its own credentials."""
    current_user = require_superadmin(request)

    if payload.new_email is None and payload.new_password is None:
        raise HTTPException(status_code=400, detail="Provide new_email and/or new_password")

    with SessionLocal() as session:
        user = session.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        if payload.new_email is not None and payload.new_email != user.email:
            existing = session.scalar(select(User).where(User.email == payload.new_email))
            if existing is not None:
                raise HTTPException(status_code=409, detail="Email already in use")
            user.email = payload.new_email

        if payload.new_password is not None:
            user.password_hash = hash_password(payload.new_password)

        session.add(user)
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)


@router.get("/users", response_model=list[UserRead])
def list_users(request: Request) -> list[UserRead]:
    require_admin(request)
    with SessionLocal() as session:
        rows = session.scalars(select(User).order_by(User.id.asc())).all()
        return [UserRead.model_validate(row) for row in rows]


@router.post("/users", response_model=UserRead)
def create_user(payload: UserCreate, request: Request) -> UserRead:
    current_user = require_admin(request)
    if current_user.role == "admin" and payload.role != "member":
        raise HTTPException(status_code=403, detail="Admin can only create member accounts")
    with SessionLocal() as session:
        existing = session.scalar(select(User).where(User.email == payload.email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="User already exists")
        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserUpdate, request: Request) -> UserRead:
    current_user = require_admin(request)
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role == "superadmin":
            raise HTTPException(status_code=403, detail="Superadmin account is protected")

        if current_user.role == "admin":
            if user.role != "member":
                raise HTTPException(status_code=403, detail="Admin can only manage member accounts")
            if payload.role is not None and payload.role != "member":
                raise HTTPException(status_code=403, detail="Admin can only keep member role")

        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active

        session.add(user)
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)
