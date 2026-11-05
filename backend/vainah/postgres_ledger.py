"""PostgreSQL storage for operator-only SANDBOX orders.

Never stores a subscription link, payment URL, merchant API key or user account.
This table is intentionally separate from any future production order ledger.
"""
from __future__ import annotations

import psycopg

LOCK_TIMEOUT_MS = 4000
STATEMENT_TIMEOUT_MS = 8000
ORDER_COLUMNS = (
    "order_id", "plan_id", "amount", "payment_id", "status", "mode",
    "webhook_received", "owner_ref", "receipt_emailed", "receipt_recipient",
    "paid_webhook_received",
)


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
        # connect_timeout bounds only opening the connection. Bound waiting for
        # advisory/table/row locks and executing statements as well, so a stuck
        # migration or worker returns a retryable failure instead of hanging API.
        cursor.execute("""
            SELECT set_config('lock_timeout', %s, TRUE),
                   set_config('statement_timeout', %s, TRUE)
        """, (f"{LOCK_TIMEOUT_MS}ms", f"{STATEMENT_TIMEOUT_MS}ms"))
        # IF NOT EXISTS alone can race on pg_type when fresh Render workers
        # initialize simultaneously. Hold one transaction-scoped schema lock
        # through migration and the operation; PostgreSQL releases it on either
        # commit or rollback. Different test/application schemas stay isolated.
        cursor.execute("""
            SELECT pg_advisory_xact_lock(1447960897, hashtext(current_schema()))
        """)
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
            ADD COLUMN IF NOT EXISTS paid_webhook_received BOOLEAN NOT NULL DEFAULT FALSE
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
        cursor.execute("""
            ALTER TABLE vainah_sandbox_orders
            ADD COLUMN IF NOT EXISTS receipt_claim_token TEXT
        """)

    def save(self, order: object) -> dict:
        """Commit a monotonic update and return the actual persisted outcome.

        A stale process must observe a concurrently committed refund, rather
        than reporting its proposed PAID state or mutating another payment's
        signed proof after an immutable binding mismatch.
        """
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    INSERT INTO vainah_sandbox_orders
                        (order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient, paid_webhook_received)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        paid_webhook_received = (
                            vainah_sandbox_orders.paid_webhook_received
                            OR EXCLUDED.paid_webhook_received
                        ),
                        receipt_emailed = (
                            vainah_sandbox_orders.receipt_emailed
                            OR EXCLUDED.receipt_emailed
                        ),
                        updated_at = NOW()
                    WHERE vainah_sandbox_orders.plan_id = EXCLUDED.plan_id
                      AND vainah_sandbox_orders.amount = EXCLUDED.amount
                      AND vainah_sandbox_orders.payment_id = EXCLUDED.payment_id
                      AND vainah_sandbox_orders.mode = EXCLUDED.mode
                      AND vainah_sandbox_orders.owner_ref
                          IS NOT DISTINCT FROM EXCLUDED.owner_ref
                      AND vainah_sandbox_orders.receipt_recipient
                          IS NOT DISTINCT FROM EXCLUDED.receipt_recipient
                    RETURNING order_id, plan_id, amount, payment_id, status, mode,
                              webhook_received, owner_ref, receipt_emailed,
                              receipt_recipient, paid_webhook_received
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
                    bool(getattr(order, "paid_webhook_received", False)),
                ))
                row = cursor.fetchone()
                if row is None:
                    raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")
                return dict(zip(ORDER_COLUMNS, row, strict=True))
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def attach_provider_payment(self, order: object, *, pending_payment_id: str) -> None:
        """Bind one provider response to an order reserved before the network POST.

        An early callback sees a durable pending record and can retry. Only the
        worker holding its exact reservation can attach the immutable payment ID;
        no callback, stale cache, or second response may replace that binding.
        """
        if (not pending_payment_id.startswith("pending:")
                or order.payment_id.startswith("pending:")
                or order.status not in {"created", "processing"}
                or order.mode != "provider"):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    UPDATE vainah_sandbox_orders
                    SET payment_id = %s, status = %s, updated_at = NOW()
                    WHERE order_id = %s AND payment_id = %s
                      AND plan_id = %s AND amount = %s AND mode = 'provider'
                      AND owner_ref IS NOT DISTINCT FROM %s
                      AND status = 'created'
                      AND webhook_received = FALSE
                      AND paid_webhook_received = FALSE
                    RETURNING order_id
                """, (
                    order.payment_id, order.status, order.order_id,
                    pending_payment_id, order.plan_id, order.amount,
                    getattr(order, "owner_ref", None),
                ))
                if cursor.fetchone() is None:
                    raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def load(self) -> list[dict]:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    SELECT order_id, plan_id, amount, payment_id, status, mode, webhook_received, owner_ref, receipt_emailed, receipt_recipient, paid_webhook_received
                    FROM vainah_sandbox_orders
                    ORDER BY updated_at, order_id
                    LIMIT 5000
                """)
                rows = cursor.fetchall()
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

        return [
            dict(zip(
                ("order_id", "plan_id", "amount", "payment_id", "status", "mode", "webhook_received", "owner_ref", "receipt_emailed", "receipt_recipient", "paid_webhook_received"),
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
                           receipt_recipient, paid_webhook_received
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
            "receipt_recipient", "paid_webhook_received",
        ), row, strict=True))

    def load_for_owner(
        self, owner_ref: str, *, signed_paid_only: bool = False,
    ) -> list[dict]:
        """Read the owner's recent orders from shared storage on every request."""
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    SELECT order_id, plan_id, amount, payment_id, status,
                           mode, webhook_received, owner_ref, receipt_emailed,
                           receipt_recipient, paid_webhook_received
                    FROM vainah_sandbox_orders
                    WHERE owner_ref = %s
                      AND (NOT %s OR (status = 'paid' AND paid_webhook_received = TRUE))
                    ORDER BY updated_at DESC, order_id DESC
                    LIMIT 20
                """, (owner_ref, signed_paid_only))
                rows = cursor.fetchall()
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None
        return [dict(zip((
            "order_id", "plan_id", "amount", "payment_id", "status",
            "mode", "webhook_received", "owner_ref", "receipt_emailed",
            "receipt_recipient", "paid_webhook_received",
        ), row, strict=True)) for row in rows]

    def claim_receipt(self, order_id: str, *, claim_token: str) -> str | None:
        """Cross-worker lease; only signed PAID test orders can claim an email."""
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    UPDATE vainah_sandbox_orders
                    SET receipt_claimed_at = NOW(), receipt_claim_token = %s
                    WHERE order_id = %s AND mode = 'provider'
                      AND status = 'paid' AND paid_webhook_received = TRUE
                      AND owner_ref IS NOT NULL AND receipt_recipient IS NOT NULL
                      AND receipt_emailed = FALSE
                      AND (receipt_claimed_at IS NULL OR
                           receipt_claimed_at < NOW() - interval '2 minutes')
                    RETURNING receipt_recipient
                """, (claim_token, order_id))
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def finish_receipt(self, order_id: str, *, claim_token: str) -> bool:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    UPDATE vainah_sandbox_orders
                    SET receipt_emailed = TRUE,
                        receipt_claimed_at = NULL, receipt_claim_token = NULL,
                        updated_at = NOW()
                    WHERE order_id = %s AND status = 'paid'
                      AND paid_webhook_received = TRUE AND receipt_claimed_at IS NOT NULL
                      AND receipt_claim_token = %s
                    RETURNING order_id
                """, (order_id, claim_token))
                return cursor.fetchone() is not None
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None

    def release_receipt(self, order_id: str, *, claim_token: str) -> None:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as connection, connection.cursor() as cursor:
                self._schema(cursor)
                cursor.execute("""
                    UPDATE vainah_sandbox_orders
                    SET receipt_claimed_at = NULL, receipt_claim_token = NULL
                    WHERE order_id = %s AND receipt_emailed = FALSE
                      AND receipt_claim_token = %s
                """, (order_id, claim_token))
        except (psycopg.Error, OSError, ValueError):
            raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE") from None
