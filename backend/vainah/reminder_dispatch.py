"""Opt-in renewal email dispatcher, disabled unless explicitly configured.

Uses the paid LIVE ledger only, rechecks H1Cloud and locks each reminder
revision in PostgreSQL. Never includes subscription URLs or payment secrets.
The operator endpoint is for trusted scheduling infrastructure only.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime

import psycopg
from fastapi import APIRouter, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from .email_delivery import database_url, email_service_ready, send_email
from .h1_panel import H1PanelError, read_h1_issued_client_status
from .live_checkout import owner_ref_for_email
from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger, unseal_live_secret
from .production_contracts import LiveContractError, h1_provision_intent
from .reminder_preferences import _schema as preference_schema

router = APIRouter(prefix="/api/internal/reminders", tags=["Scheduled reminders"])
WINDOWS = (7, 3, 1)


def enabled() -> bool:
    return os.environ.get("VAINAH_REMINDER_DELIVERY_ENABLED") == "true"


def require_runner(token: str | None) -> None:
    expected = os.environ.get("VAINAH_REMINDER_RUNNER_KEY", "")
    signing = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(expected) < 40 or expected == signing:
        raise HTTPException(503, "REMINDER_RUNNER_NOT_CONFIGURED")
    if not token or len(token) > 256 or not hmac.compare_digest(token, expected):
        raise HTTPException(403, "REMINDER_RUNNER_FORBIDDEN")


def threshold(expires: datetime, now: datetime) -> int | None:
    if expires.tzinfo is None or now.tzinfo is None:
        return None
    seconds = (expires - now).total_seconds()
    if seconds <= 0:
        return None
    for day in (1, 3, 7):
        if seconds <= day * 86400:
            return day
    return None


def _schema(cur) -> None:
    preference_schema(cur)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_reminder_deliveries (
            owner_hash CHAR(64) NOT NULL,
            expiry_at TIMESTAMPTZ NOT NULL,
            threshold_days SMALLINT NOT NULL CHECK (threshold_days IN (1,3,7)),
            state VARCHAR(12) NOT NULL CHECK (state IN ('claimed','sent')),
            claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            sent_at TIMESTAMPTZ,
            PRIMARY KEY (owner_hash, expiry_at, threshold_days)
        )
    """)


def _candidates() -> list[tuple]:
    """Only latest paid, delivered, non-reversed live orders can qualify."""
    with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
        PostgresLiveOrderLedger._schema(cur)
        _schema(cur)
        cur.execute("""
            WITH newest_delivery AS (
                SELECT DISTINCT ON (owner_ref)
                       owner_ref, receipt_email_cipher, h1_expires_at
                FROM vainah_live_orders
                WHERE payment_state='paid'
                  AND delivery_state='delivered'
                ORDER BY owner_ref, delivered_at DESC, created_at DESC
            )
            SELECT orders.owner_ref, orders.receipt_email_cipher,
                   orders.h1_expires_at
            FROM newest_delivery AS orders
            WHERE orders.h1_expires_at > now()
              AND orders.h1_expires_at <= now()+interval '7 days'
              AND NOT EXISTS (
                SELECT 1 FROM vainah_live_orders AS reversal
                WHERE reversal.owner_ref=orders.owner_ref
                  AND reversal.payment_state IN ('refunded','chargeback')
              )
            ORDER BY orders.h1_expires_at ASC LIMIT 15
        """)
        return cur.fetchall()


def _claim(owner_hash: str, expiry: datetime, days: int) -> bool:
    """An expired lease is not blindly retried to avoid duplicate emails."""
    with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
        _schema(cur)
        cur.execute("""
            INSERT INTO vainah_reminder_deliveries
                (owner_hash, expiry_at, threshold_days, state)
            SELECT %s,%s,%s,'claimed'
            WHERE EXISTS (
                SELECT 1 FROM vainah_reminder_preferences
                WHERE owner_hash=%s AND enabled=TRUE
            )
            ON CONFLICT DO NOTHING RETURNING owner_hash
        """, (owner_hash, expiry, days, owner_hash))
        return cur.fetchone() is not None


