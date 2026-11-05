"""Customer-only public checkout intent checks; no money or H1 writes."""
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from vainah import live_checkout
from vainah.live_ledger import PostgresLiveOrderLedger
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
EMAIL = "buyer@example.com"


@pytest.fixture
def account(monkeypatch, postgres_url):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-key-only-" + "k" * 48)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("VAINAH_LIVE_CUSTOMER_ACCESS_ENABLED", "enabled")
    monkeypatch.delenv("VAINAH_LIVE_CHECKOUT_ENABLED", raising=False)
    monkeypatch.setattr(live_checkout, "current_email", lambda _req: EMAIL)
    return PostgresLiveOrderLedger(postgres_url)


def headers(key):
    return {"Idempotency-Key": key, "Origin": ORIGIN}


def test_missing_intent_can_be_read_without_enabling_public_sales(account):
    key = str(uuid4())
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/shop/config").json()["checkout_ready"] is False
        response = client.get("/api/shop/checkout-intent?plan=30",
                              headers=headers(key))
        assert response.status_code == 200
        assert response.json() == {"found": False, "renewal_ready": False}


def test_only_delivered_signed_paid_intent_can_rotate_after_success(
    account, postgres_url,
):
    owner = live_checkout.owner_ref_for_email(EMAIL)
    key = str(uuid4())
    order_id, url = account.reserve_checkout(
        owner_ref=owner, verified_email=EMAIL, plan_id="30",
        idempotency_key=key,
    )
    assert url is None
    with TestClient(app, base_url=ORIGIN) as client:
        endpoint = "/api/shop/checkout-intent?plan=30"
        def read():
            response = client.get(endpoint, headers=headers(key))
            assert response.status_code == 200
            return response.json()
        assert read() == {
            "found": True, "payment_state": "reserved",
            "delivery_state": "pending", "renewal_ready": False,
        }
        with psycopg.connect(postgres_url) as conn:
            conn.execute("""
                UPDATE vainah_live_orders SET
                    payment_state = 'created' WHERE order_id = %s
            """, (order_id,))
        assert read()["renewal_ready"] is False
        with psycopg.connect(postgres_url) as conn:
            conn.execute("""
                UPDATE vainah_live_orders SET
                    payment_state = 'paid', webhook_at = now()
                WHERE order_id = %s
            """, (order_id,))
        assert read()["renewal_ready"] is False
        with psycopg.connect(postgres_url) as conn:
            conn.execute("""
                UPDATE vainah_live_orders SET
                    delivery_state = 'delivered', delivered_at = now()
                WHERE order_id = %s
            """, (order_id,))
        assert read() == {
            "found": True, "payment_state": "paid",
            "delivery_state": "delivered", "renewal_ready": True,
        }
        assert client.get("/api/shop/checkout-intent?plan=60",
                          headers=headers(key)).json()["found"] is False


def test_never_exposes_other_buyer_intent(account, monkeypatch):
    key = str(uuid4())
    owner = live_checkout.owner_ref_for_email(EMAIL)
    account.reserve_checkout(
        owner_ref=owner, verified_email=EMAIL, plan_id="30",
        idempotency_key=key,
    )
    monkeypatch.setattr(live_checkout, "current_email", lambda _req: "other@example.com")
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/shop/checkout-intent?plan=30",
                              headers=headers(key))
        assert response.status_code == 200
        assert response.json() == {"found": False, "renewal_ready": False}


@pytest.mark.parametrize("plan", ["pilot-1d", "unknown", ""])
def test_public_intent_rejects_private_or_unknown_plans(account, plan):
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/shop/checkout-intent",
            params={"plan": plan}, headers=headers(str(uuid4())))
        assert response.status_code == 422


def test_intent_status_requires_verified_email_and_uuid(account, monkeypatch):
    with TestClient(app, base_url=ORIGIN) as client:
        missing = client.get("/api/shop/checkout-intent?plan=30")
        assert missing.status_code == 422
        malformed = client.get("/api/shop/checkout-intent?plan=30",
                               headers=headers("not-a-uuid"))
        assert malformed.status_code == 422
        monkeypatch.setattr(live_checkout, "current_email", lambda _req: None)
        login = client.get("/api/shop/checkout-intent?plan=30",
                           headers=headers(str(uuid4())))
        assert login.status_code == 401


def test_operator_pilot_intent_is_not_public(account):
    key = str(uuid4())
    owner = live_checkout.owner_ref_for_email(EMAIL)
    account.reserve_checkout(
        owner_ref=owner, verified_email=EMAIL, plan_id="30",
        idempotency_key=key, pilot=True,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/shop/checkout-intent?plan=30",
                              headers=headers(key))
        assert response.status_code == 200
        assert response.json() == {"found": False, "renewal_ready": False}
