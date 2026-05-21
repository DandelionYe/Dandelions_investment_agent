"""Streamlit dashboard API auth client tests."""

from apps.dashboard.components import login


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_authenticated_request_sends_bearer_token(monkeypatch):
    session_state = {"auth_token": "access-1", "refresh_token": "refresh-1"}
    monkeypatch.setattr(login.st, "session_state", session_state)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return _Response(200, {"ok": True})

    monkeypatch.setattr(login.requests, "request", fake_request)

    resp = login.authenticated_request(
        "GET",
        "/api/v1/watchlist/items",
        params={"page_size": 200},
    )

    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0]["url"] == "http://localhost:8000/api/v1/watchlist/items"
    assert calls[0]["kwargs"]["headers"]["Authorization"] == "Bearer access-1"
    assert calls[0]["kwargs"]["params"] == {"page_size": 200}


def test_authenticated_request_refreshes_and_retries_on_401(monkeypatch):
    session_state = {"auth_token": "expired", "refresh_token": "refresh-1"}
    monkeypatch.setattr(login.st, "session_state", session_state)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(kwargs["headers"]["Authorization"])
        if len(calls) == 1:
            return _Response(401, text='{"detail":"Not authenticated"}')
        return _Response(200, {"ok": True})

    def fake_post(url, json, timeout):
        assert url == "http://localhost:8000/api/v1/auth/refresh"
        assert json == {"refresh_token": "refresh-1"}
        assert timeout == 5
        return _Response(
            200,
            {"access_token": "access-2", "refresh_token": "refresh-2"},
        )

    monkeypatch.setattr(login.requests, "request", fake_request)
    monkeypatch.setattr(login.requests, "post", fake_post)

    resp = login.authenticated_request("GET", "/api/v1/watchlist/folders")

    assert resp.status_code == 200
    assert calls == ["Bearer expired", "Bearer access-2"]
    assert session_state["auth_token"] == "access-2"
    assert session_state["refresh_token"] == "refresh-2"
