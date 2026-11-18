"""Platega contract tests; never contact a real payment provider."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from vainah import platega
from vainah.live_ledger import LiveLedgerError, PostgresLiveOrderLedger
from vainah.main import app

MERCHANT = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
PAYMENT = "3fa85f64-5717-4562-b3fc-2c963f66afa7"
ORDER = "vainah_live_" + "a" * 32
SECRET = "local-only-test-platega-secret-at-least-16"


def setup_gateway(monkeypatch):
    monkeypatch.setenv("PLATEGA_MERCHANT_ID", MERCHANT)
    monkeypatch.setenv("PLATEGA_SECRET", SECRET)
    monkeypatch.setenv("PLATEGA_PAYMENT_METHOD", "2")
    monkeypatch.setenv("PLATEGA_ENABLED", "enabled")
    monkeypatch.setattr(platega, "live_ready", lambda: True)


def test_strict_redirect_and_exact_amount():
    assert platega.safe_pay_url("https://pay.platega.io?qrsbp") == (
        "https://pay.platega.io?qrsbp"
    )
    for url in [
        "http://pay.platega.io?qrsbp",
        "https://pay.platega.io.evil.example?qrsbp",
        "https://evil.example@pay.platega.io?qrsbp",
        "https://pay.platega.io/path#fragment",
        "https://pay.platega.io/../checkout",
    ]:
        with pytest.raises(ValueError):
            platega.safe_pay_url(url)
    assert platega.exact_rub_amount(149, "149.00")
    assert not platega.exact_rub_amount(True, "1.00")
    assert not platega.exact_rub_amount("148.99", "149.00")


def test_gateway_requires_separate_explicit_enable(monkeypatch):
    setup_gateway(monkeypatch)
    assert platega.ready() is True
    monkeypatch.delenv("PLATEGA_ENABLED")
    assert platega.ready() is False
    monkeypatch.setenv("PLATEGA_ENABLED", "enabled")
    monkeypatch.setenv("PLATEGA_SECRET", "")
    monkeypatch.delenv("PLATEGA_API_KEY", raising=False)
    monkeypatch.delenv("PLATEGA_X_SECRET", raising=False)
    assert platega.ready() is False


def test_checkout_reserves_immutable_provider_and_uses_verified_price(monkeypatch):
    setup_gateway(monkeypatch)
    monkeypatch.setattr(platega, "require_same_origin", lambda _request: None)
    monkeypatch.setattr(platega, "current_email", lambda _request: "user@example.com")
    monkeypatch.setattr(
        platega, "owner_ref_for_email", lambda _email: "v1_" + "a" * 64,
    )
    captured = {}

    class Ledger:
        def reserve_checkout(self, **kwargs):
            captured["reserve"] = kwargs
            return ORDER, None

        def attach_hosted_invoice(self, **kwargs):
            captured["attach"] = kwargs
            return True

    monkeypatch.setattr(platega, "_ledger", Ledger)

    async def fake_create(**kwargs):
        captured["create"] = kwargs
        return PAYMENT, "https://pay.platega.io?qrsbp"

    monkeypatch.setattr(platega, "_new_invoice", fake_create)
    with TestClient(app) as client:
        response = client.post(
            "/api/shop/checkout/platega",
            json={"plan": "30"},
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == 200, response.text
    assert response.json()["gateway"] == "platega"
    assert captured["reserve"]["gateway"] == "platega"
    assert captured["attach"]["gateway"] == "platega"
    assert captured["create"]["email"] == "user@example.com"
    assert captured["create"]["amount_rub"] > 0


def test_callback_needs_headers_before_any_read(monkeypatch):
    setup_gateway(monkeypatch)

    async def forbidden_get(_payment):
        raise AssertionError("Unauthenticated callback cannot query the gateway")

    monkeypatch.setattr(platega, "_provider_transaction", forbidden_get)
    with TestClient(app) as client:
        response = client.post("/api/shop/webhooks/platega", json={
            "id": PAYMENT, "payload": ORDER, "amount": 149,
            "currency": "RUB", "status": "CONFIRMED",
        })
    assert response.status_code == 403


def test_verified_callback_checks_amount_and_order_before_ledger(monkeypatch):
    setup_gateway(monkeypatch)

    async def wrong_order(_payment):
        return {
            "id": PAYMENT, "status": "CONFIRMED",
            "payload": "vainah_live_" + "b" * 32,
            "paymentDetails": {"amount": 149, "currency": "RUB"},
        }

    monkeypatch.setattr(platega, "_provider_transaction", wrong_order)
    monkeypatch.setattr(
        platega, "_ledger", lambda: pytest.fail("No order may be marked paid"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/shop/webhooks/platega",
            headers={"X-MerchantId": MERCHANT, "X-Secret": SECRET},
            json={
                "id": PAYMENT, "payload": ORDER,
                "amount": 149, "currency": "RUB", "status": "CONFIRMED",
            },
        )
    assert response.status_code == 400


def test_confirmed_callback_uses_only_verified_ledger_result(monkeypatch):
    setup_gateway(monkeypatch)
    seen = {}

    async def confirmed(_payment):
        return {
            "id": PAYMENT, "status": "CONFIRMED",
            "payload": ORDER,
            "paymentDetails": {"amount": 149, "currency": "RUB"},
        }

    class Ledger:
        def record_platega_verified(self, **kwargs):
            seen["ledger"] = kwargs
            return {"paid": True, "manual_review": False}

    async def delivery(**kwargs):
        seen["delivery"] = kwargs
        return {"vpn_delivered": False, "status": "manual_review"}

    monkeypatch.setattr(platega, "_provider_transaction", confirmed)
    monkeypatch.setattr(platega, "_ledger", Ledger)
    monkeypatch.setattr(platega, "fulfill_paid_order_once", delivery)
    with TestClient(app) as client:
        response = client.post(
            "/api/shop/webhooks/platega",
            headers={"X-MerchantId": MERCHANT, "X-Secret": SECRET},
            json={
                "id": PAYMENT, "payload": ORDER,
                "amount": 149, "currency": "RUB", "status": "CONFIRMED",
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["vpn_delivered"] is False
    assert seen["ledger"]["payment_id"] == PAYMENT
    assert seen["ledger"]["amount"] == 149
    assert seen["delivery"]["order_id"] == ORDER


@pytest.mark.skipif(
    not os.environ.get("VAINAH_TEST_DATABASE_URL"),
    reason="Test-only PostgreSQL required",
)
def test_platega_order_immutable_gateway_and_paid_idempotency(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-secret-" + "z" * 54)
    ledger = PostgresLiveOrderLedger(os.environ["VAINAH_TEST_DATABASE_URL"])
    order_id, old_url = ledger.reserve_checkout(
        owner_ref="v1_" + "d" * 64, verified_email="test-platega@example.com",
        plan_id="30", idempotency_key=str(uuid4()), gateway="platega",
    )
    assert old_url is None
    assert ledger.attach_hosted_invoice(
        order_id=order_id, payment_id=PAYMENT,
        pay_url="https://pay.platega.io?qrsbp", gateway="platega",
    )
    with pytest.raises(LiveLedgerError):
        ledger.record_platega_verified(
            order_id=order_id, payment_id=PAYMENT, amount="1.00",
            currency="RUB", status="CONFIRMED",
        )
    from vainah.billing import get_plan, price_rub

    cost = price_rub(get_plan("30"))
    first = ledger.record_platega_verified(
        order_id=order_id, payment_id=PAYMENT, amount=cost,
        currency="RUB", status="CONFIRMED",
    )
    again = ledger.record_platega_verified(
        order_id=order_id, payment_id=PAYMENT, amount=cost,
        currency="RUB", status="CONFIRMED",
    )
    assert first["paid"] is True
    assert again["paid"] is True
    assert ledger.delivery_snapshot(order_id)["payment_state"] == "paid"
