"""Read-only staff operations, with real disposable PostgreSQL and no live calls."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from vainah import live_checkout
from vainah.live_ledger import (
    LiveLedgerError,
    PostgresLiveOrderLedger,
    seal_live_secret,
)
from vainah.main import app


ORIGIN = "https://vainahvpn-python-preview.onrender.com"
EMAIL = "operator-health@example.test"
TOKEN = "s" * 48
PILOT_TOKEN = "p" * 48
OWNER = "v1_" + "a" * 64


@pytest.fixture
def operator(monkeypatch, postgres_url):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "k" * 48)
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", TOKEN)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", PILOT_TOKEN)
    monkeypatch.setenv("VAINAH_LIVE_PILOT_EMAIL", EMAIL)
    monkeypatch.setattr(live_checkout, "current_email", lambda _req: EMAIL)
    return PostgresLiveOrderLedger(postgres_url)


def headers(**custom):
    return {"Origin": ORIGIN, "X-Sandbox-Token": TOKEN,
            "X-Live-Pilot-Token": PILOT_TOKEN, **custom}


def add_order(store, *, payment, delivery, expires=None, sent=False,
              owner=OWNER, age_days=0):
    order_id = "vainah_live_" + uuid4().hex
    with psycopg.connect(store._database_url) as conn, conn.cursor() as cur:
        store._schema(cur)
        cur.execute("""
            INSERT INTO vainah_live_orders
               (order_id, owner_ref, plan_id, amount_rub,
                receipt_email_cipher, payment_state, delivery_state,
                h1_expires_at, access_email_sent_at, created_at, delivered_at)
            VALUES (%s, %s, '30', 99, %s, %s, %s, %s,
                    CASE WHEN %s THEN now() ELSE NULL END,
                    now() - (%s * INTERVAL '1 day'), now())
        """, (order_id, owner, seal_live_secret("secret-customer@example.com"),
              payment, delivery, expires, sent, age_days))
    return order_id


def test_dashboard_summary_counts_and_never_exposes_private_fields(operator):
    add_order(operator, payment="paid", delivery="delivered",
              expires=datetime.now(UTC) + timedelta(hours=12))
    add_order(operator, payment="paid", delivery="delivered",
              expires=datetime.now(UTC) + timedelta(days=12), sent=True,
              owner="v1_" + "b" * 64)
    add_order(operator, payment="paid", delivery="manual_review")
    add_order(operator, payment="created", delivery="pending", age_days=3)
    add_order(operator, payment="paid", delivery="pending")
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/shop/operator/operations/summary",
                              headers=headers())
    assert response.status_code == 200
    data = response.json()
    assert data["total_orders"] == 5
    assert data["paid_delivered"] == 2
    assert data["paid_awaiting_delivery"] == 1
    assert data["manual_review"] == 1
    assert data["paid_delivered_email_not_sent"] == 1
    assert data["unpaid_older_than_24h"] == 1
    assert data["expiry_snapshot_48h"] == 1
    assert data["expiry_snapshot_7d"] == 1
    assert data["expiry_is_live_h1"] is False
    assert len(data["recent"]) == 5
    body = response.text
    for forbidden in ("secret-customer", "subscription_url", "payment_id",
                      "receipt_email_cipher", "owner_ref", "checkout_nonce_hash"):
        assert forbidden not in body


def test_operator_requires_both_tokens_and_allowlisted_session(operator, monkeypatch):
    url = "/api/shop/operator/operations/summary"
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get(url).status_code == 401
        assert client.get(url, headers=headers(**{
            "X-Live-Pilot-Token": "wrong"
        })).status_code == 401
        assert client.get(url, headers=headers(**{
            "X-Sandbox-Token": "wrong"
        })).status_code == 401
        monkeypatch.setattr(live_checkout, "current_email", lambda _req: None)
        assert client.get(url, headers=headers()).status_code == 401
        monkeypatch.setattr(live_checkout, "current_email",
                            lambda _req: "unknown@example.test")
        assert client.get(url, headers=headers()).status_code == 403
        monkeypatch.setattr(live_checkout, "current_email", lambda _req: EMAIL)
        assert client.get(url, headers=headers()).status_code == 200


def test_h1_expiry_saved_only_after_confirmed_paid_claim(operator):
    order_id = "vainah_live_" + uuid4().hex
    with psycopg.connect(operator._database_url) as conn, conn.cursor() as cur:
        operator._schema(cur)
        cur.execute("""
            INSERT INTO vainah_live_orders (
                order_id, owner_ref, plan_id, amount_rub,
                receipt_email_cipher, payment_state, delivery_state, webhook_at
            ) VALUES (%s, %s, '30', 99, %s, 'paid', 'claimed', now())
        """, (order_id, OWNER, seal_live_secret("a@example.test")))
    expires = int((datetime.now(UTC) + timedelta(days=3)).timestamp())
    with pytest.raises(LiveLedgerError, match="LIVE_H1_EXPIRY_INVALID"):
        operator.mark_delivered(order_id=order_id,
                                subscription_url="https://example.net/subscription",
                                panel_confirmed=True, expires_at=True)
    assert operator.mark_delivered(
        order_id=order_id,
        subscription_url="https://example.net/subscription",
        panel_confirmed=True, expires_at=expires,
    ) is True
    with psycopg.connect(operator._database_url) as conn:
        stored = conn.execute("""
            SELECT h1_expires_at, delivery_state FROM vainah_live_orders
            WHERE order_id = %s
        """, (order_id,)).fetchone()
    assert stored[0] == datetime.fromtimestamp(expires, UTC)
    assert stored[1] == "delivered"


def test_expiry_uses_latest_verified_snapshot_per_owner(operator):
    owner = "v1_" + "c" * 64
    add_order(operator, payment="paid", delivery="delivered",
              expires=datetime.now(UTC) + timedelta(days=1), owner=owner,
              age_days=5)
    add_order(operator, payment="paid", delivery="delivered",
              expires=datetime.now(UTC) + timedelta(days=30), owner=owner)
    data = operator.operator_health_summary()
    assert data["expiry_snapshot_48h"] == 0
    assert data["expiry_snapshot_7d"] == 0
