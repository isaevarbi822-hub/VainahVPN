"""PostgreSQL LIVE order ledger guardrails without a real database or payment."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest

from vainah.live_ledger import (
    LiveLedgerError,
    PostgresLiveOrderLedger,
    seal_live_secret,
    unseal_live_secret,
)


class FakeCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=None):
        self.commands.append((statement, params))

    def fetchone(self):
        if not self.responses:
            return None
        return self.responses.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self.cur = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cur


def setup_connection(monkeypatch, cursor):
    import vainah.live_ledger as ledger

    monkeypatch.setattr(
        ledger.psycopg, "connect",
        lambda *_args, **_kwargs: FakeConnection(cursor),
    )
    return PostgresLiveOrderLedger("postgresql://fake-host/fake-db")


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "non-production-" + "s" * 40)


def test_live_secret_is_authenticated_encrypted_and_cannot_be_forged():
    secret = "https://sub.example.com/secret-" + "a" * 30
    ciphertext = seal_live_secret(secret)
    assert secret not in ciphertext
    assert unseal_live_secret(ciphertext) == secret
    with pytest.raises(LiveLedgerError):
        unseal_live_secret(ciphertext[:-3] + "bad")


def test_bad_live_ledger_url_fails_closed():
    with pytest.raises(LiveLedgerError, match="POSTGRES_REQUIRED"):
        PostgresLiveOrderLedger("sqlite:///sandbox.db")


def test_reserve_stores_only_encrypted_verified_email(monkeypatch):
    cursor = FakeCursor([])
    store = setup_connection(monkeypatch, cursor)
    order_id = store.reserve(
        owner_ref="v1_" + "a" * 64,
        verified_email="Owner@example.com", plan_id="365-family",
    )
    assert order_id.startswith("vainah_live_")
    sql, params = next(
        (sql, args) for sql, args in cursor.commands
        if "INSERT INTO vainah_live_orders" in sql
    )
    assert "receipt_email_cipher" in sql
    assert "Owner@example.com" not in str(params)
    assert params[3] == "1000.00"
    assert unseal_live_secret(params[4]) == "owner@example.com"


def test_delivery_claim_is_atomic_one_time_and_no_automatic_lease_reclaim(monkeypatch):
    order_id = "vainah_live_" + uuid4().hex
    owner = "v1_" + "a" * 64
    cursor = FakeCursor([
        (order_id, owner, "30", "99.00", "pay_payment000", "paid", "claimed"),
        None,
    ])
    store = setup_connection(monkeypatch, cursor)
    first = store.claim_delivery_once(order_id)
    second = store.claim_delivery_once(order_id)
    assert first is not None
    assert first.plan_id == "30"
    assert second is None
    claims = [sql for sql, _ in cursor.commands if "UPDATE vainah_live_orders" in sql]
    assert len(claims) == 2
    assert all("delivery_state = 'pending'" in sql for sql in claims)
    assert all("payment_state = 'paid'" in sql for sql in claims)
    assert all("RETURNING" in sql for sql in claims)


def test_mark_delivered_requires_postcheck_and_encrypts_link(monkeypatch):
    order_id = "vainah_live_" + uuid4().hex
    cursor = FakeCursor([(order_id,)])
    store = setup_connection(monkeypatch, cursor)
    with pytest.raises(LiveLedgerError, match="UNVERIFIED"):
        store.mark_delivered(
            order_id=order_id, subscription_url="https://sub.example/abc"
        )
    assert store.mark_delivered(
        order_id=order_id, subscription_url="https://sub.example/abc",
        panel_confirmed=True,
    )
    sql, params = next(
        (statement, args) for statement, args in cursor.commands
        if "SET delivery_state = 'delivered'" in statement
    )
    assert "payment_state = 'paid'" in sql
    assert "delivery_state = 'claimed'" in sql
    assert "https://sub.example/abc" not in str(params)
    assert unseal_live_secret(params[0]) == "https://sub.example/abc"


def test_live_paid_event_uses_signed_original_payment_record(monkeypatch):
    order_id = "vainah_live_" + uuid4().hex
    payment_id = "pay_" + uuid4().hex
    owner = "v1_" + "a" * 64
    cursor = FakeCursor([(owner, "30", payment_id, "99.00", "created")])
    store = setup_connection(monkeypatch, cursor)
    body = json.dumps({
        "order_id": order_id, "payment_id": payment_id,
        "status": "paid", "event_type": "payment.paid",
        "amount": "99.00", "currency": "RUB",
    }).encode()
    signing_secret = "test-only-signing-" + "u" * 30
    timestamp = str(int(time.time()))
    signature = hmac.new(
        signing_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256,
    ).hexdigest()
    assert store.record_signed_paid(
        raw_body=body, timestamp=timestamp, signature=signature,
        secret=signing_secret,
    )
    updates = [sql for sql, _ in cursor.commands if "SET payment_state = 'paid'" in sql]
    assert len(updates) == 1


@pytest.mark.parametrize("method", ["record_signed_paid", "record_signed_reversal"])
def test_deeply_nested_signed_json_is_rejected_before_database(monkeypatch, method):
    store = setup_connection(monkeypatch, FakeCursor([]))
    raw = b"[" * 1200 + b"0" + b"]" * 1200
    timestamp = str(int(time.time()))
    secret = "test-deep-json-" + "s" * 30
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256,
    ).hexdigest()
    with pytest.raises(LiveLedgerError, match="LIVE_WEBHOOK_INVALID"):
        getattr(store, method)(
            raw_body=raw, timestamp=timestamp, signature=signature, secret=secret,
        )
