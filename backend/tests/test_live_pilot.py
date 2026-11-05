"""The single real-money pilot stays private and cannot open public checkout.

Provider/H1 calls are mocked. PostgreSQL tests use disposable schemas only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from vainah import live_checkout
from vainah.live_ledger import LiveLedgerError, PostgresLiveOrderLedger
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SANDBOX_OPERATOR = "test-operator-" + "s" * 36
PILOT_OPERATOR = "test-pilot-only-" + "p" * 36
EMAIL = "pilot-owner@example.com"
SIGNING = "test-signing-only-" + "q" * 40


@pytest.fixture
def pilot_config(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING)
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", SANDBOX_OPERATOR)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", PILOT_OPERATOR)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_EMAIL", EMAIL)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_MERCHANT_APPROVED", "approved")
    monkeypatch.setenv("VAINAH_H1_WRITE_CONTRACT_APPROVED", "approved")
    monkeypatch.setenv("VAINAH_LIVE_FULFILLMENT_APPROVED", "approved")
    monkeypatch.setenv("ROLLYPAY_API_KEY", "test-live-api-" + "a" * 40)
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", "test-live-signing-" + "x" * 32)
    monkeypatch.delenv("VAINAH_LIVE_CHECKOUT_ENABLED", raising=False)
    monkeypatch.delenv("VAINAH_LIVE_PAID_E2E_VERIFIED", raising=False)
    monkeypatch.setattr(live_checkout, "_live_infrastructure_ready", lambda: True)
    monkeypatch.setattr(live_checkout, "current_email", lambda _req: EMAIL)
    assert live_checkout.pilot_ready() is True
    assert live_checkout.live_ready() is False


def pilot_headers():
    return {
        "Origin": ORIGIN,
        "X-Sandbox-Token": SANDBOX_OPERATOR,
        "X-Live-Pilot-Token": PILOT_OPERATOR,
        "Idempotency-Key": "123e4567-e89b-42d3-a456-426614174000",
    }


def test_pilot_disabled_by_default_even_with_merchant_flags(monkeypatch):
    monkeypatch.delenv("VAINAH_LIVE_PILOT_ENABLED", raising=False)
    assert live_checkout.pilot_ready() is False


def test_pilot_secret_must_be_distinct_from_exposed_sandbox_secret(
    pilot_config, monkeypatch,
):
    monkeypatch.setenv("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", SANDBOX_OPERATOR)
    assert live_checkout.pilot_ready() is False
    monkeypatch.setenv("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", PILOT_OPERATOR)
    assert live_checkout.pilot_ready() is True


@pytest.mark.parametrize("missing", [
    "VAINAH_MERCHANT_APPROVED",
    "VAINAH_H1_WRITE_CONTRACT_APPROVED",
    "VAINAH_LIVE_FULFILLMENT_APPROVED",
    "VAINAH_LIVE_PILOT_ENABLED",
])
def test_pilot_requires_all_separate_approvals(pilot_config, monkeypatch, missing):
    monkeypatch.delenv(missing)
    assert live_checkout.pilot_ready() is False


def test_public_checkout_never_opens_from_enabled_private_pilot(pilot_config):
    with TestClient(app, base_url=ORIGIN) as client:
        r = client.get("/api/shop/config")
        assert r.json()["checkout_ready"] is False
        assert r.json()["customer_accounts_ready"] is False
        r = client.post(
            "/api/shop/checkout", headers=pilot_headers(), json={"plan": "30"},
        )
        assert r.status_code == 503
        assert r.json()["detail"] == "LIVE_CHECKOUT_NOT_READY"


def test_private_pilot_checkout_is_explicit_and_owner_bound(pilot_config, monkeypatch):
    order_id = "vainah_live_" + uuid4().hex
    pay_url = "https://pay.rollypay.io/pay/single-pilot"
    calls = []

    class FakeLedger:
        def reserve_checkout(self, **kwargs):
            calls.append(("reserve", kwargs))
            return order_id, None

        def attach_hosted_invoice(self, **kwargs):
            calls.append(("attach", kwargs))
            return True

    monkeypatch.setattr(live_checkout, "_ledger", FakeLedger)

    async def fake_invoice(**kwargs):
        calls.append(("gateway", kwargs))
        return SimpleNamespace(
            order_id=order_id, payment_id="pay_123456789abcd",
            pay_url=pay_url,
        )

    monkeypatch.setattr(live_checkout, "create_hosted_live_invoice", fake_invoice)
    with TestClient(app, base_url=ORIGIN) as client:
        path = "/api/shop/operator/live-pilot/checkout"
        valid = pilot_headers()
        assert client.post(path, headers={k: v for k, v in valid.items()
                     if k != "X-Sandbox-Token"}, json={"plan": "30"}).status_code == 401
        assert client.post(path, headers={k: v for k, v in valid.items()
                     if k != "X-Live-Pilot-Token"}, json={"plan": "30"}).status_code == 401
        assert client.post(path, headers={k: v for k, v in valid.items()
                     if k != "Origin"}, json={"plan": "30"}).status_code == 403
        assert client.post(path, headers=valid, json={"plan": "365-family"}).status_code == 422
        assert client.post(path, headers={k: v for k, v in valid.items()
                     if k != "Idempotency-Key"}, json={"plan": "30"}).status_code == 422
        assert calls == []
        created = client.post(path, headers=valid, json={"plan": "30"})
        assert created.status_code == 200, created.text
        assert created.json()["operator_pilot"] is True
        assert created.json()["pay_url"] == pay_url
    assert [kind for kind, _ in calls] == ["reserve", "gateway", "attach"]
    assert calls[0][1]["pilot"] is True
    assert calls[0][1]["verified_email"] == EMAIL
    assert calls[1][1]["verified_merchant_approved"] is True


def test_private_pilot_email_must_match_server_allowlist(pilot_config, monkeypatch):
    monkeypatch.setattr(live_checkout, "current_email", lambda _req: "other@example.com")
    with TestClient(app, base_url=ORIGIN) as client:
        r = client.post("/api/shop/operator/live-pilot/checkout",
            headers=pilot_headers(), json={"plan": "30"})
        assert r.status_code == 403
        assert r.json()["detail"] == "LIVE_PILOT_EMAIL_NOT_ALLOWED"


def test_private_pilot_requires_verified_email_cookie(pilot_config, monkeypatch):
    monkeypatch.setattr(live_checkout, "current_email", lambda _req: None)
    with TestClient(app, base_url=ORIGIN) as client:
        r = client.post("/api/shop/operator/live-pilot/checkout",
            headers=pilot_headers(), json={"plan": "30"})
        assert r.status_code == 401
        assert r.json()["detail"] == "VERIFIED_EMAIL_REQUIRED"


def test_pilot_payment_webhook_is_signed_and_restricted(pilot_config, monkeypatch):
    order_id = "vainah_live_" + uuid4().hex
    nonpilot_id = "vainah_live_" + uuid4().hex
    events = []

    class FakeLedger:
        def is_live_pilot_order(self, oid):
            return oid == order_id

        def record_signed_paid(self, **kwargs):
            events.append("paid")
            return True

    monkeypatch.setattr(live_checkout, "_ledger", FakeLedger)

    async def fake_fulfill(**_kwargs):
        events.append("delivered")
        return {"status": "delivered", "vpn_delivered": True}

    async def fake_receipt(**_kwargs):
        events.append("receipt")
        return {"status": "sent"}

    monkeypatch.setattr(live_checkout, "fulfill_paid_order_once", fake_fulfill)
    monkeypatch.setattr(live_checkout, "send_paid_access_receipt_once", fake_receipt)
    secret = "test-live-signing-" + "x" * 32

    def signed(oid, *, valid=True):
        raw = json.dumps({
            "event_type": "payment.paid", "status": "paid",
            "order_id": oid, "test": False,
        }).encode()
        timestamp = str(int(time.time()))
        sig = hmac.new(secret.encode(), timestamp.encode() + b"." + raw,
            hashlib.sha256).hexdigest()
        if not valid:
            sig = "0" * 64
        return raw, {
            "X-Timestamp": timestamp, "X-Signature": sig, "X-Test-Mode": "false",
        }

    with TestClient(app, base_url=ORIGIN) as client:
        body, headers = signed(nonpilot_id)
        other = client.post("/api/shop/webhooks/rollypay",
            content=body, headers=headers)
        assert other.status_code == 503
        assert other.json()["detail"] == "PRODUCTION_PAYMENTS_DISABLED"
        body, headers = signed(order_id, valid=False)
        bad = client.post("/api/shop/webhooks/rollypay",
            content=body, headers=headers)
        assert bad.status_code == 403
        assert events == []
        body, headers = signed(order_id)
        paid = client.post("/api/shop/webhooks/rollypay",
            content=body, headers=headers)
        assert paid.status_code == 200, paid.text
        assert paid.json()["vpn_delivered"] is True
    assert events == ["paid", "delivered", "receipt"]


def test_pilot_postgres_only_one_global_order_and_private_status(
    pilot_config, postgres_url,
):
    store = PostgresLiveOrderLedger(postgres_url)
    owner = live_checkout.owner_ref_for_email(EMAIL)
    first_nonce = str(uuid4())
    order_id, pay_url = store.reserve_checkout(
        owner_ref=owner, verified_email=EMAIL, plan_id="30",
        idempotency_key=first_nonce, pilot=True,
    )
    assert order_id.startswith("vainah_live_")
    assert pay_url is None
    assert store.is_live_pilot_order(order_id) is True
    status = store.live_pilot_status()
    assert status["pilot_order_exists"] is True
    assert status["payment_state"] == "reserved"
    assert status["access_email_sent"] is False
    assert EMAIL not in str(status)
    assert "subscription" not in str(status)
    with pytest.raises(LiveLedgerError, match="LIVE_CHECKOUT_RECONCILIATION_REQUIRED"):
        store.reserve_checkout(
            owner_ref=owner, verified_email=EMAIL, plan_id="30",
            idempotency_key=first_nonce, pilot=True,
        )
    with pytest.raises(LiveLedgerError, match="LIVE_PILOT_ALREADY_RESERVED"):
        store.reserve_checkout(
            owner_ref=owner, verified_email=EMAIL, plan_id="30",
            idempotency_key=str(uuid4()), pilot=True,
        )
    # Public production reservations remain an entirely different gate.
    ordinary, _ = store.reserve_checkout(
        owner_ref=owner, verified_email=EMAIL, plan_id="30",
        idempotency_key=str(uuid4()),
    )
    assert store.is_live_pilot_order(ordinary) is False
    with psycopg.connect(postgres_url) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM vainah_live_orders WHERE is_pilot = TRUE",
        ).fetchone()[0]
    assert count == 1


def test_concurrent_pilot_reservation_is_still_globally_once(
    pilot_config, postgres_url,
):
    owner = live_checkout.owner_ref_for_email(EMAIL)
    def reserve(_):
        store = PostgresLiveOrderLedger(postgres_url)
        try:
            order, _url = store.reserve_checkout(
                owner_ref=owner, verified_email=EMAIL, plan_id="30",
                idempotency_key=str(uuid4()), pilot=True,
            )
            return ("ok", order)
        except LiveLedgerError as exc:
            return ("blocked", str(exc))

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(reserve, range(3)))
    assert sum(result[0] == "ok" for result in results) == 1
    assert all(result[1] == "LIVE_PILOT_ALREADY_RESERVED"
               for result in results if result[0] == "blocked")


def test_read_only_operator_status_needs_both_tokens(pilot_config, monkeypatch):
    class FakeLedger:
        def live_pilot_status(self):
            return {
                "pilot_order_exists": True, "payment_state": "paid",
                "delivery_state": "delivered", "access_email_sent": True,
            }
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted/test")
    monkeypatch.setattr(live_checkout, "_ledger", FakeLedger)
    with TestClient(app, base_url=ORIGIN) as client:
        path = "/api/shop/operator/live-pilot/status"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={
            "X-Sandbox-Token": SANDBOX_OPERATOR,
        }).status_code == 401
        r = client.get(path, headers=pilot_headers())
        assert r.status_code == 200, r.text
        assert r.json()["pilot_order_exists"] is True
        assert r.json()["access_email_sent"] is True
        assert PILOT_OPERATOR not in r.text
        assert EMAIL not in r.text
