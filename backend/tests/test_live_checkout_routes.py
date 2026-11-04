"""Production route contract checks: all provider responses are mocked.

Never performs real RollyPay charges, H1Cloud writes or sends emails.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vainah import live_checkout
from vainah.main import app
from vainah.production_contracts import (
    LiveOrderContract,
    verify_live_paid_event,
)

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
ORDER = "vainah_live_" + "a" * 32
EMAIL = "owner@example.com"
PAY_URL = "https://pay.rollypay.io/pay/paidurl12345"
PAYMENT_ID = "pay_123456789abcd"
NONCE = "123e4567-e89b-42d3-a456-426614174000"
SIGNATURE_KEY = "test-live-webhook-key-" + "x" * 32


@pytest.fixture
def simulated_production(monkeypatch):
    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    monkeypatch.setattr(live_checkout, "current_email", lambda _request: EMAIL)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "owner-secret-" + "x" * 40)
    monkeypatch.setenv("ROLLYPAY_API_KEY", "fake-test-gateway-secret")
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", SIGNATURE_KEY)


def test_live_checkout_disabled_by_default(monkeypatch):
    for flag in (
        "VAINAH_LIVE_CHECKOUT_ENABLED", "VAINAH_MERCHANT_APPROVED",
        "VAINAH_H1_WRITE_CONTRACT_APPROVED",
        "VAINAH_LIVE_FULFILLMENT_APPROVED",
        "VAINAH_LIVE_CUSTOMER_ACCESS_ENABLED",
    ):
        monkeypatch.delenv(flag, raising=False)
    assert live_checkout.live_ready() is False
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/shop/checkout",
            headers={"Origin": ORIGIN, "Idempotency-Key": NONCE},
            json={"plan": "30"},
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "LIVE_CHECKOUT_NOT_READY"


def test_checkout_requires_verified_email_origin_and_nonce(
    simulated_production, monkeypatch
):
    with TestClient(app, base_url=ORIGIN) as client:
        missing_origin = client.post(
            "/api/shop/checkout",
            headers={"Idempotency-Key": NONCE},
            json={"plan": "30"},
        )
        assert missing_origin.status_code == 403
        missing_nonce = client.post(
            "/api/shop/checkout", headers={"Origin": ORIGIN},
            json={"plan": "30"},
        )
        assert missing_nonce.status_code == 422
        invalid_nonce = client.post(
            "/api/shop/checkout",
            headers={"Origin": ORIGIN, "Idempotency-Key": "123"},
            json={"plan": "30"},
        )
        assert invalid_nonce.status_code == 422
        monkeypatch.setattr(live_checkout, "current_email", lambda _: None)
        no_email = client.post(
            "/api/shop/checkout",
            headers={"Origin": ORIGIN, "Idempotency-Key": NONCE},
            json={"plan": "30"},
        )
        assert no_email.status_code == 401


def test_hosted_payment_preserves_idempotent_order(simulated_production, monkeypatch):
    class FakeLedger:
        def __init__(self):
            self.saved = []
            self.reservations = []

        def reserve_checkout(self, **kwargs):
            self.reservations.append(kwargs)
            if len(self.reservations) == 1:
                return ORDER, None
            return ORDER, PAY_URL

        def attach_hosted_invoice(self, **kwargs):
            self.saved.append(kwargs)
            return True

    ledger = FakeLedger()
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    provider_calls = []

    async def fake_invoice(**kwargs):
        provider_calls.append(kwargs)
        return SimpleNamespace(
            order_id=ORDER, payment_id=PAYMENT_ID, pay_url=PAY_URL
        )

    monkeypatch.setattr(live_checkout, "create_hosted_live_invoice", fake_invoice)
    with TestClient(app, base_url=ORIGIN) as client:
        for _ in range(2):
            response = client.post(
                "/api/shop/checkout",
                headers={"Origin": ORIGIN, "Idempotency-Key": NONCE},
                json={"plan": "30"},
            )
            assert response.status_code == 200
            assert response.json()["pay_url"] == PAY_URL
            assert response.json()["order_id"] == ORDER
    assert len(provider_calls) == 1
    assert len(ledger.saved) == 1
    assert len(ledger.reservations) == 2
    assert ledger.reservations[0]["verified_email"] == EMAIL
    assert ledger.reservations[0]["idempotency_key"] == NONCE
    assert ledger.saved[0]["payment_id"] == PAYMENT_ID
    assert provider_calls[0]["verified_merchant_approved"] is True
    assert provider_calls[0]["verified_h1_fulfillment"] is True


def _event() -> tuple[bytes, str, str]:
    data = {
        "event_type": "payment.paid", "status": "paid",
        "order_id": ORDER, "payment_id": PAYMENT_ID,
        "amount": "99.00", "currency": "RUB",
    }
    raw = json.dumps(data, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SIGNATURE_KEY.encode(), timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, timestamp, signature


def test_signed_paid_webhook_once_and_invalid_signature(
    simulated_production, monkeypatch
):
    order = LiveOrderContract(
        ORDER, "30", live_checkout.owner_ref_for_email(EMAIL), PAYMENT_ID,
    )
    class FakeLedger:
        def __init__(self):
            self.paid = 0

        def record_signed_paid(self, *, raw_body, timestamp, signature, secret):
            assert verify_live_paid_event(
                raw_body, timestamp=timestamp, signature=signature,
                signing_secret=secret, order=order,
            )
            self.paid += 1
            return True

    ledger = FakeLedger()
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    delivery_calls = []

    async def fake_delivery(**kwargs):
        delivery_calls.append(kwargs)
        return (
            {"status": "delivered", "vpn_delivered": True}
            if len(delivery_calls) == 1
            else {"status": "not_claimable", "vpn_delivered": False}
        )

    monkeypatch.setattr(
        live_checkout, "fulfill_paid_order_once", fake_delivery,
    )
    raw, timestamp, signature = _event()
    headers = {
        "X-Test-Mode": "false", "X-Timestamp": timestamp,
        "X-Signature": signature, "Content-Type": "application/json",
    }
    with TestClient(app, base_url=ORIGIN) as client:
        bad = client.post(
            "/api/shop/webhooks/rollypay", content=raw,
            headers={**headers, "X-Signature": "0" * 64},
        )
        assert bad.status_code == 403
        for index in (1, 2):
            valid = client.post(
                "/api/shop/webhooks/rollypay",
                content=raw, headers=headers,
            )
            assert valid.status_code == 200
            assert valid.json()["ok"] is True
            assert valid.json()["vpn_delivered"] is (index == 1)
    assert ledger.paid == 2
    assert len(delivery_calls) == 2


def test_customer_unpaid_link_is_not_created_from_fake_webhook(
    simulated_production, monkeypatch
):
    from vainah.live_ledger import LiveLedgerError

    class FakeLedger:
        def record_signed_paid(self, **_kwargs):
            raise LiveLedgerError("LIVE_ORDER_UNKNOWN")

    monkeypatch.setattr(live_checkout, "_ledger", FakeLedger)
    raw, timestamp, signature = _event()
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/shop/webhooks/rollypay",
            content=raw,
            headers={"X-Test-Mode": "false", "X-Timestamp": timestamp,
                     "X-Signature": signature},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "LIVE_ORDER_UNKNOWN"
