"""Live receipt outbox tests: disposable PostgreSQL, no real payments or H1."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException

from vainah import live_checkout, live_receipt
from vainah.live_ledger import PostgresLiveOrderLedger, seal_live_secret
from vainah.live_receipt import LiveReceiptError, send_paid_access_receipt_once


@pytest.fixture
def paid_order(postgres_url, monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-live-receipt-" + "e" * 40)
    order = "vainah_live_" + uuid4().hex
    ledger = PostgresLiveOrderLedger(postgres_url)
    with psycopg.connect(postgres_url) as conn, conn.cursor() as cur:
        ledger._schema(cur)
        cur.execute("""
            INSERT INTO vainah_live_orders
                (order_id, owner_ref, plan_id, amount_rub, payment_id,
                 receipt_email_cipher, subscription_cipher, payment_state,
                 delivery_state, webhook_at, delivered_at)
            VALUES (%s, %s, '30', 99, %s, %s, %s, 'paid',
                    'delivered', now(), now())
        """, (
            order, "v1_" + "a" * 64, "pay_" + uuid4().hex,
            seal_live_secret("buyer@example.com"),
            seal_live_secret("https://sub.example.com/private-access?x=1&y=2"),
        ))
    return ledger, order, postgres_url


def test_delivered_live_order_emails_link_only_once(paid_order, monkeypatch):
    ledger, order, database_url = paid_order
    sent = []

    async def fake_email(to, subject, body, **kwargs):
        sent.append((to, subject, body, kwargs))

    monkeypatch.setattr(live_receipt, "send_email", fake_email)
    first = asyncio.run(send_paid_access_receipt_once(ledger=ledger, order_id=order))
    second = asyncio.run(send_paid_access_receipt_once(ledger=ledger, order_id=order))
    assert first == {"status": "sent", "already_sent": False}
    assert second == {"status": "sent", "already_sent": True}
    assert len(sent) == 1
    assert sent[0][0] == "buyer@example.com"
    assert sent[0][3]["idempotency_key"] == "live-access/" + order
    assert 'href="https://sub.example.com/private-access?x=1&amp;y=2"' in sent[0][2]
    assert "ТЕСТОВЫЙ ЗАКАЗ" not in sent[0][2]
    with psycopg.connect(database_url) as conn:
        row = conn.execute("""
            SELECT access_email_sent_at, receipt_email_cipher, subscription_cipher
            FROM vainah_live_orders WHERE order_id = %s
        """, (order,)).fetchone()
    assert row[0] is not None
    assert "buyer@example.com" not in row[1]
    assert "private-access" not in row[2]


@pytest.mark.parametrize("alter", [
    "UPDATE vainah_live_orders SET payment_state = 'created' WHERE order_id = %s",
    "UPDATE vainah_live_orders SET delivery_state = 'pending' WHERE order_id = %s",
    "UPDATE vainah_live_orders SET webhook_at = NULL WHERE order_id = %s",
    "UPDATE vainah_live_orders SET subscription_cipher = NULL WHERE order_id = %s",
    "UPDATE vainah_live_orders SET payment_state = 'refunded', delivery_state = 'manual_review' WHERE order_id = %s",
])
def test_no_live_email_without_paid_signed_issued_entitlement(
    paid_order, monkeypatch, alter,
):
    ledger, order, url = paid_order
    seen = []

    async def fake_email(*args, **kwargs):
        seen.append((args, kwargs))

    monkeypatch.setattr(live_receipt, "send_email", fake_email)
    with psycopg.connect(url) as conn:
        conn.execute(alter, (order,))
    with pytest.raises(LiveReceiptError):
        asyncio.run(send_paid_access_receipt_once(ledger=ledger, order_id=order))
    assert not seen


def test_duplicate_callbacks_cannot_claim_email_concurrently(paid_order):
    ledger, order, _url = paid_order
    first_token = uuid4().hex
    second_token = uuid4().hex
    first = ledger.claim_paid_access_email(order, claim_token=first_token)
    assert first["status"] == "claimed"
    assert ledger.claim_paid_access_email(order, claim_token=second_token) == {
        "status": "in_progress",
    }
    assert ledger.finish_paid_access_email(order, claim_token=second_token) is False
    assert ledger.finish_paid_access_email(order, claim_token=first_token) is True
    assert ledger.claim_paid_access_email(order, claim_token=uuid4().hex) == {
        "status": "sent",
    }


def test_email_failure_does_not_claim_or_recreate_vpn(paid_order, monkeypatch):
    ledger, order, _url = paid_order
    calls = []
    async def flaky(*args, **kwargs):
        calls.append("attempt")
        if len(calls) == 1:
            raise HTTPException(503, "RESEND_TEMPORARILY_UNAVAILABLE")

    monkeypatch.setattr(live_receipt, "send_email", flaky)
    with pytest.raises(LiveReceiptError):
        asyncio.run(send_paid_access_receipt_once(ledger=ledger, order_id=order))
    assert asyncio.run(send_paid_access_receipt_once(ledger=ledger, order_id=order)) == {
        "status": "sent", "already_sent": False,
    }
    assert calls == ["attempt", "attempt"]


def test_html_injection_or_broken_url_is_never_emailed(paid_order, monkeypatch):
    ledger, order, database_url = paid_order
    with psycopg.connect(database_url) as conn:
        conn.execute("""
            UPDATE vainah_live_orders SET subscription_cipher = %s
            WHERE order_id = %s
        """, (seal_live_secret("javascript:alert(1)"), order))
    sent = []

    async def fake_email(*args, **kwargs):
        sent.append((args, kwargs))

    monkeypatch.setattr(live_receipt, "send_email", fake_email)
    with pytest.raises(LiveReceiptError):
        asyncio.run(send_paid_access_receipt_once(ledger=ledger, order_id=order))
    assert sent == []


def test_verified_paid_live_callback_triggers_receipt_but_not_for_unissued(
    monkeypatch,
):
    """Mock all payment/H1/network side effects; assert secure routing only."""
    secret = "test-only-live-webhook-" + "h" * 32
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", secret)
    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    order_id = "vainah_live_" + uuid4().hex
    event = {
        "event_type": "payment.paid", "order_id": order_id, "status": "paid",
        "test": False,
    }
    raw = json.dumps(event).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256,
    ).hexdigest()

    class FakeLedger:
        def record_signed_paid(self, **_kwargs):
            return True

    fake_ledger = FakeLedger()
    monkeypatch.setattr(live_checkout, "_ledger", lambda: fake_ledger)
    state = {"status": "delivered", "vpn_delivered": True}
    issued = []
    emails = []

    async def fake_provision(**kwargs):
        issued.append(kwargs["order_id"])
        return state.copy()

    async def fake_receipt(**kwargs):
        emails.append(kwargs["order_id"])
        return {"status": "sent"}

    monkeypatch.setattr(live_checkout, "fulfill_paid_order_once", fake_provision)
    monkeypatch.setattr(live_checkout, "send_paid_access_receipt_once", fake_receipt)
    delivered = asyncio.run(live_checkout.handle_live_paid_webhook(
        raw=raw, timestamp=timestamp, signature=signature,
    ))
    assert delivered["vpn_delivered"] is True
    assert emails == [order_id]
    state.update(status="manual_review", vpn_delivered=False)
    blocked = asyncio.run(live_checkout.handle_live_paid_webhook(
        raw=raw, timestamp=timestamp, signature=signature,
    ))
    assert blocked["vpn_delivered"] is False
    assert emails == [order_id]
    assert len(issued) == 2


def test_failed_live_email_retries_webhook_without_exposing_link(monkeypatch):
    from vainah.live_receipt import LiveReceiptError

    secret = "test-only-live-webhook-" + "k" * 32
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", secret)
    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    order_id = "vainah_live_" + uuid4().hex
    raw = json.dumps({
        "event_type": "payment.paid", "order_id": order_id, "test": False,
    }).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256,
    ).hexdigest()

    class FakeLedger:
        def record_signed_paid(self, **_kwargs):
            return True

    monkeypatch.setattr(live_checkout, "_ledger", FakeLedger)

    async def fake_provision(**_kwargs):
        return {"status": "delivered", "vpn_delivered": True}

    async def failed_email(**_kwargs):
        raise LiveReceiptError("EMAIL_PROVIDER_DOWN")

    monkeypatch.setattr(live_checkout, "fulfill_paid_order_once", fake_provision)
    monkeypatch.setattr(live_checkout, "send_paid_access_receipt_once", failed_email)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(live_checkout.handle_live_paid_webhook(
            raw=raw, timestamp=timestamp, signature=signature,
        ))
    assert exc.value.status_code == 503
    assert exc.value.detail == "LIVE_ACCESS_EMAIL_RETRY"
    assert "Retry-After" in exc.value.headers
