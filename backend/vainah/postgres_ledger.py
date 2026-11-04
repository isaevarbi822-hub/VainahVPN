"""PostgreSQL storage for operator-only SANDBOX orders.

Never stores a subscription link, payment URL, merchant API key or user account.
This table is intentionally separate from any future production order ledger.
"""
from __future__ import annotations

import psycopg


class LedgerUnavailable(Exception):
    """Database failure without a connection string or private details."""


class PostgresSandboxLedger:
    TABLE = "vainah_sandbox_orders"

    def __init__(self, database_url: str):
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("POSTGRES_URL_INVALID")
        self._database_url = database_url

    @staticmethod
    def _schema(cursor) -> None:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vainah_sandbox_orders (
                order_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                amount TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('mock', 'provider')),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            ALTER TABLE vainah_sandbox_orders
            ADD COLUMN IF NOT EXISTS webhook_received BOOLEAN NOT NULL DEFAULT FALSE
        """)
        cursor.execute("""
            ALTER TABLE vainah_sandbox_orders
            ADD COLUMN IF NOT EXISTS owner_ref TEXT
        """)

    def save(self, order: object) -> None:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    INSERT INTO vainah_sandbox_orders
                        (order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        webhook_received = EXCLUDED.webhook_received,
                        updated_at = NOW()
                """, (
                    order.order_id,
                    order.plan_id,
                    order.amount,
                    order.payment_id,
                    order.status,
                    order.mode,
                    order.webhook_received,
                    getattr(order, "owner_ref", None),
                ))
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def load(self) -> list[dict]:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    SELECT order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref
                    FROM vainah_sandbox_orders
                    ORDER BY updated_at, order_id
                    LIMIT 5000
                """)
                rows = cursor.fetchall()
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

        return [
            dict(zip(
                ("order_id", "plan_id", "amount", "payment_id", "status", "mode", "webhook_received", "owner_ref"),
                row,
                strict=True,
            ))
            for row in rows
        ]
