"""Automatic SANDBOX RollyPay paid -> H1Cloud issuance integration tests.

Real money, real provider API and real PostgreSQL are never contacted.
The provider stub validates that only one POST is sent per signed test order.
"""
from __future__ import annotations

import json
import time

import httpx
import pytest

from vainah import billing
from vainah import sandbox_auto_h1 as auto
from vainah.postgres_ledger import PostgresSandboxLedger

OPERATOR = "test-sandbox-operator-" + "x" * 40
WEBHOOK_SECRET = "test-webhook-only-" + "y" * 40
SIGNING_KEY = "test-account-secret-" + "z" * 40


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/vainah")
    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-h1-only-token")
    monkeypatch.delenv("PANEL_TLS_CA_PEM", raising=False)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SHOP_PROVIDER_TEST_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_MODE", "provider")
    monkeypatch.setenv("VAINAH_SANDBOX_AUTO_H1_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", OPERATOR)
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", WEBHOOK_SECRET)


def test_disabled_without_explicit_flag(configured, monkeypatch):
    monkeypatch.delenv("VAINAH_SANDBOX_AUTO_H1_ENABLED")
    assert auto.auto_enabled() is False
    monkeypatch.setenv("VAINAH_SANDBOX_AUTO_H1_ENABLED", "enabled")
    # Live app may not have persistent PostgreSQL test ledger: fail closed.
    old = billing.sandbox.ledger
    monkeypatch.setattr(billing.sandbox, "ledger", None)
    assert auto.auto_enabled() is False
    monkeypatch.setattr(
        billing.sandbox, "ledger",
        PostgresSandboxLedger("postgresql://test:test@localhost/vainah"),
    )
    old_mode = billing.sandbox.mode
    monkeypatch.setattr(billing.sandbox, "mode", "provider")
    assert auto.auto_enabled() is True
    monkeypatch.setattr(billing.sandbox, "mode", old_mode)
    monkeypatch.setattr(billing.sandbox, "ledger", old)


def test_h1_one_signed_paid_order_created_once(configured, monkeypatch):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "a" * 32
    client_name = auto._name(order)
    issued = []
    claims = []
    requests = []
    expires_at = int(time.time()) + 30 * 86400

    def claim_once(order_id):
        claims.append(order_id)
        return (
            auto.Claim(order_id, client_name, "30", "v1_" + "e" * 64)
            if len(claims) == 1 else None
        )

    def provider(request):
        requests.append((request.method, str(request.url)))
        assert request.url.scheme == "https"
        assert request.headers.get("Authorization") == "Bearer test-h1-only-token"
        assert request.url.path in ("/api/info", "/api/create")
        if len(requests) == 1:
            assert request.method == "GET"
            assert request.url.params.get("name") == client_name
            return httpx.Response(404, json={"error": "user_not_found"})
        if len(requests) == 2:
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "name": client_name, "days": 30, "device_limit": 3,
            }
            return httpx.Response(201, json={"ok": True})
        assert request.method == "GET"
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": client_name, "expires_at": expires_at,
                "device_limit": 3,
                "subscription_url": "https://sub.example.com/private-test-link",
            },
        })

    monkeypatch.setattr(auto, "_claim_once", claim_once)
    monkeypatch.setattr(
        auto, "_mark_issued",
        lambda order_id, url: issued.append((order_id, url)),
    )
    monkeypatch.setattr(
        auto, "read_delivery", lambda _id: {
            "status": "issued", "vpn_delivered": True,
        },
    )
    monkeypatch.setattr(
        auto, "_mark_review",
        lambda _order: pytest.fail("Successful write must not need review"),
    )
    transport = httpx.MockTransport(provider)
    result = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert result == {"status": "issued", "vpn_delivered": True}
    assert len(requests) == 3
    assert issued == [(order, "https://sub.example.com/private-test-link")]

    # Provider retries a correctly signed webhook: no second H1 request.
    repeated = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert repeated == {"status": "issued", "vpn_delivered": True}
    assert len(requests) == 3


def test_h1_ambiguous_post_stays_locked(configured, monkeypatch):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "b" * 32
    claimed = []
    needs_review = []
    calls = []
    monkeypatch.setattr(auto, "_claim_once", lambda order_id: (
        claimed.append(order_id) or
        auto.Claim(order_id, auto._name(order_id), "30", "v1_" + "f" * 64)
    ) if not claimed else None)
    monkeypatch.setattr(auto, "_mark_review", lambda oid: needs_review.append(oid))
    monkeypatch.setattr(auto, "read_delivery", lambda _id: {
        "status": "needs_review", "vpn_delivered": False,
    })

    def provider(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(404, json={"error": "user_not_found"})
        raise httpx.ReadTimeout("Test H1 write timeout")

    transport = httpx.MockTransport(provider)
    result = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert result["status"] == "needs_review"
    assert calls == ["GET", "POST"]
    assert needs_review == [order]
    again = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert again == {"status": "needs_review", "vpn_delivered": False}
    assert calls == ["GET", "POST"]


def test_claim_sql_requires_paid_signed_provider_and_owner(configured, monkeypatch):
    queries = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, params=None):
            queries.append((sql, params))

        def fetchone(self):
            return ("30", "v1_" + "e" * 64)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        auto.psycopg, "connect", lambda *_args, **_kw: Connection(),
    )
    order = "vainah_test_" + "a" * 32
    claim = auto._claim_once(order)
    assert claim.plan_id == "30"
    sql = next(q for q, _ in queries if "INSERT INTO vainah_sandbox_auto_h1" in q)
    for guard in (
        "status = 'paid'", "webhook_received = TRUE", "mode = 'provider'",
        "receipt_recipient IS NOT NULL", "ON CONFLICT (order_id) DO NOTHING",
    ):
        assert guard in sql
    assert order not in sql


