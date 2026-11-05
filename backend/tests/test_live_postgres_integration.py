"""Live ledger lifecycle on isolated PostgreSQL; no external provider writes."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from vainah.live_ledger import LiveLedgerError, PostgresLiveOrderLedger

OWNER = "v1_" + "a" * 64
OTHER_OWNER = "v1_" + "b" * 64
SIGNING_SECRET = "test-live-webhook-" + "s" * 40
SUBSCRIPTION = "https://sub.example.com/private-test-live-subscription"


@pytest.fixture
def live(postgres_url, monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "live-isolated-test-" + "k" * 40)
    return PostgresLiveOrderLedger(postgres_url)


def reserve_invoice(live, *, owner=OWNER, email="owner@example.com"):
    order_id = live.reserve(owner_ref=owner, verified_email=email, plan_id="30")
    payment_id = "pay_test_" + uuid4().hex
    assert live.attach_invoice(order_id, payment_id) is True
    return order_id, payment_id


def signed_event(order_id, payment_id, *, status="paid", **changes):
    data = {
        "order_id": order_id, "payment_id": payment_id, "status": status,
        "event_type": "payment." + status, "amount": "99.00",
        "currency": "RUB", "test": False,
    }
    data.update(changes)
    raw = json.dumps(data, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SIGNING_SECRET.encode(), timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return {
        "raw_body": raw, "timestamp": timestamp, "signature": signature,
        "secret": SIGNING_SECRET,
    }


def reserve_paid(live, **kwargs):
    order_id, payment_id = reserve_invoice(live, **kwargs)
    assert live.record_signed_paid(**signed_event(order_id, payment_id)) is True
    return order_id, payment_id


def test_live_paid_delivery_and_reversal_are_owner_private_and_monotonic(live, postgres_url):
    order_id, payment_id = reserve_paid(live)
    assert live.record_signed_paid(**signed_event(order_id, payment_id)) is True
    assert live.claim_delivery_once(order_id) is not None
    assert live.claim_delivery_once(order_id) is None
    assert live.claimed_verified_email(order_id=order_id, owner_ref=OWNER) == "owner@example.com"
    with pytest.raises(LiveLedgerError, match="CLAIM_NOT_FOUND"):
        live.claimed_verified_email(order_id=order_id, owner_ref=OTHER_OWNER)
    assert live.mark_delivered(
        order_id=order_id, subscription_url=SUBSCRIPTION, panel_confirmed=True,
    ) is True
    assert live.owner_subscription_url(OWNER) == SUBSCRIPTION
    assert live.owner_subscription_url(OTHER_OWNER) is None
    assert live.owner_orders(OTHER_OWNER) == []
    with psycopg.connect(postgres_url) as conn:
        encrypted = conn.execute("""
            SELECT receipt_email_cipher, subscription_cipher
            FROM vainah_live_orders WHERE order_id = %s
        """, (order_id,)).fetchone()
    assert "owner@example.com" not in str(encrypted)
    assert SUBSCRIPTION not in str(encrypted)
    reversal = signed_event(order_id, payment_id, status="refunded")
    assert live.record_signed_reversal(**reversal) == "refunded"
    assert live.record_signed_reversal(**reversal) == "refunded"
    assert live.record_signed_paid(**signed_event(order_id, payment_id)) is False
    assert live.claim_delivery_once(order_id) is None
    assert live.owner_subscription_url(OWNER) is None
    assert live.delivery_snapshot(order_id) == {
        "payment_state": "refunded", "delivery_state": "manual_review",
        "signed_paid": True, "owner_block": None,
    }
    assert live.record_signed_reversal(
        **signed_event(order_id, payment_id, status="chargeback")
    ) == "chargeback"
    assert live.record_signed_reversal(**reversal) == "chargeback"


def test_live_invoice_binding_is_unique_and_immutable(live):
    order_id, payment_id = reserve_invoice(live)
    assert live.attach_invoice(order_id, "pay_different_123456") is False
    second = live.reserve(owner_ref=OWNER, verified_email="owner@example.com", plan_id="30")
    with pytest.raises(LiveLedgerError, match="LEDGER_UNAVAILABLE"):
        live.attach_invoice(second, payment_id)
    with pytest.raises(LiveLedgerError, match="PAYMENT_MISMATCH"):
        live.record_signed_paid(**signed_event(order_id, "pay_different_123456"))
    assert live.claim_delivery_once(order_id) is None
    assert live.record_signed_paid(**signed_event(order_id, payment_id)) is True


def test_parallel_duplicate_paid_callbacks_claim_one_order_once(live):
    order_id, payment_id = reserve_invoice(live)
    event = signed_event(order_id, payment_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: live.record_signed_paid(**event), range(4))) == [True] * 4
        claims = list(pool.map(lambda _: live.claim_delivery_once(order_id), range(4)))
    assert sum(claim is not None for claim in claims) == 1


def test_same_owner_different_orders_serialize_until_delivery(live):
    first, _ = reserve_paid(live)
    second, _ = reserve_paid(live)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(live.claim_delivery_once, (first, second)))
    assert sum(claim is not None for claim in claims) == 1
    claimed = first if claims[0] is not None else second
    waiting = second if claimed == first else first
    assert live.delivery_snapshot(waiting) == {
        "payment_state": "paid", "delivery_state": "pending",
        "signed_paid": True, "owner_block": "claimed",
    }
    assert live.mark_delivered(
        order_id=claimed, subscription_url=SUBSCRIPTION, panel_confirmed=True,
    ) is True
    assert live.claim_delivery_once(waiting) is not None
    assert live.claim_delivery_once(claimed) is None


def test_ambiguous_write_blocks_other_orders_for_same_owner_only(live):
    first, _ = reserve_paid(live)
    second, _ = reserve_paid(live)
    unrelated, _ = reserve_paid(live, owner=OTHER_OWNER, email="other@example.com")
    assert live.claim_delivery_once(first) is not None
    assert live.mark_uncertain(first) is True
    assert live.claim_delivery_once(second) is None
    assert live.delivery_snapshot(second)["owner_block"] == "manual_review"
    assert live.claim_delivery_once(unrelated) is not None


def test_reversal_during_claim_blocks_completion_and_following_owner_order(live):
    first, payment_id = reserve_paid(live)
    second, _ = reserve_paid(live)
    assert live.claim_delivery_once(first) is not None
    assert live.record_signed_reversal(
        **signed_event(first, payment_id, status="refunded")
    ) == "refunded"
    assert live.mark_delivered(
        order_id=first, subscription_url=SUBSCRIPTION, panel_confirmed=True,
    ) is False
    with pytest.raises(LiveLedgerError, match="CLAIM_NOT_FOUND"):
        live.claimed_verified_email(order_id=first, owner_ref=OWNER)
    assert live.claim_delivery_once(second) is None
    assert live.owner_subscription_url(OWNER) is None


def test_prior_delivered_profile_reversal_blocks_in_flight_extension(live):
    first, payment_id = reserve_paid(live)
    assert live.claim_delivery_once(first) is not None
    assert live.mark_delivered(
        order_id=first, subscription_url=SUBSCRIPTION, panel_confirmed=True,
    ) is True
    second, _ = reserve_paid(live)
    assert live.claim_delivery_once(second) is not None
    assert live.record_signed_reversal(
        **signed_event(first, payment_id, status="refunded")
    ) == "refunded"
    with pytest.raises(LiveLedgerError, match="CLAIM_NOT_FOUND"):
        live.claimed_verified_email(order_id=second, owner_ref=OWNER)
    assert live.mark_delivered(
        order_id=second, subscription_url=SUBSCRIPTION, panel_confirmed=True,
    ) is False
    assert live.owner_subscription_url(OWNER) is None


def test_paid_state_without_signed_webhook_proof_cannot_claim(live, postgres_url):
    order_id, _ = reserve_invoice(live)
    with psycopg.connect(postgres_url) as conn:
        conn.execute("""
            UPDATE vainah_live_orders SET payment_state = 'paid'
            WHERE order_id = %s
        """, (order_id,))
    assert live.delivery_snapshot(order_id)["signed_paid"] is False
    assert live.claim_delivery_once(order_id) is None
