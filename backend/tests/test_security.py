import pytest
from fastapi import Request
from starlette.datastructures import Headers

from app import security


def _make_request(path: str, headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": Headers(headers or {}).raw,
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_health_skips_auth(monkeypatch):
    monkeypatch.setattr(security.settings, "require_api_key", True)
    monkeypatch.setattr(security.settings, "api_keys", "key")
    request = _make_request("/health")
    security.enforce_security(request)


def test_api_key_required(monkeypatch):
    monkeypatch.setattr(security.settings, "require_api_key", True)
    monkeypatch.setattr(security.settings, "api_keys", "key")
    request = _make_request("/scores")
    with pytest.raises(Exception):
        security.enforce_security(request)


def test_api_key_valid(monkeypatch):
    monkeypatch.setattr(security.settings, "require_api_key", True)
    monkeypatch.setattr(security.settings, "api_keys", "key")
    request = _make_request("/scores", {"x-api-key": "key"})
    security.enforce_security(request)
