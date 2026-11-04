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
)


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
        except (ValueError, UnicodeDecodeError):
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
                    raise LiveLedgerError("LIVE_PAYMENT_ALREADY_REVERSED")
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
                cur.execute("""
                    UPDATE vainah_live_orders
                    SET delivery_state = 'claimed', claimed_at = now(),
                        updated_at = now()
                    WHERE order_id = %s
                        AND payment_state = 'paid'
                        AND delivery_state = 'pending'
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
                    FROM vainah_live_orders
                    WHERE order_id = %s
                        AND owner_ref = %s
                        AND payment_state = 'paid'
                        AND delivery_state = 'claimed'
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
                    UPDATE vainah_live_orders
                    SET delivery_state = 'delivered', subscription_cipher = %s,
                        delivered_at = now(), updated_at = now()
                    WHERE order_id = %s AND payment_state = 'paid'
                        AND delivery_state = 'claimed'
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
