"""Real, isolated PostgreSQL ledger checks; CI supplies a disposable test DB.

Set VAINAH_TEST_DATABASE_URL to a dedicated test database. Each test creates and
removes its own schema; application/provider databases must never be selected.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException

from vainah.billing import BillingSandbox
from vainah.billing import TestOrder as SandboxOrder
from vainah.postgres_ledger import LedgerUnavailable, PostgresSandboxLedger


def provider_order(**changes):
    order = SandboxOrder(
        "vainah_test_" + uuid4().hex, "30", "99.00",
        "pay_test_" + uuid4().hex, "created", "provider",
        owner_ref="v1_" + "a" * 64, receipt_recipient="encrypted-test-recipient",
    )
    return replace(order, **changes)


def paid_event(order):
    return {
        "event_type": "payment.paid", "status": "paid", "test": True,
        "order_id": order.order_id, "payment_id": order.payment_id,
        "currency": "RUB", "amount": "99.00",
    }


def test_pending_reservation_commits_before_binding_and_is_single_use(postgres_url):
    store = PostgresSandboxLedger(postgres_url)
    reserved = provider_order(payment_id="pending:" + uuid4().hex)
    store.save(reserved)
    worker = BillingSandbox("provider", ledger_path=postgres_url)
    actual = replace(reserved, payment_id="pay_test_" + uuid4().hex)
    # A callback racing the provider response sees a retryable pending order.
    with pytest.raises(HTTPException) as error:
        worker.process_webhook(paid_event(actual))
    assert error.value.status_code == 503
    assert store.load_one(reserved.order_id)["paid_webhook_received"] is False

    store.attach_provider_payment(actual, pending_payment_id=reserved.payment_id)
    assert worker.process_webhook(paid_event(actual))["status"] == "paid"
    assert store.load_one(actual.order_id)["paid_webhook_received"] is True
    with pytest.raises(LedgerUnavailable):
        store.attach_provider_payment(
            replace(actual, payment_id="pay_other_123456"),
            pending_payment_id=reserved.payment_id,
        )
    assert store.load_one(actual.order_id)["payment_id"] == actual.payment_id


def test_failed_bind_does_not_mutate_reservation(postgres_url):
    store = PostgresSandboxLedger(postgres_url)
    reserved = provider_order(payment_id="pending:" + uuid4().hex)
    store.save(reserved)
    with pytest.raises(LedgerUnavailable):
        store.attach_provider_payment(
            replace(reserved, payment_id="pay_bound_123456", amount="1.00"),
            pending_payment_id=reserved.payment_id,
        )
    assert store.load_one(reserved.order_id)["payment_id"] == reserved.payment_id


def test_independent_worker_finds_order_and_replays_paid_without_regression(postgres_url):
    creator = BillingSandbox("provider", ledger_path=postgres_url)
    receiver = BillingSandbox("provider", ledger_path=postgres_url)
    receiver._ensure_loaded()
    order = provider_order()
    creator._save(order)
    event = paid_event(order)
    assert receiver.process_webhook(event)["status"] == "paid"
    assert receiver.process_webhook(event)["status"] == "paid"
    # A different worker still holds its pre-webhook process snapshot.
    creator._save(order)
    saved = creator.ledger.load_one(order.order_id)
    assert saved["status"] == "paid"
    assert saved["paid_webhook_received"] is True
    assert receiver.read(order.order_id)["webhook_received"] is True


def test_concurrent_stale_writes_preserve_paid_proof_and_refund(postgres_url):
    store = PostgresSandboxLedger(postgres_url)
    order = provider_order()
    store.save(order)
    paid = replace(order, status="paid", webhook_received=True, paid_webhook_received=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(store.save, [order, paid, order, paid, order]))
    saved = store.load_one(order.order_id)
    assert saved["status"] == "paid"
    assert saved["paid_webhook_received"] is True
    store.save(replace(paid, status="refunded"))
    store.save(paid)
    assert store.load_one(order.order_id)["status"] == "refunded"


def test_legacy_paid_row_is_not_promoted_to_signed_paid_proof(postgres_url):
    with psycopg.connect(postgres_url) as connection:
        connection.execute("""
            CREATE TABLE vainah_sandbox_orders (
                order_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL,
                amount TEXT NOT NULL, payment_id TEXT NOT NULL,
                status TEXT NOT NULL, mode TEXT NOT NULL,
                webhook_received BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        connection.execute("""
            INSERT INTO vainah_sandbox_orders
                (order_id, plan_id, amount, payment_id, status, mode, webhook_received)
            VALUES (%s, '30', '99.00', 'pay_legacy_123456', 'paid', 'provider', TRUE)
        """, ("vainah_test_" + "b" * 32,))
    store = PostgresSandboxLedger(postgres_url)
    order = store.load_one("vainah_test_" + "b" * 32)
    assert order["webhook_received"] is True
    assert order["paid_webhook_received"] is False
    assert store.claim_receipt(order["order_id"], claim_token=uuid4().hex) is None


def test_receipt_lease_requires_signed_paid_and_is_cross_worker(postgres_url):
    store = PostgresSandboxLedger(postgres_url)
    order = provider_order(status="paid", webhook_received=True)
    store.save(order)
    assert store.claim_receipt(order.order_id, claim_token="receipt-token") is None
    store.save(replace(order, paid_webhook_received=True))
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: store.claim_receipt(order.order_id, claim_token="receipt-token"), range(3)))
    assert results.count("encrypted-test-recipient") == 1
    store.finish_receipt(order.order_id, claim_token="receipt-token")
    assert store.claim_receipt(order.order_id, claim_token="receipt-token") is None
    assert store.load_one(order.order_id)["receipt_emailed"] is True


