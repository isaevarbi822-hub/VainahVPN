"""Paid renewal, duplicate webhook, refund and uncertain-H1 safety tests.

All network/payment/H1 and email traffic is mocked. PostgreSQL uses
a disposable schema; no real invoice is created or charged.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException

from vainah import live_checkout, live_fulfillment, live_receipt
from vainah.h1_live_provision import LiveH1Error
from vainah.live_ledger import PostgresLiveOrderLedger, seal_live_secret


@pytest.fixture
def renewal(postgres_url, monkeypatch):
    key = "test-renewal-signing-" + "s" * 40
    secret = "test-renewal-webhook-" + "h" * 40
    email = "renewal-owner@example.com"
    owner = "v1_" + "e" * 64
    monkeypatch.setenv("SESSION_SIGNING_KEY", key)
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", secret)
    ledger = PostgresLiveOrderLedger(postgres_url)
    old_order = "vainah_live_" + uuid4().hex
    new_order = "vainah_live_" + uuid4().hex
    old_payment = "pay_" + uuid4().hex
    new_payment = "pay_" + uuid4().hex
    with psycopg.connect(postgres_url) as conn, conn.cursor() as cur:
        ledger._schema(cur)
        cur.execute("""
            INSERT INTO vainah_live_orders (
                order_id, owner_ref, plan_id, amount_rub, payment_id,
                receipt_email_cipher, subscription_cipher, payment_state,
                delivery_state, webhook_at, delivered_at
            ) VALUES (%s, %s, '30', 99, %s, %s, %s,
                      'paid', 'delivered', now(), now())
        """, (old_order, owner, old_payment, seal_live_secret(email),
              seal_live_secret("https://sub.example.com/old-sub")))
        cur.execute("""
            INSERT INTO vainah_live_orders (
                order_id, owner_ref, plan_id, amount_rub, payment_id,
                receipt_email_cipher, payment_state, delivery_state
            ) VALUES (%s, %s, 'pilot-1d', 10, %s, %s, 'created', 'pending')
        """, (new_order, owner, new_payment, seal_live_secret(email)))
    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    return SimpleNamespace(
        ledger=ledger, old_order=old_order, order=new_order,
        payment=new_payment, email=email, secret=secret,
        owner=owner, url=postgres_url,
    )


def signed(order, event_type="payment.paid", *, amount="10.00", valid=True):
    statuses = {
        "payment.paid": "paid", "payment.refunded": "refunded",
        "payment.chargeback": "chargeback",
    }
    raw = json.dumps({
        "event_type": event_type, "status": statuses[event_type],
        "order_id": order.order, "payment_id": order.payment,
        "amount": amount, "currency": "RUB", "test": False,
    }).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        order.secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256,
    ).hexdigest()
    if not valid:
        signature = "0" * 64
    return {"raw": raw, "timestamp": timestamp, "signature": signature}


def stub_h1_renewal(monkeypatch):
    writes = []

    async def inspect(_name, *, transport=None):
        return {"panel_ready": True, "found": True, "banned": False}

    class Node:
        def __init__(self, **kwargs):
            assert kwargs["write_contract_approved"] is True

        async def provision_once(self, *, claim, intent, operation):
            writes.append((claim.order_id, operation, intent.days, intent.devices))
            assert operation == "extend"
            assert claim.payment_state == "paid"
            return SimpleNamespace(
                subscription_url="https://sub.example.com/renewed-sub",
                expires_at=int(time.time()) + 86400,
            )

    monkeypatch.setattr(live_fulfillment, "read_h1_issued_client_status", inspect)
    monkeypatch.setattr(live_fulfillment, "LiveH1CloudNode", Node)
    return writes


def test_real_paid_renewal_repeated_callback_never_double_extends(
    renewal, monkeypatch,
):
    writes = stub_h1_renewal(monkeypatch)
    sent = []

    async def send_email(to, subject, body, **kwargs):
        sent.append((to, subject, body, kwargs))

    monkeypatch.setattr(live_receipt, "send_email", send_email)
    event = signed(renewal)
    first = asyncio.run(live_checkout.handle_live_paid_webhook(**event))
    duplicate = asyncio.run(live_checkout.handle_live_paid_webhook(**event))
    assert first["vpn_delivered"] is True
    assert duplicate["vpn_delivered"] is True
    assert writes == [(renewal.order, "extend", 1, 3)]
    assert len(sent) == 1
    assert sent[0][0] == renewal.email
    assert sent[0][3]["idempotency_key"] == "live-access/" + renewal.order
    assert renewal.ledger.owner_subscription_url(renewal.owner) == (
        "https://sub.example.com/renewed-sub"
    )
    with psycopg.connect(renewal.url) as conn:
        old = conn.execute("""
            SELECT payment_state, delivery_state FROM vainah_live_orders
            WHERE order_id = %s
        """, (renewal.old_order,)).fetchone()
        new = conn.execute("""
            SELECT payment_state, delivery_state, access_email_sent_at IS NOT NULL
            FROM vainah_live_orders WHERE order_id = %s
        """, (renewal.order,)).fetchone()
    assert old == ("paid", "delivered")
    assert new == ("paid", "delivered", True)


def test_refund_blocks_access_and_stale_paid_replay(renewal, monkeypatch):
    writes = stub_h1_renewal(monkeypatch)
    emails = []

    async def send_email(*args, **kwargs):
        emails.append(1)

    monkeypatch.setattr(live_receipt, "send_email", send_email)
    paid_event = signed(renewal)
    asyncio.run(live_checkout.handle_live_paid_webhook(**paid_event))
    refunded = asyncio.run(live_checkout.handle_live_paid_webhook(
        **signed(renewal, "payment.refunded")
    ))
    assert refunded["status"] == "refunded"
    assert refunded["manual_h1_revocation_required"] is True
    assert renewal.ledger.owner_subscription_url(renewal.owner) is None
    replay = asyncio.run(live_checkout.handle_live_paid_webhook(**paid_event))
    assert replay["stale_event_ignored"] is True
    repeated = asyncio.run(live_checkout.handle_live_paid_webhook(
        **signed(renewal, "payment.refunded")
    ))
    assert repeated["status"] == "refunded"
    assert writes == [(renewal.order, "extend", 1, 3)]
    assert len(emails) == 1
    with psycopg.connect(renewal.url) as conn:
        state = conn.execute("""
            SELECT payment_state, delivery_state
            FROM vainah_live_orders WHERE order_id = %s
        """, (renewal.order,)).fetchone()
    assert state == ("refunded", "manual_review")


def test_chargeback_is_terminal_over_refund(renewal, monkeypatch):
    stub_h1_renewal(monkeypatch)
    monkeypatch.setattr(live_receipt, "send_email", fake_email)
    asyncio.run(live_checkout.handle_live_paid_webhook(**signed(renewal)))
    asyncio.run(live_checkout.handle_live_paid_webhook(
        **signed(renewal, "payment.refunded")
    ))
    chargeback = asyncio.run(live_checkout.handle_live_paid_webhook(
        **signed(renewal, "payment.chargeback")
    ))
    assert chargeback["status"] == "chargeback"
    late_refund = asyncio.run(live_checkout.handle_live_paid_webhook(
        **signed(renewal, "payment.refunded")
    ))
    assert late_refund["status"] == "chargeback"
    assert renewal.ledger.owner_subscription_url(renewal.owner) is None


async def fake_email(*_args, **_kwargs):
    return None


@pytest.mark.parametrize("bad", [
    {"amount": "99.00", "valid": True},
    {"amount": "10.00", "valid": False},
])
def test_mismatched_payment_or_signature_does_not_authorize_h1(
    renewal, monkeypatch, bad,
):
    writes = stub_h1_renewal(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(live_checkout.handle_live_paid_webhook(
            **signed(renewal, **bad)
        ))
    assert exc.value.status_code in (400, 403)
    assert writes == []
    with psycopg.connect(renewal.url) as conn:
        state = conn.execute("""
            SELECT payment_state, delivery_state
            FROM vainah_live_orders WHERE order_id = %s
        """, (renewal.order,)).fetchone()
    assert state == ("created", "pending")


def test_unknown_h1_result_is_locked_for_manual_review(renewal, monkeypatch):
    writes = []

    async def inspect(_name, *, transport=None):
        return {"panel_ready": True, "found": True, "banned": False}

    class UncertainNode:
        def __init__(self, **kwargs):
            pass

        async def provision_once(self, *, claim, intent, operation):
            writes.append((claim.order_id, operation))
            raise LiveH1Error("H1_WRITE_UNCERTAIN_MANUAL_REVIEW")

    monkeypatch.setattr(live_fulfillment, "read_h1_issued_client_status", inspect)
    monkeypatch.setattr(live_fulfillment, "LiveH1CloudNode", UncertainNode)
    first = asyncio.run(live_checkout.handle_live_paid_webhook(**signed(renewal)))
    repeated = asyncio.run(live_checkout.handle_live_paid_webhook(**signed(renewal)))
    assert first["delivery_state"] == "manual_review"
    assert repeated["delivery_state"] == "manual_review"
    assert writes == [(renewal.order, "extend")]
    assert renewal.ledger.owner_subscription_url(renewal.owner) == (
        "https://sub.example.com/old-sub"
    )
