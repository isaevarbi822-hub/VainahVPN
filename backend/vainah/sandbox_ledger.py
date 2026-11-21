"""Local-only durable ledger for SANDBOX test orders.

Not a production payments database. No identities, API keys, signing secrets,
VLESS subscriptions or payment links are stored here.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .postgres_ledger import LedgerUnavailable

ORDER_FIELDS = (
    "order_id", "plan_id", "amount", "payment_id", "status", "mode",
    "webhook_received", "owner_ref", "receipt_emailed", "receipt_recipient",
    "paid_webhook_received",
)


class SandboxLedger:
    def __init__(self, filename: str):
        self.path = Path(filename).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            # Serialize the inspect-and-ALTER migration across fresh workers;
            # SQLite has no ADD COLUMN IF NOT EXISTS for these upgrades.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS sandbox_orders (
                    order_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    payment_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('mock', 'provider')),
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
                )
            """)
            fields = {row[1] for row in db.execute("PRAGMA table_info(sandbox_orders)")}
            if "webhook_received" not in fields:
                db.execute("ALTER TABLE sandbox_orders ADD COLUMN webhook_received INTEGER NOT NULL DEFAULT 0")
            if "owner_ref" not in fields:
                db.execute("ALTER TABLE sandbox_orders ADD COLUMN owner_ref TEXT")
            if "receipt_emailed" not in fields:
                db.execute("ALTER TABLE sandbox_orders ADD COLUMN receipt_emailed INTEGER NOT NULL DEFAULT 0")
            if "receipt_recipient" not in fields:
                db.execute("ALTER TABLE sandbox_orders ADD COLUMN receipt_recipient TEXT")
            if "receipt_claimed_at" not in fields:
                db.execute("ALTER TABLE sandbox_orders ADD COLUMN receipt_claimed_at INTEGER")
            if "receipt_claim_token" not in fields:
                db.execute("ALTER TABLE sandbox_orders ADD COLUMN receipt_claim_token TEXT")
            if "paid_webhook_received" not in fields:
                db.execute("ALTER TABLE sandbox_orders ADD COLUMN paid_webhook_received INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def _connect(self):
        try:
            db = sqlite3.connect(str(self.path), timeout=5)
            try:
                with db:
                    yield db
            finally:
                db.close()
        except (sqlite3.Error, OSError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def save(self, order: object) -> dict:
        with self._connect() as db:
            row = db.execute("""
                INSERT INTO sandbox_orders (
                    order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient, paid_webhook_received
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=CASE
                        WHEN sandbox_orders.status IN ('refunded', 'chargeback')
                            THEN sandbox_orders.status
                        WHEN sandbox_orders.status = 'paid'
                            AND excluded.status IN ('created', 'processing', 'expired', 'canceled')
                            THEN sandbox_orders.status
                        ELSE excluded.status END,
                    webhook_received=MAX(sandbox_orders.webhook_received, excluded.webhook_received),
                    paid_webhook_received=MAX(sandbox_orders.paid_webhook_received, excluded.paid_webhook_received),
                    receipt_emailed=MAX(sandbox_orders.receipt_emailed, excluded.receipt_emailed),
                    updated_at=unixepoch()
                WHERE sandbox_orders.plan_id = excluded.plan_id
                  AND sandbox_orders.amount = excluded.amount
                  AND sandbox_orders.payment_id = excluded.payment_id
                  AND sandbox_orders.mode = excluded.mode
                  AND sandbox_orders.owner_ref IS excluded.owner_ref
                  AND sandbox_orders.receipt_recipient IS excluded.receipt_recipient
                RETURNING order_id, plan_id, amount, payment_id, status, mode,
                    webhook_received, owner_ref, receipt_emailed, receipt_recipient,
                    paid_webhook_received
            """, (
                order.order_id, order.plan_id, order.amount, order.payment_id,
                order.status, order.mode, int(order.webhook_received),
                getattr(order, "owner_ref", None),
                int(getattr(order, "receipt_emailed", False)),
                getattr(order, "receipt_recipient", None),
                int(getattr(order, "paid_webhook_received", False)),
            )).fetchone()
            if row is None:
                raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")
            result = dict(zip(ORDER_FIELDS, row, strict=True))
        return result

    def attach_provider_payment(self, order: object, *, pending_payment_id: str) -> None:
        if (not pending_payment_id.startswith("pending:")
                or order.payment_id.startswith("pending:")
                or order.status not in {"created", "processing"}
                or order.mode != "provider"):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")
        with self._connect() as db:
            row = db.execute("""
                UPDATE sandbox_orders SET payment_id = ?, status = ?, updated_at = unixepoch()
                WHERE order_id = ? AND payment_id = ? AND plan_id = ?
                  AND amount = ? AND mode = 'provider' AND owner_ref IS ?
                  AND status = 'created' AND webhook_received = 0
                  AND paid_webhook_received = 0
                RETURNING order_id
            """, (
                order.payment_id, order.status, order.order_id,
                pending_payment_id, order.plan_id, order.amount,
                getattr(order, "owner_ref", None),
            )).fetchone()
            if row is None:
                raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")

    def load(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient, paid_webhook_received
                  FROM sandbox_orders ORDER BY updated_at DESC, rowid DESC
            """).fetchall()
        return [
            dict(zip(ORDER_FIELDS, row, strict=True))
            for row in rows
        ]

    def load_one(self, order_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("""
                SELECT order_id, plan_id, amount, payment_id, status, mode,
                    webhook_received, owner_ref, receipt_emailed, receipt_recipient,
                    paid_webhook_received
                FROM sandbox_orders WHERE order_id = ?
            """, (order_id,)).fetchone()
        return dict(zip(ORDER_FIELDS, row, strict=True)) if row else None

    def load_for_owner(self, owner_ref: str, *, signed_paid_only: bool = False) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT order_id, plan_id, amount, payment_id, status, mode,
                    webhook_received, owner_ref, receipt_emailed, receipt_recipient,
                    paid_webhook_received
                FROM sandbox_orders WHERE owner_ref = ?
                  AND (? = 0 OR (status = 'paid' AND paid_webhook_received = 1))
                ORDER BY updated_at DESC, rowid DESC LIMIT 20
            """, (owner_ref, int(signed_paid_only))).fetchall()
        return [dict(zip(ORDER_FIELDS, row, strict=True)) for row in rows]

    def claim_receipt(self, order_id: str, *, claim_token: str) -> str | None:
        with self._connect() as db:
            row = db.execute("""
                UPDATE sandbox_orders
                SET receipt_claimed_at = unixepoch(), receipt_claim_token = ?
                WHERE order_id = ? AND mode = 'provider' AND status = 'paid'
                  AND webhook_received = 1 AND receipt_emailed = 0
                  AND paid_webhook_received = 1
                  AND owner_ref IS NOT NULL AND receipt_recipient IS NOT NULL
                  AND (receipt_claimed_at IS NULL OR
                       receipt_claimed_at < unixepoch() - 120)
                RETURNING receipt_recipient
            """, (claim_token, order_id)).fetchone()
        return str(row[0]) if row else None

    def finish_receipt(self, order_id: str, *, claim_token: str) -> bool:
        with self._connect() as db:
            row = db.execute("""
                UPDATE sandbox_orders
                SET receipt_emailed = 1, receipt_claimed_at = NULL,
                        receipt_claim_token = NULL,
                    updated_at = unixepoch()
                WHERE order_id = ? AND status = 'paid' AND webhook_received = 1
                  AND paid_webhook_received = 1
                  AND receipt_claimed_at IS NOT NULL
                  AND receipt_claim_token = ?
                RETURNING order_id
            """, (order_id, claim_token)).fetchone()
        return row is not None

    def release_receipt(self, order_id: str, *, claim_token: str) -> None:
        with self._connect() as db:
            db.execute("""
                UPDATE sandbox_orders
                SET receipt_claimed_at = NULL, receipt_claim_token = NULL
                WHERE order_id = ? AND receipt_emailed = 0 AND receipt_claim_token = ?
            """, (order_id, claim_token))
