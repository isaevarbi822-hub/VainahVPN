"""Manual H1 grants: no real provider calls, no payment bypass."""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import manual_grants
from vainah.h1_panel import H1PanelError
from vainah.main import app


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("VAINAH_MANUAL_GRANTS_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", "operator-" + "s" * 40)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", "pilot-" + "p" * 44)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-signing-" + "k" * 44)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/db")
    monkeypatch.setenv("PANEL_BASE_URL", "https://panel.example.test:25105/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-panel-token")
    monkeypatch.delenv("PANEL_TLS_CA_PEM", raising=False)


def test_operator_requires_both_secrets_and_opt_in(configured, monkeypatch):
    monkeypatch.delenv("VAINAH_MANUAL_GRANTS_ENABLED")
    with TestClient(app) as c:
        r = c.get("/api/operator/manual-grants/status", headers={
            "X-Sandbox-Token": "operator-" + "s" * 40,
            "X-Live-Pilot-Token": "pilot-" + "p" * 44,
        })
        assert r.status_code == 503
        r = c.post("/api/operator/manual-grants/issue", json={
            "recipient_email": "test@example.com", "grant_id": "a" * 32,
            "days": 30, "devices": 3, "confirm": True,
        })
        assert r.status_code == 401
    monkeypatch.setenv("VAINAH_MANUAL_GRANTS_ENABLED", "enabled")
    with TestClient(app) as c:
        r = c.get("/api/operator/manual-grants/status", headers={
            "X-Sandbox-Token": "operator-" + "s" * 40,
        })
        assert r.status_code == 401


def test_create_verifies_absence_then_write_then_exact_readback(configured, monkeypatch):
    name = manual_grants._client_name("a" * 32)
    expires = int(time.time()) + 86400 * 30
    methods = []
    def handler(req):
        methods.append(req.method)
        assert req.url.scheme == "https"
        assert req.headers["Authorization"] == "Bearer test-panel-token"
        if len(methods) == 1:
            assert req.method == "GET"
            assert req.url.params["name"] == name
            return httpx.Response(404, json={"error": "user_not_found"})
        if len(methods) == 2:
            assert req.method == "POST"
            assert req.url.path == "/api/create"
            assert req.read().decode() == (
                '{"name":"' + name + '","days":30,"device_limit":3}'
            )
            return httpx.Response(200, json={"ok": True})
        assert req.method == "GET"
        return httpx.Response(200, json={"ok": True, "client": {
            "name": name, "expires_at": expires, "device_limit": 3,
            "subscription_url": "https://example.com/private-subscription",
        }})
    value, expiry = asyncio.run(manual_grants._provision(
        client_name=name, days=30, devices=3,
        transport=httpx.MockTransport(handler),
    ))
    assert value == "https://example.com/private-subscription"
    assert expiry == expires
    assert methods == ["GET", "POST", "GET"]


def test_network_timeout_never_retries_write(configured):
    name = manual_grants._client_name("b" * 32)
    methods = []
    def handler(req):
        methods.append(req.method)
        if req.method == "GET":
            return httpx.Response(404, json={"error": "user_not_found"})
        raise httpx.ReadTimeout("H1 may have committed")
    with pytest.raises(manual_grants.GrantError, match="WRITE_UNCERTAIN"):
        asyncio.run(manual_grants._provision(
            client_name=name, days=7, devices=2,
            transport=httpx.MockTransport(handler),
        ))
    assert methods == ["GET", "POST"]


def test_invalid_readback_never_confirms_issued(configured):
    name = manual_grants._client_name("c" * 32)
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"ok": True})
        if req.url.params["name"] == name and handler.count == 0:
            handler.count += 1
            return httpx.Response(404, json={"error": "user_not_found"})
        return httpx.Response(200, json={"ok": True, "client": {
            "name": name, "expires_at": int(time.time())+86400,
            "device_limit": 2, "subscription_url": "https://example.com/private",
        }})
    handler.count = 0
    with pytest.raises(manual_grants.GrantError, match="POSTCHECK_INVALID"):
        asyncio.run(manual_grants._provision(
            client_name=name, days=30, devices=3,
            transport=httpx.MockTransport(handler),
        ))


def test_a_failed_email_does_not_undo_an_issued_grant(configured, monkeypatch):
    claimed = []
    finished = []
    monkeypatch.setattr(manual_grants, "_claim",
        lambda grant_id, owner, days, devices, name: claimed.append(name) or None)
    async def provision(**kwargs):
        return "https://example.com/private", int(time.time()) + 86400 * 7
    async def bad_email(*args, **kwargs):
        raise HTTPException(503, "EMAIL_DELIVERY_UNAVAILABLE")
    monkeypatch.setattr(manual_grants, "_provision", provision)
    monkeypatch.setattr(manual_grants, "send_email", bad_email)
    monkeypatch.setattr(manual_grants, "_finish",
        lambda grant_id, url, expiry: finished.append((grant_id, url)))
    result = asyncio.run(manual_grants.issue_grant(
        email="client@example.com", grant_id="d" * 32, days=7, devices=2
    ))
    assert claimed and finished
    assert result["status"] == "issued"
    assert result["email_sent"] is False
    assert result["subscription_url"] == "https://example.com/private"


def test_saved_issued_grant_recovers_link_during_temporary_panel_outage(configured, monkeypatch):
    """Only the verified original owner may recover a pre-issued, unexpired link."""

    expiry = datetime.fromtimestamp(time.time() + 3600, UTC)
    original_url = "https://example.com/previously-issued-access"
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, *args): pass
        def fetchone(self): return ("vn" + "a" * 28, 30, 2, expiry, "sealed")
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def cursor(self): return FakeCursor()
    monkeypatch.setattr(manual_grants.psycopg, "connect", lambda *a, **kw: FakeConn())
    async def temporarily_unavailable(*args, **kwargs):
        raise H1PanelError("PANEL_CONNECT_TIMEOUT")
    monkeypatch.setattr(manual_grants, "read_h1_issued_client_status", temporarily_unavailable)
    monkeypatch.setattr(manual_grants, "unseal_live_secret", lambda cipher: original_url)
    public = asyncio.run(manual_grants.manual_grant_summary_for_email("client@example.com"))
    assert public["available"] is True
    assert public["provider_verified"] is False
    assert "subscription_url" not in public
    private = asyncio.run(manual_grants.manual_grant_summary_for_email(
        "client@example.com", include_secret=True
    ))
    assert private["subscription_url"] == original_url
    assert private["provider_verified"] is False


def test_saved_grant_never_claims_active_when_panel_reports_inactive(configured, monkeypatch):

    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, *args): pass
        def fetchone(self):
            return ("vn" + "a" * 28, 30, 2,
                datetime.fromtimestamp(time.time() + 3600, UTC), "sealed")
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def cursor(self): return FakeCursor()
    monkeypatch.setattr(manual_grants.psycopg, "connect", lambda *a, **kw: FakeConn())
    async def inactive(*args, **kwargs):
        return {"active": False, "panel_ready": True}
    monkeypatch.setattr(manual_grants, "read_h1_issued_client_status", inactive)
    result = asyncio.run(manual_grants.manual_grant_summary_for_email(
        "client@example.com", include_secret=True
    ))
    assert result == {"available": False}
