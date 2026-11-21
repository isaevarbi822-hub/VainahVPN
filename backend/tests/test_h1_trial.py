"""No-payment H1Cloud operator trial; never call the real provider in CI."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from vainah import h1_trial
from vainah.main import app


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("VAINAH_H1_TRIAL_ENABLED", "enabled")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-key-" + "s" * 44)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("PANEL_BASE_URL", "https://panel.example.com:25105/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "fake-token-no-real-provider")
    monkeypatch.delenv("PANEL_TLS_CA_PEM", raising=False)


def test_trial_one_write_then_verified_readback(configured, monkeypatch):
    issued = []
    claimed = []
    mark_uncertain = []
    requests = []
    expiry = int(time.time()) + 86400
    monkeypatch.setattr(
        h1_trial, "_claim_once",
        lambda db, name: claimed.append((db, name)) or True,
    )
    monkeypatch.setattr(
        h1_trial, "_save_success",
        lambda db, subscription: issued.append(subscription),
    )
    monkeypatch.setattr(
        h1_trial, "_mark_uncertain",
        lambda db: mark_uncertain.append(db),
    )
    def provider(request):
        requests.append((request.method, str(request.url), request.headers.get("Authorization")))
        expected_name, _ = h1_trial._ready()
        assert request.url.scheme == "https"
        assert request.headers.get("Authorization") == "Bearer fake-token-no-real-provider"
        if len(requests) == 1:
            assert request.method == "GET"
            assert request.url.path == "/api/info"
            assert request.url.params.get("name") == expected_name
            return httpx.Response(404, json={"error": "user_not_found"})
        if len(requests) == 2:
            assert request.method == "POST"
            assert request.url.path == "/api/create"
            assert request.read().decode() == (
                '{"name":"' + expected_name + '","days":1,"device_limit":1}'
            )
            return httpx.Response(200, json={"ok": True})
        assert request.method == "GET"
        assert request.url.params.get("name") == expected_name
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": expected_name,
                "expires_at": expiry,
                "device_limit": 1,
                "subscription_url": "https://sub.example.com/private-trial",
            },
        })

    result = asyncio.run(h1_trial.issue_operator_trial(
        transport=httpx.MockTransport(provider)
    ))
    assert [x[0] for x in requests] == ["GET", "POST", "GET"]
    assert claimed and not mark_uncertain
    assert issued == ["https://sub.example.com/private-trial"]
    assert result["test_only"] is True
    assert result["status"] == "issued"
    assert result["days"] == 1
    assert result["device_limit"] == 1
    assert result["payment_created"] is False


def test_trial_duplicate_claim_never_writes(configured, monkeypatch):
    monkeypatch.setattr(h1_trial, "_claim_once", lambda *_: False)
    events = []

    def provider(request):
        events.append(request.method)
        return httpx.Response(404, json={"error": "user_not_found"})

    with pytest.raises(h1_trial.TrialError, match="ALREADY_ATTEMPTED"):
        asyncio.run(h1_trial.issue_operator_trial(
            transport=httpx.MockTransport(provider)
        ))
    assert events == ["GET"]


def test_trial_ambiguous_post_stops_with_manual_review(configured, monkeypatch):
    uncertain = []
    monkeypatch.setattr(h1_trial, "_claim_once", lambda *_: True)
    monkeypatch.setattr(h1_trial, "_mark_uncertain", lambda db: uncertain.append(db))
    events = []

    def provider(request):
        events.append(request.method)
        if request.method == "GET":
            return httpx.Response(404, json={"error": "user_not_found"})
        raise httpx.ReadTimeout("Simulated write timeout")

    with pytest.raises(h1_trial.TrialError, match="WRITE_UNCERTAIN"):
        asyncio.run(h1_trial.issue_operator_trial(
            transport=httpx.MockTransport(provider)
        ))
    assert events == ["GET", "POST"]
    assert len(uncertain) == 1


def test_trial_rejects_bad_readback(configured, monkeypatch):
    mark_uncertain = []
    monkeypatch.setattr(h1_trial, "_claim_once", lambda *_: True)
    monkeypatch.setattr(h1_trial, "_mark_uncertain", lambda db: mark_uncertain.append(db))
    events = []
    def provider(request):
        events.append(request.method)
        if len(events) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            return httpx.Response(201, json={"ok": True})
        name, _ = h1_trial._ready()
        return httpx.Response(200, json={
            "ok": True,
            "client": {
                "name": name,
                "expires_at": int(time.time()) + 86400,
                "device_limit": 3,
                "subscription_url": "https://sub.example.com/secret",
            },
        })
    with pytest.raises(h1_trial.TrialError, match="POSTCHECK_INVALID"):
        asyncio.run(h1_trial.issue_operator_trial(
            transport=httpx.MockTransport(provider)
        ))
    assert events == ["GET", "POST", "GET"]
    assert len(mark_uncertain) == 1


def test_trial_requires_operator_and_explicit_confirmation(configured, monkeypatch):
    token = "operator-test-" + "t" * 40
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", token)
    called = []
    async def stub():
        called.append("issue")
        return {"status": "issued", "test_only": True}

    monkeypatch.setattr(h1_trial, "issue_operator_trial", stub)
    with TestClient(app) as client:
        unauthorized = client.post(
            "/api/site/integrations/h1cloud/trial/issue",
            json={"confirm": True},
        )
        assert unauthorized.status_code == 401
        for bad in ({}, {"confirm": False}, {"confirm": True, "days": 365}):
            resp = client.post(
                "/api/site/integrations/h1cloud/trial/issue",
                headers={"X-Sandbox-Token": token}, json=bad,
            )
            assert resp.status_code == 422
        assert called == []
        good = client.post(
            "/api/site/integrations/h1cloud/trial/issue",
            headers={"X-Sandbox-Token": token}, json={"confirm": True},
        )
        assert good.status_code == 200
        assert good.json()["test_only"] is True
        assert called == ["issue"]


def test_trial_disabled_is_fail_closed(monkeypatch):
    monkeypatch.delenv("VAINAH_H1_TRIAL_ENABLED", raising=False)
    with pytest.raises(h1_trial.TrialError, match="TRIAL_DISABLED"):
        asyncio.run(h1_trial.issue_operator_trial(transport=httpx.MockTransport(
            lambda _req: pytest.fail("No network when disabled")
        )))


@pytest.mark.parametrize("change", [
    {"expires_at": "short"}, {"expires_at": True},
    {"expires_at": 10**100}, {"expires_at": 2000000000000},
    {"expires_at": 2000000000.5}, {"banned": True},
    {"banned": "true"}, {"status": []}, {"status": "disabled"},
])
def test_trial_invalid_or_unusable_profile_is_never_saved(configured, monkeypatch, change):
    monkeypatch.setattr(h1_trial, "_claim_once", lambda *_: True)
    monkeypatch.setattr(h1_trial, "_save_success", lambda *_: pytest.fail("Unusable trial was saved"))
    reviewed, calls = [], []
    monkeypatch.setattr(h1_trial, "_mark_uncertain", lambda _: reviewed.append(True))

    def provider(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            return httpx.Response(201, json={"ok": True})
        name, _ = h1_trial._ready()
        profile = {
            "name": name, "expires_at": int(time.time()) + 86400,
            "device_limit": 1, "subscription_url": "https://sub.example/private-trial",
        } | change
        if profile["expires_at"] == "short":
            profile["expires_at"] = int(time.time()) + 1
        return httpx.Response(200, json={"ok": True, "client": profile})

    with pytest.raises(h1_trial.TrialError, match="POSTCHECK_INVALID"):
        asyncio.run(h1_trial.issue_operator_trial(transport=httpx.MockTransport(provider)))
    assert calls == ["GET", "POST", "GET"]
    assert reviewed == [True]


@pytest.mark.parametrize("phase", ["write", "postcheck"])
def test_cancelled_trial_stays_locked_and_marks_review(configured, monkeypatch, phase):
    monkeypatch.setattr(h1_trial, "_claim_once", lambda *_: True)
    reviewed, calls = [], []
    monkeypatch.setattr(h1_trial, "_mark_uncertain", lambda _: reviewed.append(True))

    def provider(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if phase == "write" or len(calls) == 3:
            raise asyncio.CancelledError()
        return httpx.Response(201, json={"ok": True})

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(h1_trial.issue_operator_trial(transport=httpx.MockTransport(provider)))
    assert reviewed == [True]
    assert calls.count("POST") == 1


def test_trial_real_postgres_concurrent_claims_and_key_rotation(configured, postgres_url, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    name, _ = h1_trial._ready()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: h1_trial._claim_once(postgres_url, name), range(8)))
    assert sum(claims) == 1
    monkeypatch.setenv("SESSION_SIGNING_KEY", "rotated-test-only-" + "r" * 40)
    new_name, _ = h1_trial._ready()
    assert new_name != name
    assert h1_trial._claim_once(postgres_url, new_name) is False


@pytest.mark.parametrize("operation", ["claim", "uncertain", "success"])
def test_trial_postgres_lock_waits_are_bounded(configured, postgres_url, monkeypatch, operation):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    name, _ = h1_trial._ready()
    assert h1_trial._claim_once(postgres_url, name)
    monkeypatch.setattr(h1_trial, "LOCK_TIMEOUT_MS", 30)
    monkeypatch.setattr(h1_trial, "STATEMENT_TIMEOUT_MS", 200)
    operations = {
        "claim": lambda: h1_trial._claim_once(postgres_url, name),
        "uncertain": lambda: h1_trial._mark_uncertain(postgres_url),
        "success": lambda: h1_trial._save_success(postgres_url, "https://sub.example/private-trial"),
    }
    with psycopg.connect(postgres_url) as holder:
        holder.execute("LOCK TABLE vainah_h1_trial_issuance IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        if operation == "uncertain":
            operations[operation]()  # Best effort: the durable claim stays locked.
        else:
            with pytest.raises(h1_trial.TrialError, match="DATABASE_UNAVAILABLE"):
                operations[operation]()
        assert time.monotonic() - started < 2
    with psycopg.connect(postgres_url) as conn:
        row = conn.execute("SELECT state, subscription_cipher FROM vainah_h1_trial_issuance").fetchone()
        assert row == ("claimed", None)
