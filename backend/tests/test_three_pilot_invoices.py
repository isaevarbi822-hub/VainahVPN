"""Two sequential 10-RUB invoices plus the immutable original 99-RUB pilot."""
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
EMAIL = "private-three-invoices@example.test"
OPERATOR = "operator-" + "s" * 40
PILOT = "pilot-" + "p" * 40


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "s" * 48)
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", OPERATOR)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", PILOT)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_EMAIL", EMAIL)
    for key, value in {
        "VAINAH_LIVE_PILOT_ENABLED": "enabled",
        "VAINAH_LIVE_DISCOUNT_PILOT_ENABLED": "enabled",
        "VAINAH_MERCHANT_APPROVED": "approved",
        "VAINAH_H1_WRITE_CONTRACT_APPROVED": "approved",
        "VAINAH_LIVE_FULFILLMENT_APPROVED": "approved",
        "ROLLYPAY_API_KEY": "k" * 40,
        "ROLLYPAY_SIGNING_SECRET": "h" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(live_checkout, "_live_infrastructure_ready", lambda: True)
    monkeypatch.setattr(live_checkout, "current_email", lambda _request: EMAIL)


def headers():
    return {"Origin": ORIGIN, "X-Sandbox-Token": OPERATOR,
            "X-Live-Pilot-Token": PILOT}


def test_two_discount_slots_cannot_exceed_lifetime_limit(configured, postgres_url):
    store = PostgresLiveOrderLedger(postgres_url)
    owner = live_checkout.owner_ref_for_email(EMAIL)
    original, _ = store.reserve_checkout(
        owner_ref=owner, verified_email=EMAIL, plan_id="30",
        idempotency_key=str(uuid4()), pilot=True,
    )
    issued = []
    for index in range(2):
        order, link = store.reserve_checkout(
            owner_ref=owner, verified_email=EMAIL, plan_id="pilot-1d",
            idempotency_key=str(uuid4()), discounted_pilot=True,
        )
        assert link is None
        assert store.is_live_pilot_order(order) is True
        assert order != original
        issued.append(order)
        state = store.discount_pilot_state()
        assert state["discount_order_count"] == index + 1
        assert state["discount_remaining"] == 1 - index
    assert len(set(issued)) == 2
    with pytest.raises(LiveLedgerError, match="LIVE_DISCOUNT_PILOT_LIMIT_REACHED"):
        store.reserve_checkout(
            owner_ref=owner, verified_email=EMAIL, plan_id="pilot-1d",
            idempotency_key=str(uuid4()), discounted_pilot=True,
        )
    assert store.is_live_pilot_order(original) is True
    with psycopg.connect(postgres_url) as conn:
        rows = conn.execute("""
            SELECT plan_id, amount_rub, is_pilot, is_discount_pilot
            FROM vainah_live_orders ORDER BY created_at
        """).fetchall()
    assert len(rows) == 3
    assert sum(row[2] for row in rows) == 1
    assert sum(row[3] for row in rows) == 2
    assert all(str(row[1]) == "10.00" for row in rows if row[3])


def test_concurrent_discount_reservations_have_exactly_two_slots(
    configured, postgres_url,
):
    owner = live_checkout.owner_ref_for_email(EMAIL)

    def reserve(_):
        store = PostgresLiveOrderLedger(postgres_url)
        try:
            order_id, _ = store.reserve_checkout(
                owner_ref=owner, verified_email=EMAIL, plan_id="pilot-1d",
                idempotency_key=str(uuid4()), discounted_pilot=True,
            )
            return ("created", order_id)
        except LiveLedgerError as exc:
            return ("blocked", str(exc))

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(reserve, range(3)))
    assert sum(result[0] == "created" for result in results) == 2
    assert sum(result[0] == "blocked" for result in results) == 1
    assert any("LIVE_DISCOUNT_PILOT_LIMIT_REACHED" in result[1]
               for result in results if result[0] == "blocked")


def test_second_discount_allowed_only_after_paid_delivery(configured, monkeypatch):
    class Ledger:
        def discount_pilot_state(self):
            return {"discount_order_exists": True,
                    "discount_order_count": 1,
                    "discount_remaining": 1,
                    "discount_payment_state": "paid",
                    "discount_delivery_state": "delivered"}
        def latest_discount_payment_for_verification(self, owner):
            return {"order_id": "vainah_live_" + "0"*32,
                    "payment_id": "pay_previous001",
                    "plan_id": "pilot-1d", "amount_rub": "10.00",
                    "payment_state": "paid", "delivery_state": "delivered"}
    monkeypatch.setattr(live_checkout, "_ledger", Ledger)
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get("/api/shop/operator/live-pilot/discount-status",
                            headers=headers())
        assert result.status_code == 200
        assert result.json()["discount_checkout_ready"] is True
        assert result.json()["discount_remaining"] == 1


@pytest.mark.parametrize("count,expected_reason", [
    (2, "DISCOUNT_PILOT_LIMIT_REACHED"),
    (1, "DISCOUNT_PILOT_UNVERIFIED"),
])
def test_discount_fail_closed_at_cap_or_unissued_order(
    configured, monkeypatch, count, expected_reason,
):
    class Ledger:
        def discount_pilot_state(self):
            return {"discount_order_count": count,
                    "discount_order_exists": True,
                    "discount_remaining": max(0, 2-count)}
        def latest_discount_payment_for_verification(self, owner):
            return {"order_id": "vainah_live_" + "0"*32,
                    "payment_id": None,
                    "plan_id": "pilot-1d", "amount_rub": "10.00",
                    "payment_state": "reserved", "delivery_state": "pending"}
    monkeypatch.setattr(live_checkout, "_ledger", Ledger)
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get("/api/shop/operator/live-pilot/discount-status",
                            headers=headers())
        assert result.status_code == 200
        assert result.json()["discount_checkout_ready"] is False
        assert result.json()["reason"] == expected_reason


def test_second_discount_requires_provider_closed_if_unpaid(configured, monkeypatch):
    order = "vainah_live_" + uuid4().hex
    class Ledger:
        def discount_pilot_state(self):
            return {"discount_order_count": 1, "discount_order_exists": True}
        def latest_discount_payment_for_verification(self, owner):
            return {"order_id": order, "payment_id": "pay_previous001",
                    "plan_id": "pilot-1d", "amount_rub": "10.00",
                    "payment_state": "created", "delivery_state": "pending"}
    class Provider:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, *, headers):
            return SimpleNamespace(
                status_code=200, content=b"{}",
                json=lambda: {"order_id": order, "payment_id": "pay_previous001",
                              "amount": "10.00", "payment_currency": "RUB",
                              "status": "expired", "test": False},
            )
    monkeypatch.setattr(live_checkout, "_ledger", Ledger)
    monkeypatch.setattr(live_checkout.httpx, "AsyncClient", Provider)
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get("/api/shop/operator/live-pilot/discount-status",
                            headers=headers())
        assert result.status_code == 200
        assert result.json()["discount_checkout_ready"] is True
        assert result.json()["discount_order_count"] == 1
