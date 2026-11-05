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
        cursor.execute("""
            ALTER TABLE vainah_sandbox_orders
            ADD COLUMN IF NOT EXISTS receipt_emailed BOOLEAN NOT NULL DEFAULT FALSE
        """)
        cursor.execute("""
            ALTER TABLE vainah_sandbox_orders
            ADD COLUMN IF NOT EXISTS receipt_recipient TEXT
        """)
        cursor.execute("""
            ALTER TABLE vainah_sandbox_orders
            ADD COLUMN IF NOT EXISTS receipt_claimed_at TIMESTAMPTZ
        """)

    def save(self, order: object) -> None:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    INSERT INTO vainah_sandbox_orders
                        (order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_id) DO UPDATE SET
                        -- Another Render worker may hold a stale in-memory
                        -- snapshot. Never erase signed callback proof or a
                        -- terminal paid/refund outcome with older polling data.
                        status = CASE
                            WHEN vainah_sandbox_orders.status IN
                                ('refunded', 'chargeback')
                                THEN vainah_sandbox_orders.status
                            WHEN vainah_sandbox_orders.status = 'paid'
                                 AND EXCLUDED.status IN (
                                     'created', 'processing', 'expired', 'canceled'
                                 ) THEN vainah_sandbox_orders.status
                            ELSE EXCLUDED.status
                        END,
                        webhook_received = (
                            vainah_sandbox_orders.webhook_received
                            OR EXCLUDED.webhook_received
                        ),
                        receipt_emailed = (
                            vainah_sandbox_orders.receipt_emailed
                            OR EXCLUDED.receipt_emailed
                        ),
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
                    bool(getattr(order, "receipt_emailed", False)),
                    getattr(order, "receipt_recipient", None),
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
                    SELECT order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient
                    FROM vainah_sandbox_orders
                    ORDER BY updated_at, order_id
                    LIMIT 5000
                """)
                rows = cursor.fetchall()
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

        return [
            dict(zip(
                ("order_id", "plan_id", "amount", "payment_id", "status", "mode", "webhook_received", "owner_ref", "receipt_emailed", "receipt_recipient"),
                row,
                strict=True,
            ))
            for row in rows
        ]

    def load_one(self, order_id: str) -> dict | None:
        """Find a just-created order across multiple independent Render workers.

        The process-local snapshot is only a cache; a signed webhook must not
        fail because a different worker created the test payment.
        """
        if not isinstance(order_id, str) or len(order_id) > 80:
            return None
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    SELECT order_id, plan_id, amount, payment_id, status,
                           mode, webhook_received, owner_ref, receipt_emailed,
                           receipt_recipient
                    FROM vainah_sandbox_orders
                    WHERE order_id = %s
                """, (order_id,))
                row = cursor.fetchone()
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None
        if row is None:
            return None
        return dict(zip((
            "order_id", "plan_id", "amount", "payment_id", "status",
            "mode", "webhook_received", "owner_ref", "receipt_emailed",
            "receipt_recipient",
        ), row, strict=True))

    def claim_receipt(self, order_id: str) -> str | None:
        """Cross-worker lease; only signed PAID test orders can claim an email."""
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    UPDATE vainah_sandbox_orders
                    SET receipt_claimed_at = NOW()
                    WHERE order_id = %s AND mode = 'provider'
                      AND status = 'paid' AND webhook_received = TRUE
                      AND owner_ref IS NOT NULL AND receipt_recipient IS NOT NULL
                      AND receipt_emailed = FALSE
                      AND (receipt_claimed_at IS NULL OR
                           receipt_claimed_at < NOW() - interval '2 minutes')
                    RETURNING receipt_recipient
                """, (order_id,))
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def finish_receipt(self, order_id: str) -> None:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    UPDATE vainah_sandbox_orders
                    SET receipt_emailed = TRUE,
                        receipt_claimed_at = NULL,
                        updated_at = NOW()
                    WHERE order_id = %s AND status = 'paid'
                      AND webhook_received = TRUE AND receipt_claimed_at IS NOT NULL
                """, (order_id,))
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def release_receipt(self, order_id: str) -> None:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    UPDATE vainah_sandbox_orders
                    SET receipt_claimed_at = NULL
                    WHERE order_id = %s AND receipt_emailed = FALSE
                """, (order_id,))
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None
