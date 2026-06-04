"""Tests for JWT token expiry check in login module.

Verifies that _is_token_expired correctly identifies expired tokens
and that _restore_from_query_params clears expired tokens from URL.
"""

import base64
import json
import time
from unittest.mock import patch

import pytest


def _make_jwt_token(exp: float | None, *, valid_format: bool = True) -> str:
    """Build a minimal JWT-like token with the given exp claim."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b"=")
    if exp is not None:
        payload_data = {"sub": "test", "exp": exp}
    else:
        payload_data = {"sub": "test"}
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=")
    if not valid_format:
        return header.decode()  # Missing payload and signature
    signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.{signature.decode()}"


class TestIsTokenExpired:
    """Test _is_token_expired helper."""

    def setup_method(self):
        from apps.dashboard.components.login import _is_token_expired
        self.is_expired = _is_token_expired

    def test_expired_token(self):
        """Token with exp in the past is expired."""
        token = _make_jwt_token(time.time() - 100)
        assert self.is_expired(token) is True

    def test_valid_token(self):
        """Token with exp far in the future is not expired."""
        token = _make_jwt_token(time.time() + 3600)
        assert self.is_expired(token) is False

    def test_token_within_margin(self):
        """Token expiring within _TOKEN_EXPIRY_MARGIN seconds is treated as expired."""
        # exp is 10 seconds from now, margin is 30 seconds → expired
        token = _make_jwt_token(time.time() + 10)
        assert self.is_expired(token) is True

    def test_token_just_outside_margin(self):
        """Token expiring just beyond margin is still valid."""
        # exp is 60 seconds from now, margin is 30 seconds → valid
        token = _make_jwt_token(time.time() + 60)
        assert self.is_expired(token) is False

    def test_no_exp_field(self):
        """Token without exp field is treated as expired."""
        token = _make_jwt_token(None)
        assert self.is_expired(token) is True

    def test_malformed_token(self):
        """Malformed token (not exactly 3 parts) is treated as expired."""
        assert self.is_expired("not-a-jwt") is True
        assert self.is_expired("") is True
        assert self.is_expired("header.payload") is True  # 2 parts, missing signature
        assert self.is_expired("a.b.c.d") is True  # 4 parts, too many

    def test_invalid_base64(self):
        """Token with invalid base64 payload is treated as expired."""
        assert self.is_expired("header.!!!invalid!!!.sig") is True

    def test_token_at_exact_expiry(self):
        """Token at exact exp time is expired (time.time() >= exp - margin)."""
        token = _make_jwt_token(time.time())
        assert self.is_expired(token) is True


class TestRestoreFromQueryParamsClearsExpiredToken:
    """Test that _restore_from_query_params clears expired tokens from URL."""

    def test_expired_token_cleared_from_url(self, tmp_path):
        """When URL contains an expired token, it should be cleared and return False."""
        import sys
        # We need to mock streamlit since it's not available in test context
        mock_st = type("MockSt", (), {})()
        mock_st.session_state = {}
        mock_st.query_params = {}

        expired_token = _make_jwt_token(time.time() - 100)
        auth_data = base64.b64encode(json.dumps({
            "access_token": expired_token,
            "refresh_token": "some_refresh",
            "username": "testuser",
        }).encode()).decode()

        mock_st.query_params = {"auth": auth_data}

        with patch.dict(sys.modules, {"streamlit": mock_st}):
            # Re-import with mocked streamlit
            import importlib
            if "apps.dashboard.components.login" in sys.modules:
                saved = sys.modules.pop("apps.dashboard.components.login")
            else:
                saved = None

            try:
                from apps.dashboard.components.login import _restore_from_query_params
                result = _restore_from_query_params()
                assert result is False
                # session_state should NOT have the token
                assert "auth_token" not in mock_st.session_state
            finally:
                if saved:
                    sys.modules["apps.dashboard.components.login"] = saved
