"""Dependencies et helpers reutilisables pour les routers.

Centralise les guards d'autorisation (admin/superadmin) et l'acces a
Redis pour eviter la duplication entre `main.py` et les sous-routers.
"""
from __future__ import annotations

from fastapi import HTTPException, Request
import redis

from .models import User
from .settings import get_settings

settings = get_settings()


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def require_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(request: Request) -> User:
    user = require_user(request)
    if user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def require_superadmin(request: Request) -> User:
    user = require_admin(request)
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin role required")
    return user
