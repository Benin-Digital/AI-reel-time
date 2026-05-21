from __future__ import annotations

import logging
from typing import Set

from fastapi import HTTPException, Request

from .auth import authenticate_request
from .db import SessionLocal
from .services.rate_limit import check_rate_limit
from .settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

SKIP_PATHS = {
    "/health",
    "/ready",
    "/auth/login",
    "/openapi.json",
    "/docs",
    "/redoc",
}


def _parse_keys(raw: str) -> Set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def validate_security_settings() -> None:
    keys = _parse_keys(settings.api_keys)
    if settings.require_api_key and not keys:
        raise RuntimeError("API key auth enabled but no keys configured")
    if settings.environment != "local" and not settings.require_api_key:
        logger.warning("API key auth disabled outside local environment")


def _get_identifier(request: Request, api_key: str | None) -> str:
    if api_key:
        return api_key
    if request.client and request.client.host:
        return request.client.host
    return "anonymous"


def _validate_api_key(request: Request) -> str | None:
    if not settings.require_api_key:
        return None

    keys = _parse_keys(settings.api_keys)
    api_key = request.headers.get("x-api-key")
    if not api_key or api_key not in keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


def enforce_security(request: Request) -> None:
    if request.method == "OPTIONS":
        return

    if request.url.path in SKIP_PATHS:
        return

    if settings.auth_enabled:
        with SessionLocal() as session:
            user = authenticate_request(request, session)
            request.state.user = user

    api_key = _validate_api_key(request)

    if settings.rate_limit_enabled:
        identifier = _get_identifier(request, api_key)
        if not check_rate_limit(
            identifier,
            settings.rate_limit_max_requests,
            settings.rate_limit_window_seconds,
        ):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