def test_db_failure_rolls_back_paid_cache_and_retry_preserves_order(postgres_url, monkeypatch):
    store = BillingSandbox("provider", ledger_path=postgres_url)
    order = provider_order()
    store._save(order)
    store.read(order.order_id)
    original_save = store.ledger.save

    def unavailable(_order):
        raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")

    monkeypatch.setattr(store.ledger, "save", unavailable)
    with pytest.raises(HTTPException) as error:
        store.process_webhook(paid_event(order))
    assert error.value.status_code == 503
    assert store.orders[order.order_id].status == "created"
    assert store.orders[order.order_id].paid_webhook_received is False
    monkeypatch.setattr(store.ledger, "save", original_save)
    assert store.process_webhook(paid_event(order))["status"] == "paid"
    assert store.ledger.load_one(order.order_id)["paid_webhook_received"] is True


def test_owner_listing_refreshes_other_workers_and_never_leaks(postgres_url):
    reader = BillingSandbox("provider", ledger_path=postgres_url)
    reader._ensure_loaded()
    store = PostgresSandboxLedger(postgres_url)
    own = provider_order(status="paid", webhook_received=True, paid_webhook_received=True)
    foreign = provider_order(owner_ref="v1_" + "c" * 64)
    store.save(own)
    store.save(foreign)
    rows = reader.owned_test_orders(own.owner_ref)
    assert [row["order_id"] for row in rows] == [own.order_id]
    reader.require_order_owner(own.order_id, own.owner_ref)
    with pytest.raises(HTTPException) as error:
        reader.require_order_owner(foreign.order_id, own.owner_ref)
    assert error.value.status_code == 404


def test_first_workers_initialize_schema_concurrently(postgres_url):
    stores = [PostgresSandboxLedger(postgres_url) for _ in range(4)]
    orders = [provider_order() for _ in stores]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair: pair[0].save(pair[1]), zip(stores, orders, strict=True)))
    assert len(stores[0].load()) == 4


def test_save_returns_actual_refunded_outcome_to_stale_worker(postgres_url):
    store = PostgresSandboxLedger(postgres_url)
    paid = provider_order(status="paid", webhook_received=True, paid_webhook_received=True)
    store.save(paid)
    store.save(replace(paid, status="refunded"))
    saved = store.save(paid)
    assert saved["status"] == "refunded"
    assert saved["paid_webhook_received"] is True