def _complete(owner_hash: str, expiry: datetime, days: int) -> None:
    with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
        _schema(cur)
        cur.execute("""
            UPDATE vainah_reminder_deliveries
            SET state='sent', sent_at=now()
            WHERE owner_hash=%s AND expiry_at=%s
              AND threshold_days=%s AND state='claimed'
        """, (owner_hash, expiry, days))


def _eligible(owner_hash: str, owner_ref: str, expiry: datetime) -> bool:
    """Recheck consent and paid, delivered, non-reversed live order before IO."""
    with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
        _schema(cur)
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM vainah_reminder_preferences
                WHERE owner_hash=%s AND enabled=TRUE
            ) AND EXISTS (
                SELECT 1 FROM vainah_live_orders
                WHERE owner_ref=%s AND payment_state='paid'
                  AND delivery_state='delivered' AND h1_expires_at=%s
            ) AND NOT EXISTS (
                SELECT 1 FROM vainah_live_orders WHERE owner_ref=%s
                  AND payment_state IN ('refunded','chargeback')
            )
        """, (owner_hash, owner_ref, expiry, owner_ref))
        return bool(cur.fetchone()[0])


async def run_batch() -> dict:
    if not enabled():
        return {"enabled": False, "checked": 0, "sent": 0}
    if not email_service_ready():
        raise HTTPException(503, "EMAIL_DELIVERY_NOT_CONFIGURED")
    signing = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(signing) < 32:
        raise HTTPException(503, "REMINDER_SERVICE_NOT_CONFIGURED")

    checked = sent = 0
    for owner_ref, cipher, expiry in await run_in_threadpool(_candidates):
        checked += 1
        try:
            recipient = unseal_live_secret(cipher).strip().lower()
            if not recipient or len(recipient) > 254 or "@" not in recipient:
                continue
            if owner_ref_for_email(recipient) != owner_ref:
                continue
            owner_hash = hmac.new(
                signing.encode(),
                ("subscription-reminder-v1\n" + recipient).encode(),
                hashlib.sha256,
            ).hexdigest()
            day = threshold(expiry, datetime.now(UTC))
            if day is None or not await run_in_threadpool(
                _eligible, owner_hash, owner_ref, expiry
            ):
                continue
            name = h1_provision_intent(
                email=recipient, plan_id="30", signing_key=signing,
            ).client_name
            state = await read_h1_issued_client_status(name)
            if not state.get("found") or not state.get("active"):
                continue
            reported = state.get("expires_at")
            if not reported or datetime.fromisoformat(reported) != expiry:
                continue
            # Claims never expire automatically: unknown delivery outcomes
            # require manual investigation rather than blind email duplication.
            if not await run_in_threadpool(_claim, owner_hash, expiry, day):
                continue
            # Recheck opt-in before external delivery to reduce the window
            # between changing settings and mailing the customer.
            if not await run_in_threadpool(_eligible, owner_hash, owner_ref, expiry):
                continue
            body = (
                "<h2>Vainah VPN — напоминание о подписке</h2>"
                "<p>До указанной даты окончания осталось не более "
                + str(day) + " дней.</p>"
                "<p>Проверь срок и при необходимости продли подписку в личном кабинете.</p>"
                "<p>В письме нет VPN-ключей и платёжных данных.</p>"
            )
            await send_email(
                recipient, "Vainah VPN — напоминание о продлении", body,
                idempotency_key=(
                    "vainah-renewal-" + owner_hash[:20] + "-"
                    + str(int(expiry.timestamp())) + "-" + str(day)
                ),
            )
            await run_in_threadpool(_complete, owner_hash, expiry, day)
            sent += 1
        except (LiveLedgerError, LiveContractError, H1PanelError,
                HTTPException, ValueError, TypeError, KeyError):
            # Do not disclose recipient, secrets or provider responses.
            continue
    return {"enabled": True, "checked": checked, "sent": sent}


@router.post("/run")
async def run_reminders(x_vainah_reminder_key: str | None = Header(default=None)) -> dict:
    require_runner(x_vainah_reminder_key)
    return await run_batch()
