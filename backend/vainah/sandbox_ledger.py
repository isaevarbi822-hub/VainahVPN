"""Local-only durable ledger for SANDBOX test orders.

Not a production payments database. No identities, API keys, signing secrets,
VLESS subscriptions or payment links are stored here.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class SandboxLedger:
    def __init__(self, filename: str):
        self.path = Path(filename).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
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

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=5)

    def save(self, order: object) -> None:
        with self._connect() as db:
            db.execute("""
                INSERT INTO sandbox_orders (
                    order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=excluded.status,
                    webhook_received=excluded.webhook_received,
                    receipt_emailed=MAX(sandbox_orders.receipt_emailed, excluded.receipt_emailed),
                    updated_at=unixepoch()
            """, (
                order.order_id, order.plan_id, order.amount, order.payment_id,
                order.status, order.mode, int(order.webhook_received),
                getattr(order, "owner_ref", None),
                int(getattr(order, "receipt_emailed", False)),
                getattr(order, "receipt_recipient", None),
            ))

    def load(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient
                  FROM sandbox_orders ORDER BY updated_at DESC, rowid DESC
            """).fetchall()
        return [
            dict(zip(("order_id", "plan_id", "amount", "payment_id",
                      "status", "mode", "webhook_received", "owner_ref", "receipt_emailed", "receipt_recipient"), row))
            for row in rows
        ]

    def claim_receipt(self, order_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute("""
                UPDATE sandbox_orders SET receipt_claimed_at = unixepoch()
                WHERE order_id = ? AND mode = 'provider' AND status = 'paid'
                  AND webhook_received = 1 AND receipt_emailed = 0
                  AND owner_ref IS NOT NULL AND receipt_recipient IS NOT NULL
                  AND (receipt_claimed_at IS NULL OR
                       receipt_claimed_at < unixepoch() - 120)
                RETURNING receipt_recipient
            """, (order_id,)).fetchone()
        return str(row[0]) if row else None

    def finish_receipt(self, order_id: str) -> None:
        with self._connect() as db:
            db.execute("""
                UPDATE sandbox_orders
                SET receipt_emailed = 1, receipt_claimed_at = NULL,
                    updated_at = unixepoch()
                WHERE order_id = ? AND status = 'paid' AND webhook_received = 1
                  AND receipt_claimed_at IS NOT NULL
            """, (order_id,))

    def release_receipt(self, order_id: str) -> None:
        with self._connect() as db:
            db.execute("""
                UPDATE sandbox_orders SET receipt_claimed_at = NULL
                WHERE order_id = ? AND receipt_emailed = 0
            """, (order_id,))
