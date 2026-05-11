from types import SimpleNamespace

import pytest

import apps.api.auth.security as security
from apps.api.limiter import rate_limit_key_func


def test_jwt_secret_is_at_least_32_chars():
    assert len(security.JWT_SECRET) >= 32


def test_revocation_fail_open_returns_not_revoked(monkeypatch):
    def fail_redis():
        raise ConnectionError("redis down")

    monkeypatch.setattr(security, "AUTH_REVOCATION_FAIL_MODE", "open")
    monkeypatch.setattr(security, "_get_revocation_redis", fail_redis)

    assert security._is_token_revoked("jti") is False


def test_revocation_fail_closed_rejects_when_redis_unavailable(monkeypatch):
    def fail_redis():
        raise ConnectionError("redis down")

    monkeypatch.setattr(security, "AUTH_REVOCATION_FAIL_MODE", "closed")
    monkeypatch.setattr(security, "_get_revocation_redis", fail_redis)

    with pytest.raises(security.TokenRevocationUnavailableError):
        security._is_token_revoked("jti")


def test_rate_limit_uses_forwarded_ip_only_from_trusted_proxy(monkeypatch):
    request = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.10"),
        headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.10"},
    )
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "10.0.0.10")
    monkeypatch.setenv("RATE_LIMIT_CLIENT_IP_HEADER", "X-Forwarded-For")

    assert rate_limit_key_func(request) == "203.0.113.10"


def test_rate_limit_ignores_forwarded_ip_from_untrusted_proxy(monkeypatch):
    request = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.99"),
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "10.0.0.10")
    monkeypatch.setenv("RATE_LIMIT_CLIENT_IP_HEADER", "X-Forwarded-For")

    assert rate_limit_key_func(request) == "10.0.0.99"