def test_webhook_overlapping_refund_returns_committed_terminal_state(postgres_url, monkeypatch):
    service = BillingSandbox("provider", ledger_path=postgres_url)
    order = provider_order()
    service._save(order)
    original_save = service.ledger.save

    def refund_before_paid_commit(proposed):
        original_save(replace(proposed, status="refunded"))
        return original_save(proposed)

    monkeypatch.setattr(service.ledger, "save", refund_before_paid_commit)
    result = service.process_webhook(paid_event(order))
    assert result["status"] == "refunded"
    assert service.orders[order.order_id].status == "refunded"
    assert service.ledger.load_one(order.order_id)["status"] == "refunded"


@pytest.mark.parametrize("changed", [
    {"payment_id": "pay_unrelated_123456"},
    {"amount": "1.00"},
    {"plan_id": "365-family"},
    {"mode": "mock"},
    {"owner_ref": "v1_" + "f" * 64},
    {"receipt_recipient": "another-encrypted-recipient"},
])
def test_save_cannot_merge_proof_from_different_immutable_binding(postgres_url, changed):
    store = PostgresSandboxLedger(postgres_url)
    order = provider_order()
    store.save(order)
    unrelated = replace(
        order, status="paid", webhook_received=True,
        paid_webhook_received=True, **changed,
    )
    with pytest.raises(LedgerUnavailable):
        store.save(unrelated)
    saved = store.load_one(order.order_id)
    assert saved["status"] == "created"
    assert saved["paid_webhook_received"] is False
    assert saved["payment_id"] == order.payment_id


def test_expired_receipt_worker_cannot_release_or_finish_new_claim(postgres_url):
    store = PostgresSandboxLedger(postgres_url)
    order = provider_order(status="paid", webhook_received=True, paid_webhook_received=True)
    store.save(order)
    assert store.claim_receipt(order.order_id, claim_token="worker-A") is not None
    with psycopg.connect(postgres_url) as connection:
        connection.execute("""
            UPDATE vainah_sandbox_orders
            SET receipt_claimed_at = NOW() - interval '3 minutes'
            WHERE order_id = %s
        """, (order.order_id,))
    assert store.claim_receipt(order.order_id, claim_token="worker-B") is not None
    store.release_receipt(order.order_id, claim_token="worker-A")
    assert store.claim_receipt(order.order_id, claim_token="worker-C") is None
    assert store.finish_receipt(order.order_id, claim_token="worker-A") is False
    assert store.load_one(order.order_id)["receipt_emailed"] is False
    assert store.finish_receipt(order.order_id, claim_token="worker-B") is True
    assert store.load_one(order.order_id)["receipt_emailed"] is True


@pytest.mark.parametrize("lock_kind", ["advisory", "table"])
def test_blocked_ledger_locks_fail_promptly_and_recover(postgres_url, monkeypatch, lock_kind):
    from time import monotonic

    from vainah import postgres_ledger

    store = PostgresSandboxLedger(postgres_url)
    order = provider_order()
    store.save(order)
    monkeypatch.setattr(postgres_ledger, "LOCK_TIMEOUT_MS", 100)
    monkeypatch.setattr(postgres_ledger, "STATEMENT_TIMEOUT_MS", 250)
    with psycopg.connect(postgres_url) as blocker:
        if lock_kind == "advisory":
            blocker.execute("SELECT pg_advisory_xact_lock(1447960897, hashtext(current_schema()))")
        else:
            blocker.execute("LOCK TABLE vainah_sandbox_orders IN ACCESS EXCLUSIVE MODE")
        started = monotonic()
        with pytest.raises(LedgerUnavailable):
            store.load_one(order.order_id)
        assert monotonic() - started < 2
    assert store.load_one(order.order_id)["status"] == "created"
