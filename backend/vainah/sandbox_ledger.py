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

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=5)

    def save(self, order: object) -> None:
        with self._connect() as db:
            db.execute("""
                INSERT INTO sandbox_orders (
                    order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=excluded.status,
                    webhook_received=excluded.webhook_received,
                    receipt_emailed=excluded.receipt_emailed,
                    updated_at=unixepoch()
            """, (
                order.order_id, order.plan_id, order.amount, order.payment_id,
                order.status, order.mode, int(order.webhook_received),
                getattr(order, "owner_ref", None),
                int(getattr(order, "receipt_emailed", False)),
            ))

    def load(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed
                  FROM sandbox_orders ORDER BY updated_at DESC, rowid DESC
            """).fetchall()
        return [
            dict(zip(("order_id", "plan_id", "amount", "payment_id",
                      "status", "mode", "webhook_received", "owner_ref", "receipt_emailed"), row))
            for row in rows
        ]
