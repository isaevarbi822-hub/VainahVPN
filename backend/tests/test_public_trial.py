"""Verified free one-day VPN trial with real disposable DB and mocked H1."""
from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import public_trial
from vainah.live_checkout import owner_ref_for_email
from vainah.live_ledger import PostgresLiveOrderLedger, seal_live_secret
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
EMAIL = "trial-customer@example.test"


@pytest.fixture
def trial(monkeypatch, postgres_url):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "unit-trial-" + "k" * 48)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-" + "r" * 38)
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "support@example.test")
    monkeypatch.setenv("VAINAH_PUBLIC_TRIAL_ENABLED", "enabled")
    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "h1-private-key-test")
    monkeypatch.delenv("PANEL_TLS_CA_PEM", raising=False)
    monkeypatch.setattr(public_trial, "current_email", lambda _req: EMAIL)
    assert public_trial.enabled() is True
    return postgres_url


def provider_factory(*, good_quota=True):
    calls = []
    expires = int(time.time()) + 86400
    name = public_trial._owner_name(EMAIL)

    def provider(request):
        calls.append((request.method, request.url.path))
        assert request.url.host == "vpn-panel.example.com"
        assert request.headers["Authorization"] == "Bearer h1-private-key-test"
        if request.method == "POST":
            assert request.url.path == "/api/create"
            assert json.loads(request.content) == {
                "name": name, "days": 1,
                "device_limit": 2, "traffic_limit_gb": 10,
            }
            return httpx.Response(200, json={"ok": True})
        assert request.method == "GET"
        assert request.url.path == "/api/info"
        assert request.url.params["name"] == name
        if not any(method == "POST" for method, _ in calls):
            return httpx.Response(404, json={"error": "user_not_found"})
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": name, "device_limit": 2,
                "traffic_limit_bytes": (
                    10 * 1024**3 if good_quota else 0
                ),
                "expires_at": expires,
                "subscription_url": "https://sub.example.com/private-trial",
                "banned": False,
            },
        })
    return httpx.MockTransport(provider), calls


def test_public_config_is_free_and_excluded_from_paid_catalog(trial):
    with TestClient(app, base_url=ORIGIN) as client:
        data = client.get("/api/trial/config").json()
        assert data == {
            "available": True, "days": 1, "devices": 2,
            "traffic_gb": 10, "price_rub": 0, "one_time": True,
            "requires_verified_email": True,
        }
        assert all(x["id"] != "trial" for x in
                   client.get("/api/shop/plans").json()["items"])


def test_h1_quota_verified_and_trial_one_time(trial):
    transport, calls = provider_factory()
    delivered = asyncio.run(public_trial.issue_trial_once(
        EMAIL, transport=transport
    ))
    assert delivered["status"] == "delivered"
    assert delivered["devices"] == 2
    assert delivered["traffic_gb"] == 10
    assert delivered["subscription_url"].startswith("https://")
    assert [x[0] for x in calls] == ["GET", "POST", "GET"]
    with TestClient(app, base_url=ORIGIN) as client:
        data = client.get("/api/trial/status").json()
        assert data["status"] == "delivered"
        assert data["can_claim"] is False
        assert data["subscription_url"] == delivered["subscription_url"]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(public_trial.issue_trial_once(EMAIL, transport=transport))
    assert exc.value.status_code == 409
    assert [x[0] for x in calls].count("POST") == 1


def test_quota_not_verified_fails_closed_and_never_reissues(trial):
    transport, calls = provider_factory(good_quota=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(public_trial.issue_trial_once(EMAIL, transport=transport))
    assert exc.value.status_code == 503
    assert str(exc.value.detail) == "TRIAL_REQUIRES_OPERATOR_REVIEW"
    with TestClient(app, base_url=ORIGIN) as client:
        state = client.get("/api/trial/status").json()
    assert state == {"status": "manual_review", "can_claim": False}
    with pytest.raises(HTTPException) as repeated:
        asyncio.run(public_trial.issue_trial_once(EMAIL, transport=transport))
    assert repeated.value.status_code == 409
    assert [x[0] for x in calls].count("POST") == 1


def test_existing_paid_customer_cannot_claim_free_trial(trial):
    owner = owner_ref_for_email(EMAIL)
    store = PostgresLiveOrderLedger(trial)
    with psycopg.connect(trial) as conn, conn.cursor() as cur:
        store._schema(cur)
        cur.execute("""
            INSERT INTO vainah_live_orders (
              order_id, owner_ref, plan_id, amount_rub,
              receipt_email_cipher, payment_state
            ) VALUES (%s, %s, '30', 99, %s, 'paid')
        """, ("vainah_live_" + "f" * 32, owner,
              seal_live_secret(EMAIL)))
    transport, calls = provider_factory()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(public_trial.issue_trial_once(EMAIL, transport=transport))
    assert exc.value.status_code == 409
    assert calls == []


def test_concurrent_claims_issue_only_one_h1_write(trial):
    owner = owner_ref_for_email(EMAIL)
    name = public_trial._owner_name(EMAIL)
    def reserve(_):
        try:
            public_trial._reserve(owner_ref=owner, client_name=name)
            return "ok"
        except public_trial.TrialError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(reserve, range(4)))
    assert outcomes.count("ok") == 1
    assert outcomes.count("TRIAL_ALREADY_CLAIMED") == 3


def test_requires_valid_email_session_and_same_origin(trial, monkeypatch):
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get("/api/trial/status")
        assert result.status_code == 200
        monkeypatch.setattr(public_trial, "current_email", lambda _req: None)
        assert client.get("/api/trial/status").status_code == 401
        assert client.post("/api/trial/claim", headers={"Origin": ORIGIN}).status_code == 401
        monkeypatch.setattr(public_trial, "current_email", lambda _req: EMAIL)
        cross = client.post("/api/trial/claim",
                            headers={"Origin": "https://evil.example"})
        assert cross.status_code == 403


def test_trial_disabled_by_default(monkeypatch, trial):
    monkeypatch.delenv("VAINAH_PUBLIC_TRIAL_ENABLED")
    assert public_trial.enabled() is False
    transport, calls = provider_factory()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(public_trial.issue_trial_once(EMAIL, transport=transport))
    assert exc.value.status_code == 503
    assert calls == []
