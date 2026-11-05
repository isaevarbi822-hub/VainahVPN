"""Actual PostgreSQL concurrency for verified login and live-order storage.

All connections use the disposable per-test schema fixture. No provider calls,
emails, payment processing, or VPN writes occur in these tests.
"""
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from fastapi import HTTPException

from vainah import email_auth, live_ledger
from vainah.live_ledger import LiveLedgerError, PostgresLiveOrderLedger


def test_live_ledger_first_workers_can_reserve_concurrently(postgres_url, monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-live-concurrency-" + "s" * 40)
    start = Barrier(4)

    def reserve(index):
        start.wait(timeout=10)
        return PostgresLiveOrderLedger(postgres_url).reserve(
            owner_ref="v1_" + "a" * 64,
            verified_email=f"owner{index}@example.com", plan_id="30",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        orders = list(pool.map(reserve, range(4)))
    assert len(set(orders)) == 4
    saved = PostgresLiveOrderLedger(postgres_url).owner_orders("v1_" + "a" * 64)
    assert {row["order_id"] for row in saved} == set(orders)
    assert all(row["payment_state"] == "reserved" for row in saved)


def test_email_first_workers_can_create_independent_codes(postgres_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-otp-concurrency-" + "s" * 40)
    start = Barrier(4)

    def issue(index):
        start.wait(timeout=10)
        email = f"owner{index}@example.com"
        return email, email_auth._locked_send_code(email, f"{index:064x}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(issue, range(4)))
    assert len(codes) == 4
    for email, code in codes:
        assert email_auth._verify_code(email, code) is True
        assert email_auth._verify_code(email, code) is False


def test_same_email_concurrent_requests_keep_one_usable_code(postgres_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-otp-concurrency-" + "s" * 40)
    start = Barrier(4)

    def issue(index):
        start.wait(timeout=10)
        try:
            return email_auth._locked_send_code("same@example.com", f"{index:064x}")
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(issue, range(4)))
    assert outcomes.count(429) == 3
    codes = [value for value in outcomes if isinstance(value, str)]
    assert len(codes) == 1
    assert email_auth._verify_code("same@example.com", codes[0]) is True


def test_concurrent_otp_verification_consumes_code_once(postgres_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-otp-concurrency-" + "s" * 40)
    code = email_auth._locked_send_code("same@example.com", "a" * 64)
    start = Barrier(4)

    def verify(_index):
        start.wait(timeout=10)
        return email_auth._verify_code("same@example.com", code)

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(verify, range(4)))
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 3


def test_concurrent_wrong_codes_cannot_exceed_attempt_budget(postgres_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-otp-concurrency-" + "s" * 40)
    code = email_auth._locked_send_code("same@example.com", "a" * 64)
    wrong = "999999" if code != "999999" else "000000"
    start = Barrier(8)

    def verify(_index):
        start.wait(timeout=10)
        return email_auth._verify_code("same@example.com", wrong)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(verify, range(8)))
    assert outcomes == [False] * 8
    assert email_auth._verify_code("same@example.com", code) is False


def test_live_signed_paid_claim_is_once_and_uncertainty_cannot_retry(postgres_url, monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-live-concurrency-" + "s" * 40)
    store = PostgresLiveOrderLedger(postgres_url)
    order = store.reserve(
        owner_ref="v1_" + "a" * 64,
        verified_email="buyer@example.com", plan_id="30",
    )
    payment_id = "pay_test_invoice_123456"
    assert store.attach_invoice(order, payment_id) is True
    assert store.claim_delivery_once(order) is None
    body = json.dumps({
        "event_type": "payment.paid", "status": "paid",
        "order_id": order, "payment_id": payment_id,
        "amount": "99.00", "currency": "RUB",
    }).encode()
    timestamp = str(int(time.time()))
    secret = "test-only-webhook-signing-secret-" + "s" * 32
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256,
    ).hexdigest()
    for _ in range(2):
        assert store.record_signed_paid(
            raw_body=body, timestamp=timestamp, signature=signature, secret=secret,
        ) is True
    start = Barrier(4)

    def claim(_index):
        start.wait(timeout=10)
        return PostgresLiveOrderLedger(postgres_url).claim_delivery_once(order)

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(claim, range(4)))
    winners = [claim for claim in outcomes if claim is not None]
    assert len(winners) == 1
    assert winners[0].payment_state == "paid"
    assert winners[0].delivery_state == "claimed"
    assert store.claimed_verified_email(
        order_id=order, owner_ref="v1_" + "a" * 64,
    ) == "buyer@example.com"
    assert store.mark_uncertain(order) is True
    assert store.claim_delivery_once(order) is None
    assert store.owner_subscription_url("v1_" + "a" * 64) is None


@pytest.mark.parametrize("lock_kind", ["live_schema", "live_table", "email_schema", "email_row"])
def test_blocked_live_and_otp_locks_fail_safely_then_recover(postgres_url, monkeypatch, lock_kind):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-lock-timeout-" + "s" * 40)
    module = live_ledger if lock_kind.startswith("live_") else email_auth
    monkeypatch.setattr(module, "LOCK_TIMEOUT_MS", 100)
    monkeypatch.setattr(module, "STATEMENT_TIMEOUT_MS", 250)
    owner = "v1_" + "a" * 64
    if module is live_ledger:
        store = PostgresLiveOrderLedger(postgres_url)

        def reserve():
            return store.reserve(owner_ref=owner, verified_email="buyer@example.com", plan_id="30")

        original = reserve()
        operation = reserve
    else:
        code = email_auth._locked_send_code("buyer@example.com", "a" * 64)

        def operation():
            return email_auth._verify_code("buyer@example.com", code)

    with psycopg.connect(postgres_url) as blocker:
        if lock_kind.endswith("schema"):
            name = "vainah_live_orders_schema" if module is live_ledger else "vainah_email_login_schema"
            blocker.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (name,))
        elif lock_kind == "live_table":
            blocker.execute("LOCK TABLE vainah_live_orders IN ACCESS EXCLUSIVE MODE")
        else:
            blocker.execute("SELECT email FROM vainah_email_login_codes WHERE email = %s FOR UPDATE", ("buyer@example.com",))
        started = time.monotonic()
        if module is live_ledger:
            with pytest.raises(LiveLedgerError) as error:
                operation()
            assert str(error.value) == "LIVE_LEDGER_UNAVAILABLE"
        else:
            with pytest.raises(HTTPException) as error:
                operation()
            assert error.value.status_code == 503
            assert error.value.detail == "EMAIL_LOGIN_DATABASE_UNAVAILABLE"
        assert time.monotonic() - started < 2
    # A lock timeout rolls back the failed operation, preserving existing order
    # identity or the unconsumed OTP. Releasing the blocker restores the path.
    result = operation()
    if module is live_ledger:
        assert result != original
        assert {row["order_id"] for row in store.owner_orders(owner)} == {original, result}
    else:
        assert result is True
        assert operation() is False
