"""End-to-end gift funding/one-time claim against disposable PostgreSQL.

The signed provider event is simulated; NO real charges or H1Cloud writes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest

from vainah.live_ledger import LiveLedgerError, PostgresLiveOrderLedger

BUYER = "v1_" + "a" * 64
RECIPIENT = "v1_" + "b" * 64
PAYMENT = "pay_validgiftpayment123456"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "temporary-gift-postgres-test-secret-" + "s" * 42)


def test_signed_gift_payment_requires_one_redeem_before_h1_claim(postgres_url):
    ledger = PostgresLiveOrderLedger(postgres_url)
    nonce = str(uuid4())
    order_id, prior = ledger.reserve_checkout(
        owner_ref=BUYER,
        verified_email="buyer@example.com",
        plan_id="30",
        idempotency_key=nonce,
        gift=True,
    )
    assert prior is None
    assert ledger.is_gift_order(order_id) is True
    assert ledger.claim_delivery_once(order_id) is None
    assert ledger.buyer_gift_cards(BUYER)[0]["gift_code"] is None

    assert ledger.attach_hosted_invoice(
        order_id=order_id, payment_id=PAYMENT,
        pay_url="https://pay.rollypay.io/pay/paidurl12345",
    )
    assert ledger.buyer_gift_cards(BUYER)[0]["gift_code"] is None
    secret = "test-signed-gift-payment-" + "x" * 40
    raw = json.dumps({
        "event_type": "payment.paid", "status": "paid",
        "order_id": order_id, "payment_id": PAYMENT,
        "amount": "99.00", "currency": "RUB",
    }).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256,
    ).hexdigest()
    assert ledger.record_signed_paid(
        raw_body=raw, timestamp=timestamp,
        signature=signature, secret=secret,
    ) is True
    assert ledger.claim_delivery_once(order_id) is None
    code = ledger.buyer_gift_cards(BUYER)[0]["gift_code"]
    assert code is not None and code.startswith("VG") and len(code) == 34

    with pytest.raises(LiveLedgerError, match="GIFT_NOT_REDEEMABLE"):
        ledger.redeem_paid_gift_once(
            gift_code="VG" + "0" * 32,
            recipient_ref=RECIPIENT,
            verified_email="recipient@example.com",
        )
    assert ledger.redeem_paid_gift_once(
        gift_code=code, recipient_ref=RECIPIENT,
        verified_email="recipient@example.com",
    ) == order_id
    with pytest.raises(LiveLedgerError, match="GIFT_NOT_REDEEMABLE"):
        ledger.redeem_paid_gift_once(
            gift_code=code, recipient_ref=BUYER,
            verified_email="buyer@example.com",
        )
    assert ledger.buyer_gift_cards(BUYER)[0]["gift_code"] is None
    assert ledger.recipient_gift_order(
        order_id=order_id, recipient_ref=RECIPIENT,
    )
    assert not ledger.recipient_gift_order(
        order_id=order_id, recipient_ref=BUYER,
    )
    assert ledger.recipient_gift_cards(RECIPIENT)[0]["can_finish"] is True
    claim = ledger.claim_delivery_once(order_id)
    assert claim is not None and claim.owner_ref == RECIPIENT
    assert ledger.claim_delivery_once(order_id) is None
    assert ledger.claimed_verified_email(
        order_id=order_id, owner_ref=RECIPIENT,
    ) == "recipient@example.com"


def test_checkout_idempotency_never_turns_regular_order_into_gift(postgres_url):
    ledger = PostgresLiveOrderLedger(postgres_url)
    nonce = str(uuid4())
    normal, _ = ledger.reserve_checkout(
        owner_ref=BUYER, verified_email="buyer@example.com",
        plan_id="30", idempotency_key=nonce,
    )
    assert ledger.is_gift_order(normal) is False
    with pytest.raises(LiveLedgerError, match="LIVE_IDEMPOTENCY_CONFLICT"):
        ledger.reserve_checkout(
            owner_ref=BUYER, verified_email="buyer@example.com",
            plan_id="30", idempotency_key=nonce, gift=True,
        )


def test_unrefunded_and_unpaid_code_is_always_hidden(postgres_url):
    ledger = PostgresLiveOrderLedger(postgres_url)
    order_id, _ = ledger.reserve_checkout(
        owner_ref=BUYER, verified_email="buyer@example.com",
        plan_id="60", idempotency_key=str(uuid4()), gift=True,
    )
    rows = ledger.buyer_gift_cards(BUYER)
    assert rows[0]["order_id"] == order_id
    assert rows[0]["payment_state"] == "reserved"
    assert rows[0]["gift_code"] is None
    assert ledger.recipient_gift_cards(RECIPIENT) == []
