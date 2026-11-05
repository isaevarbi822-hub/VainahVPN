"""Durable, single-claim PostgreSQL foundation for future LIVE orders.

This is intentionally NOT wired to public checkout or RollyPay live callbacks.
A real H1Cloud write can be non-idempotent; once a claim is acquired it is
never automatically released, even on timeout. Operators must reconcile
uncertain node writes before deciding on a retry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from uuid import uuid4

import psycopg
from cryptography.fernet import Fernet, InvalidToken

from .billing import PAYMENT_ID_RE, get_plan, price_rub, verify_signature
from .production_contracts import (
    LIVE_ORDER_RE,
    LiveContractError,
    LiveOrderContract,
    verify_live_paid_event,
    verify_live_reversal_event,
)

LOCK_TIMEOUT_MS = 4000
STATEMENT_TIMEOUT_MS = 8000


class LiveLedgerError(Exception):
    """A public-safe code; PostgreSQL query text and secrets are never exposed."""


def _cipher() -> Fernet:
    key = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(key) < 32:
        raise LiveLedgerError("LIVE_ENCRYPTION_UNAVAILABLE")
    digest = hmac.new(
        key.encode(), b"vainah-live-order-cipher-v1", hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal_live_secret(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise LiveLedgerError("LIVE_SECRET_INVALID")
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def unseal_live_secret(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (ValueError, InvalidToken, UnicodeError):
        raise LiveLedgerError("LIVE_SECRET_UNAVAILABLE") from None


@dataclass(frozen=True)
class PendingLiveOrder:
    order_id: str
    owner_ref: str
    plan_id: str
    amount_rub: str
    payment_id: str | None
    payment_state: str
    delivery_state: str


class PostgresLiveOrderLedger:
    """Separate from sandbox: unique payments, atomic claims, no blind retries."""

    def __init__(self, database_url: str):
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise LiveLedgerError("LIVE_POSTGRES_REQUIRED")
        self._database_url = database_url

    @staticmethod
    def _schema(cur) -> None:
        # Connection timeouts do not bound waiting for a query or another
        # worker's locks. These limits apply only to the current transaction.
        cur.execute("""
            SELECT set_config('lock_timeout', %s, TRUE),
                   set_config('statement_timeout', %s, TRUE)
        """, (f"{LOCK_TIMEOUT_MS}ms", f"{STATEMENT_TIMEOUT_MS}ms"))
        # IF NOT EXISTS alone does not serialize PostgreSQL's catalog writes.
        # The lock lasts until the caller commits its first reservation/read,
        # and is always released before any external payment or VPN request.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_live_orders_schema'))")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vainah_live_orders (
                order_id VARCHAR(50) PRIMARY KEY,
                owner_ref VARCHAR(67) NOT NULL,
                plan_id VARCHAR(24) NOT NULL,
                amount_rub NUMERIC(12,2) NOT NULL,
                payment_id VARCHAR(128) UNIQUE,
                receipt_email_cipher TEXT NOT NULL,
                subscription_cipher TEXT,
                payment_state TEXT NOT NULL DEFAULT 'reserved'
                    CHECK (payment_state IN (
                        'reserved', 'created', 'paid', 'refunded', 'chargeback'
                    )),
                delivery_state TEXT NOT NULL DEFAULT 'pending'
                    CHECK (delivery_state IN (
                        'pending', 'claimed', 'delivered', 'manual_review'
                    )),
                webhook_at TIMESTAMPTZ,
                claimed_at TIMESTAMPTZ,
                delivered_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute("""
            ALTER TABLE vainah_live_orders
            ADD COLUMN IF NOT EXISTS checkout_nonce_hash CHAR(64)
        """)
        cur.execute("""
            ALTER TABLE vainah_live_orders
            ADD COLUMN IF NOT EXISTS pay_url_cipher TEXT
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS vainah_live_checkout_nonce_uq
            ON vainah_live_orders (checkout_nonce_hash)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS vainah_live_orders_owner_idx
            ON vainah_live_orders (owner_ref, created_at DESC)
        """)

    def reserve(self, *, owner_ref: str, verified_email: str,
                plan_id: str) -> str:
        """Called ONLY for an authenticated and verified server-side email."""
        plan = get_plan(plan_id)
        if plan is None or not isinstance(owner_ref, str):
            raise LiveLedgerError("LIVE_ORDER_INVALID")
        order_id = "vainah_live_" + uuid4().hex
        # Validate owner against the immutable signed callback contract.
        try:
            LiveOrderContract(order_id, plan_id, owner_ref, "pay_reserved000")
        except LiveContractError:
            raise LiveLedgerError("LIVE_OWNER_INVALID") from None
        if (not isinstance(verified_email, str)
                or len(verified_email) > 254 or verified_email.count("@") != 1):
            raise LiveLedgerError("LIVE_EMAIL_INVALID")
        recipient = seal_live_secret(verified_email.lower())
        try:
            with psycopg.connect(self._database_url, connect_timeout=4) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    INSERT INTO vainah_live_orders
                        (order_id, owner_ref, plan_id, amount_rub, receipt_email_cipher)
                    VALUES (%s, %s, %s, %s, %s)
                """, (order_id, owner_ref, plan_id, price_rub(plan), recipient))
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None
        return order_id


    def reserve_checkout(self, *, owner_ref: str, verified_email: str,
                         plan_id: str, idempotency_key: str) -> tuple[str, str | None]:
        """One durable invoice intent per browser-generated UUID, per owner.

        A pending intent is never retried automatically: an earlier gateway
        request might have succeeded before losing its response.
        """
        from uuid import UUID

        try:
            normalized = str(UUID(idempotency_key))
        except (ValueError, TypeError, AttributeError):
            raise LiveLedgerError("LIVE_IDEMPOTENCY_INVALID") from None
        if normalized != idempotency_key or len(idempotency_key) != 36:
            raise LiveLedgerError("LIVE_IDEMPOTENCY_INVALID")
        plan = get_plan(plan_id)
        if plan is None or not isinstance(owner_ref, str):
            raise LiveLedgerError("LIVE_ORDER_INVALID")
        try:
            LiveOrderContract(
                "vainah_live_" + uuid4().hex, plan_id, owner_ref,
                "pay_reserved000",
            )
        except LiveContractError:
            raise LiveLedgerError("LIVE_OWNER_INVALID") from None
        if not isinstance(verified_email, str) or not 5 <= len(verified_email) <= 254:
            raise LiveLedgerError("LIVE_EMAIL_INVALID")
        key = os.environ.get("SESSION_SIGNING_KEY", "")
        if len(key) < 32:
            raise LiveLedgerError("LIVE_ENCRYPTION_UNAVAILABLE")
        nonce_hash = hmac.new(
            key.encode(), ("vainah-live-idempotency-v1:" + owner_ref + ":" +
                           normalized).encode(), hashlib.sha256,
        ).hexdigest()
        order_id = "vainah_live_" + uuid4().hex
        recipient = seal_live_secret(verified_email.lower())
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    INSERT INTO vainah_live_orders (
                        order_id, owner_ref, plan_id, amount_rub,
                        receipt_email_cipher, checkout_nonce_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (checkout_nonce_hash) DO NOTHING
                    RETURNING order_id
                """, (order_id, owner_ref, plan_id, price_rub(plan),
                      recipient, nonce_hash))
                created = cur.fetchone()
                if created:
                    return created[0], None
                cur.execute("""
                    SELECT order_id, plan_id, owner_ref, payment_state,
                           pay_url_cipher
                    FROM vainah_live_orders
                    WHERE checkout_nonce_hash = %s
                """, (nonce_hash,))
                existing = cur.fetchone()
                if not existing or existing[1] != plan_id or existing[2] != owner_ref:
                    raise LiveLedgerError("LIVE_IDEMPOTENCY_CONFLICT")
                if existing[3] == "created" and existing[4]:
                    return existing[0], unseal_live_secret(existing[4])
                raise LiveLedgerError("LIVE_CHECKOUT_RECONCILIATION_REQUIRED")
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None

    def attach_hosted_invoice(self, *,
                              order_id: str, payment_id: str, pay_url: str) -> bool:
        """Atomically persist validated hosted URL and provider payment ID."""
        from .billing import safe_pay_url

        if (not LIVE_ORDER_RE.fullmatch(order_id)
                or not PAYMENT_ID_RE.fullmatch(payment_id)):
            raise LiveLedgerError("LIVE_PAYMENT_INVALID")
        try:
            safe_pay_url(pay_url)
        except ValueError:
            raise LiveLedgerError("LIVE_PAYMENT_URL_INVALID") from None
        ciphertext = seal_live_secret(pay_url)
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    UPDATE vainah_live_orders
                    SET payment_id = %s, pay_url_cipher = %s,
                        payment_state = 'created', updated_at = now()
                    WHERE order_id = %s
                        AND payment_id IS NULL AND payment_state = 'reserved'
                    RETURNING order_id
                """, (payment_id, ciphertext, order_id))
                return cur.fetchone() is not None
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None

    def owner_orders(self, owner_ref: str) -> list[dict]:
        """Never disclose another account's orders or any payment credentials."""
        if not isinstance(owner_ref, str) or not owner_ref.startswith("v1_"):
            raise LiveLedgerError("LIVE_OWNER_INVALID")
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    SELECT order_id, plan_id, amount_rub,
                           payment_state, delivery_state, created_at
                    FROM vainah_live_orders
                    WHERE owner_ref = %s ORDER BY created_at DESC LIMIT 30
                """, (owner_ref,))
                rows = cur.fetchall()
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None
        return [{
            "order_id": row[0], "plan_id": row[1],
            "amount_rub": str(row[2]), "payment_state": row[3],
            "delivery_state": row[4],
            "created_at": row[5].isoformat(),
        } for row in rows]

    def owner_subscription_url(self, owner_ref: str) -> str | None:
        """Decrypt link only after paid+delivered check for the same owner."""
        if not isinstance(owner_ref, str) or not owner_ref.startswith("v1_"):
            raise LiveLedgerError("LIVE_OWNER_INVALID")
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as conn, conn.cursor() as cur:
                self._schema(cur)
                # Block all access when a reversal of a previously delivered
                # profile is awaiting manual H1Cloud reconciliation.
                cur.execute("""
                    SELECT 1 FROM vainah_live_orders
                    WHERE owner_ref = %s
                        AND payment_state IN ('refunded', 'chargeback')
                        AND delivery_state = 'manual_review'
                    LIMIT 1
                """, (owner_ref,))
                if cur.fetchone() is not None:
                    return None
                cur.execute("""
                    SELECT subscription_cipher FROM vainah_live_orders
                    WHERE owner_ref = %s AND payment_state = 'paid'
                        AND delivery_state = 'delivered'
                        AND subscription_cipher IS NOT NULL
                    ORDER BY delivered_at DESC LIMIT 1
                """, (owner_ref,))
                row = cur.fetchone()
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None
        return unseal_live_secret(row[0]) if row else None

    def attach_invoice(self, order_id: str, payment_id: str) -> bool:
        if (not LIVE_ORDER_RE.fullmatch(order_id)
                or not PAYMENT_ID_RE.fullmatch(payment_id)):
            raise LiveLedgerError("LIVE_PAYMENT_INVALID")
        try:
            with psycopg.connect(self._database_url, connect_timeout=4) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    UPDATE vainah_live_orders
                    SET payment_id = %s, payment_state = 'created',
                        updated_at = now()
                    WHERE order_id = %s AND payment_id IS NULL
                        AND payment_state = 'reserved'
                    RETURNING order_id
                """, (payment_id, order_id))
                return cur.fetchone() is not None
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None

    def record_signed_paid(self, *, raw_body: bytes, timestamp: str | None,
                           signature: str | None, secret: str) -> bool:
        """Returns True if this paid event matches a saved live invoice.

        Duplicate paid events are harmless; they DO NOT run H1Cloud writes.
        """
        if len(raw_body) > 32768 or not verify_signature(
            raw_body, timestamp, signature, secret
        ):
            raise LiveLedgerError("LIVE_SIGNATURE_INVALID")
        try:
            data = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise LiveLedgerError("LIVE_WEBHOOK_INVALID") from None
        if not isinstance(data, dict):
            raise LiveLedgerError("LIVE_WEBHOOK_INVALID")
        order_id = data.get("order_id")
        if not isinstance(order_id, str) or not LIVE_ORDER_RE.fullmatch(order_id):
            raise LiveLedgerError("LIVE_ORDER_UNKNOWN")
        try:
            with psycopg.connect(self._database_url, connect_timeout=4) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    SELECT owner_ref, plan_id, payment_id, amount_rub, payment_state
                    FROM vainah_live_orders
                    WHERE order_id = %s FOR UPDATE
                """, (order_id,))
                record = cur.fetchone()
                if not record or not record[2]:
                    raise LiveLedgerError("LIVE_ORDER_UNKNOWN")
                contract = LiveOrderContract(
                    order_id, record[1], record[0], record[2],
                    amount_snapshot=str(record[3]),
                )
                try:
                    verify_live_paid_event(
                        raw_body, timestamp=timestamp, signature=signature,
                        signing_secret=secret, order=contract,
                    )
                except LiveContractError:
                    raise LiveLedgerError("LIVE_PAYMENT_MISMATCH") from None
                if record[4] in {"refunded", "chargeback"}:
                    # A valid late PAID replay cannot undo a reversal. Acknowledge
                    # it as stale without authorizing fulfillment or endless retries.
                    return False
                if record[4] == "paid":
                    return True
                if record[4] != "created":
                    raise LiveLedgerError("LIVE_PAYMENT_INVALID_STATE")
                cur.execute("""
                    UPDATE vainah_live_orders
                    SET payment_state = 'paid', webhook_at = now(),
                        updated_at = now()
                    WHERE order_id = %s
                """, (order_id,))
                return True
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None

    def record_signed_reversal(self, *, raw_body: bytes,
                               timestamp: str | None,
                               signature: str | None, secret: str) -> str:
        """Remove paid access to a refunded/charged-back order atomically.

        The H1 node is NOT modified here; a previously issued profile must
        be reconciled by an operator. No auto-retries of an H1 edit are safe.
        """
        if len(raw_body) > 32768 or not verify_signature(
            raw_body, timestamp, signature, secret
        ):
            raise LiveLedgerError("LIVE_SIGNATURE_INVALID")
        try:
            data = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise LiveLedgerError("LIVE_WEBHOOK_INVALID") from None
        if not isinstance(data, dict):
            raise LiveLedgerError("LIVE_WEBHOOK_INVALID")
        order_id = data.get("order_id")
        if not isinstance(order_id, str) or not LIVE_ORDER_RE.fullmatch(order_id):
            raise LiveLedgerError("LIVE_ORDER_UNKNOWN")
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    SELECT owner_ref, plan_id, payment_id,
                           amount_rub, payment_state
                    FROM vainah_live_orders WHERE order_id = %s
                    FOR UPDATE
                """, (order_id,))
                record = cur.fetchone()
                if not record or not record[2]:
                    raise LiveLedgerError("LIVE_ORDER_UNKNOWN")
                contract = LiveOrderContract(
                    order_id, record[1], record[0], record[2],
                    amount_snapshot=str(record[3]),
                )
                try:
                    new_state = verify_live_reversal_event(
                        raw_body, timestamp=timestamp, signature=signature,
                        signing_secret=secret, order=contract,
                    )
                except LiveContractError:
                    raise LiveLedgerError("LIVE_PAYMENT_MISMATCH") from None
                if record[4] == "chargeback":
                    return "chargeback"
                if record[4] == new_state:
                    return new_state
                if record[4] not in {"created", "paid", "refunded"}:
                    raise LiveLedgerError("LIVE_PAYMENT_INVALID_STATE")
                cur.execute("""
                    UPDATE vainah_live_orders
                    SET payment_state = %s,
                        delivery_state = CASE
                            WHEN delivery_state IN ('claimed', 'delivered')
                            THEN 'manual_review'
                            ELSE delivery_state
                        END,
                        updated_at = now()
                    WHERE order_id = %s
                """, (new_state, order_id))
                return new_state
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None


    def claim_delivery_once(self, order_id: str) -> PendingLiveOrder | None:
        """One atomic claim per order across any number of Render workers.

        Claimed orders are intentionally never re-claimed on a timeout; node
        PATCH could already have extended an account before the worker died.
        """
        if not LIVE_ORDER_RE.fullmatch(order_id):
            raise LiveLedgerError("LIVE_ORDER_INVALID")
        try:
            with psycopg.connect(self._database_url, connect_timeout=4) as conn, conn.cursor() as cur:
                self._schema(cur)
                # Orders for the same owner map to one stable H1 profile.
                # Serializing only order_id would let two different payments
                # create/edit that profile simultaneously. Hold a per-owner
                # transaction lock for the claim decision; the persisted state
                # then excludes sibling claims throughout the external write.
                cur.execute("""
                    SELECT pg_advisory_xact_lock(
                        hashtext('vainah_live_order_owner'), hashtext(owner_ref)
                    )
                    FROM vainah_live_orders WHERE order_id = %s
                """, (order_id,))
                cur.execute("""
                    UPDATE vainah_live_orders AS target
                    SET delivery_state = 'claimed', claimed_at = now(),
                        updated_at = now()
                    WHERE order_id = %s
                        AND payment_state = 'paid'
                        AND webhook_at IS NOT NULL
                        AND delivery_state = 'pending'
                        AND NOT EXISTS (
                            SELECT 1 FROM vainah_live_orders blocked
                            WHERE blocked.owner_ref = target.owner_ref
                              AND blocked.order_id <> target.order_id
                              AND blocked.delivery_state IN ('claimed', 'manual_review')
                        )
                    RETURNING order_id, owner_ref, plan_id, amount_rub,
                              payment_id, payment_state, delivery_state
                """, (order_id,))
                record = cur.fetchone()
                if record is None:
                    return None
                return PendingLiveOrder(
                    record[0], record[1], record[2], str(record[3]),
                    record[4], record[5], record[6],
                )
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None

    def delivery_snapshot(self, order_id: str) -> dict | None:
        """Internal status for duplicate callbacks; never decrypts account data.

        A paid pending order blocked by another active claim needs a callback
        retry after that claim finishes. It must not be acknowledged as issued,
        nor confused with this order's own durable non-retryable write claim.
        """
        if not isinstance(order_id, str) or not LIVE_ORDER_RE.fullmatch(order_id):
            raise LiveLedgerError("LIVE_ORDER_INVALID")
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    SELECT target.payment_state, target.delivery_state,
                           target.webhook_at IS NOT NULL,
                           (
                               SELECT blocked.delivery_state
                               FROM vainah_live_orders blocked
                               WHERE blocked.owner_ref = target.owner_ref
                                 AND blocked.order_id <> target.order_id
                                 AND blocked.delivery_state IN ('claimed', 'manual_review')
                               ORDER BY (blocked.delivery_state = 'manual_review') DESC
                               LIMIT 1
                           )
                    FROM vainah_live_orders target
                    WHERE target.order_id = %s
                """, (order_id,))
                row = cur.fetchone()
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None
        if row is None:
            return None
        return {
            "payment_state": row[0], "delivery_state": row[1],
            "signed_paid": bool(row[2]), "owner_block": row[3],
        }

    def claimed_verified_email(self, *, order_id: str, owner_ref: str) -> str:
        """Internal-only: reveal the reserved mailbox for a paid claimed order.

        Never expose the returned address through a public endpoint. The H1
        username is an HMAC of this server-verified email, not client input.
        """
        if (not LIVE_ORDER_RE.fullmatch(order_id)
                or not isinstance(owner_ref, str)
                or len(owner_ref) != 67
                or not owner_ref.startswith("v1_")):
            raise LiveLedgerError("LIVE_CLAIM_INVALID")
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=4
            ) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    SELECT receipt_email_cipher
                    FROM vainah_live_orders AS target
                    WHERE order_id = %s
                        AND owner_ref = %s
                        AND payment_state = 'paid'
                        AND webhook_at IS NOT NULL
                        AND delivery_state = 'claimed'
                        AND NOT EXISTS (
                            SELECT 1 FROM vainah_live_orders blocked
                            WHERE blocked.owner_ref = target.owner_ref
                              AND blocked.order_id <> target.order_id
                              AND blocked.delivery_state = 'manual_review'
                        )
                """, (order_id, owner_ref))
                row = cur.fetchone()
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None
        if not row:
            raise LiveLedgerError("LIVE_CLAIM_NOT_FOUND")
        return unseal_live_secret(row[0])

    def mark_delivered(self, *, order_id: str, subscription_url: str,
                       panel_confirmed: bool = False) -> bool:
        """Never mark delivered from payment alone or without H1 verification."""
        from urllib.parse import urlsplit

        if not LIVE_ORDER_RE.fullmatch(order_id) or panel_confirmed is not True:
            raise LiveLedgerError("LIVE_DELIVERY_UNVERIFIED")
        parsed = urlsplit(subscription_url)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment
                or not 10 <= len(subscription_url) <= 2048):
            raise LiveLedgerError("LIVE_SUBSCRIPTION_URL_INVALID")
        encrypted_url = seal_live_secret(subscription_url)
        try:
            with psycopg.connect(self._database_url, connect_timeout=4) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    UPDATE vainah_live_orders AS target
                    SET delivery_state = 'delivered', subscription_cipher = %s,
                        delivered_at = now(), updated_at = now()
                    WHERE order_id = %s AND payment_state = 'paid'
                        AND webhook_at IS NOT NULL
                        AND delivery_state = 'claimed'
                        AND NOT EXISTS (
                            SELECT 1 FROM vainah_live_orders blocked
                            WHERE blocked.owner_ref = target.owner_ref
                              AND blocked.order_id <> target.order_id
                              AND blocked.delivery_state = 'manual_review'
                        )
                    RETURNING order_id
                """, (encrypted_url, order_id))
                return cur.fetchone() is not None
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None

    def mark_uncertain(self, order_id: str) -> bool:
        """Stop automation after an ambiguous H1Cloud write or postcheck."""
        if not LIVE_ORDER_RE.fullmatch(order_id):
            raise LiveLedgerError("LIVE_ORDER_INVALID")
        try:
            with psycopg.connect(self._database_url, connect_timeout=4) as conn, conn.cursor() as cur:
                self._schema(cur)
                cur.execute("""
                    UPDATE vainah_live_orders
                    SET delivery_state = 'manual_review', updated_at = now()
                    WHERE order_id = %s AND delivery_state = 'claimed'
                    RETURNING order_id
                """, (order_id,))
                return cur.fetchone() is not None
        except psycopg.Error:
            raise LiveLedgerError("LIVE_LEDGER_UNAVAILABLE") from None
