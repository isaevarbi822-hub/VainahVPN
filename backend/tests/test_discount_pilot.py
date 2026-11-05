"""Restricted 10 RUB / 1-day pilot regression checks (never charge the provider)."""
from uuid import uuid4
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vainah import live_checkout
from vainah.billing import get_plan, public_plans
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
EMAIL = "private-pilot@example.test"
OPERATOR = "operator-" + "s"*40
PILOT = "pilot-" + "p"*40


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "s"*48)
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", OPERATOR)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", PILOT)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_EMAIL", EMAIL)
    for key, value in {
        "VAINAH_LIVE_PILOT_ENABLED": "enabled",
        "VAINAH_LIVE_DISCOUNT_PILOT_ENABLED": "enabled",
        "VAINAH_MERCHANT_APPROVED": "approved",
        "VAINAH_H1_WRITE_CONTRACT_APPROVED": "approved",
        "VAINAH_LIVE_FULFILLMENT_APPROVED": "approved",
        "ROLLYPAY_API_KEY": "k"*40,
        "ROLLYPAY_SIGNING_SECRET": "h"*40,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(live_checkout, "_live_infrastructure_ready", lambda: True)
    monkeypatch.setattr(live_checkout, "current_email", lambda request: EMAIL)


def headers():
    return {"Origin": ORIGIN, "X-Sandbox-Token": OPERATOR,
            "X-Live-Pilot-Token": PILOT,
            "Idempotency-Key": str(uuid4())}


def test_discount_is_one_day_and_not_in_public_catalog(configured):
    assert get_plan("pilot-1d")["kopeks"] == 1000
    assert get_plan("pilot-1d")["days"] == 1
    assert all(p["id"] != "pilot-1d" for p in public_plans())
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post("/api/shop/checkout", json={"plan": "pilot-1d"},
                               headers=headers())
        assert response.status_code == 503


@pytest.mark.parametrize("status,ready", [
    ("expired", True), ("canceled", True), ("created", False), ("paid", False),
])
def test_original_provider_state_verification(configured, monkeypatch, status, ready):
    order = "vainah_live_" + uuid4().hex

    class Ledger:
        def discount_pilot_state(self):
            return {"discount_order_exists": False}
        def original_pilot_payment_for_verification(self, owner):
            return {"order_id": order, "payment_id": "pay_original00001",
                    "plan_id": "30", "amount_rub": "99.00",
                    "payment_state": "created"}

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, *, headers):
            assert url.endswith("/pay_original00001")
            return SimpleNamespace(status_code=200, content=b"{}",
                json=lambda: {"order_id": order, "payment_id": "pay_original00001",
                              "amount": "99.00", "payment_currency": "RUB",
                              "status": status, "test": False})

    monkeypatch.setattr(live_checkout, "_ledger", Ledger)
    monkeypatch.setattr(live_checkout.httpx, "AsyncClient", FakeClient)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/shop/operator/live-pilot/discount-status",
                              headers=headers())
        assert response.status_code == 200
        assert response.json()["discount_checkout_ready"] is ready


def test_discount_locked_without_operator_opt_in(configured, monkeypatch):
    monkeypatch.delenv("VAINAH_LIVE_DISCOUNT_PILOT_ENABLED")
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post("/api/shop/operator/live-pilot/discount-checkout",
                               json={"plan":"pilot-1d"},headers=headers())
        assert response.status_code == 503
        assert response.json()["detail"] == "DISCOUNT_PILOT_DISABLED"
