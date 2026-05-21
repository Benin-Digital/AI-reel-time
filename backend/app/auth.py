from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from fastapi import HTTPException, Request
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User
from .settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=max(1, settings.jwt_access_token_minutes)
    )
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, str]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def authenticate_request(request: Request, session: Session) -> User:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = session.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid user")
    return user


def ensure_bootstrap_user(session: Session) -> None:
    if not settings.auth_enabled:
        return
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        logger.warning("Auth enabled without bootstrap admin credentials.")
        return

    if settings.jwt_secret_key == "change-me":
        logger.warning("JWT secret key uses default value; update AI_REALTIME_JWT_SECRET_KEY.")

    existing = session.scalar(
        select(User).where(User.email == settings.bootstrap_admin_email)
    )
    if existing is not None:
        return

    user = User(
        email=settings.bootstrap_admin_email,
        password_hash=hash_password(settings.bootstrap_admin_password),
        role=settings.bootstrap_admin_role or "admin",
        is_active=True,
    )
    session.add(user)
    session.commit()
