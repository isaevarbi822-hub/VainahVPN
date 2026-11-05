"""Automatic H1 delivery for signed, account-bound RollyPay SANDBOX payments.

Test-only: a real 1:1 plan-shaped H1Cloud user may be created after a provider
test-paid webhook. No production invoices or live orders are processed.
A PostgreSQL one-time claim prevents double creation on callback retries,
worker crashes and concurrent Render instances. An uncertain write is never
retried; human reconciliation is required.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import psycopg

from .billing import ORDER_RE, get_plan
from .h1_live_provision import (
    LiveH1Error,
    _client,
    _disabled,
    _expiry,
    _validate_subscription_url,
)
from .h1_panel import H1PanelError, panel_settings, panel_tls_verify
from .live_ledger import LiveLedgerError, seal_live_secret, unseal_live_secret
from .postgres_ledger import PostgresSandboxLedger

OWNER_RE = re.compile(r"v1_[0-9a-f]{64}")


class SandboxAutoH1Error(Exception):
    """Sanitized error code; never includes a subscription or upstream body."""


@dataclass(frozen=True)
class Claim:
    order_id: str
    client_name: str
    plan_id: str
    owner_ref: str


def auto_enabled() -> bool:
    """Explicit server-only opt-in; never enable by untrusted callback fields."""
    from .billing import sandbox

    return (
        os.environ.get("VAINAH_SANDBOX_AUTO_H1_ENABLED") == "enabled"
        and os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") == "enabled"
        and os.environ.get("VAINAH_SHOP_PROVIDER_TEST_ENABLED") == "enabled"
        and sandbox.mode == "provider"
        and isinstance(sandbox.ledger, PostgresSandboxLedger)
        and os.environ.get("DATABASE_URL", "").startswith(
            ("postgresql://", "postgres://")
        )
        and len(os.environ.get("SESSION_SIGNING_KEY", "")) >= 32
    )


def _name(order_id: str) -> str:
    key = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(key) < 32 or not ORDER_RE.fullmatch(order_id):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_CONFIG_INVALID")
    # Per-order test client, distinct from both live email users and operator trial.
    digest = hmac.new(
        key.encode(), ("vainah-sandbox-vpn-v1:" + order_id).encode(),
        hashlib.sha256,
    ).hexdigest()
    return "vn" + digest[:28]


def _schema(cur) -> None:
    # Serialize first-use creation and the additive state-check migration across
    # workers. This transaction-scoped lock is released before any HTTP request.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_sandbox_auto_h1_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_sandbox_auto_h1 (
            order_id VARCHAR(44) PRIMARY KEY,
            client_name VARCHAR(30) NOT NULL UNIQUE,
            owner_ref VARCHAR(67) NOT NULL,
            plan_id VARCHAR(24) NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('pending', 'claimed', 'issued', 'needs_review',
                          'failed_before_write')
            ),
            subscription_cipher TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            issued_at TIMESTAMPTZ
        )
    """)
    cur.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'vainah_sandbox_auto_h1'::regclass
                  AND conname = 'vainah_sandbox_auto_h1_state_check'
                  AND pg_get_constraintdef(oid) NOT LIKE '%failed_before_write%'
            ) THEN
                ALTER TABLE vainah_sandbox_auto_h1
                    DROP CONSTRAINT vainah_sandbox_auto_h1_state_check;
                ALTER TABLE vainah_sandbox_auto_h1
                    ADD CONSTRAINT vainah_sandbox_auto_h1_state_check CHECK (
                        state IN ('pending', 'claimed', 'issued', 'needs_review',
                                  'failed_before_write')
                    );
            END IF;
        END $$
    """)


def _db_url() -> str:
    value = os.environ.get("DATABASE_URL", "")
    if not value.startswith(("postgresql://", "postgres://")):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_DATABASE_NOT_CONFIGURED")
    return value


def _claim_once(order_id: str) -> Claim | None:
    """Claim only a truly signed, paid, email-owned provider test invoice."""
    if not ORDER_RE.fullmatch(order_id):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_ORDER_INVALID")
    name = _name(order_id)
    try:
        with psycopg.connect(
            _db_url(), connect_timeout=4
        ) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                INSERT INTO vainah_sandbox_auto_h1
                    (order_id, client_name, owner_ref, plan_id, state)
                SELECT s.order_id, %s, s.owner_ref, s.plan_id, 'pending'
                FROM vainah_sandbox_orders s
                WHERE s.order_id = %s
                    AND s.mode = 'provider'
                    AND s.status = 'paid'
                    AND s.paid_webhook_received = TRUE
                    AND s.owner_ref ~ '^v1_[0-9a-f]{64}$'
                    AND s.receipt_recipient IS NOT NULL
                ON CONFLICT (order_id) DO NOTHING
            """, (name, order_id))
            # Only a proven pre-write failure can be reclaimed. A crashed or
            # uncertain claimed request stays locked even after a long delay.
            cur.execute("""
                UPDATE vainah_sandbox_auto_h1 d SET state = 'claimed'
                FROM vainah_sandbox_orders s
                WHERE d.order_id = %s AND s.order_id = d.order_id
                  AND d.state IN ('pending', 'failed_before_write')
                  AND s.mode = 'provider' AND s.status = 'paid'
                  AND s.paid_webhook_received = TRUE
                  AND s.owner_ref ~ '^v1_[0-9a-f]{64}$'
                  AND s.receipt_recipient IS NOT NULL
                  AND d.owner_ref = s.owner_ref AND d.plan_id = s.plan_id
                RETURNING d.client_name, d.plan_id, d.owner_ref
            """, (order_id,))
            row = cur.fetchone()
    except (psycopg.Error, OSError):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_DATABASE_UNAVAILABLE") from None
    if row is None:
        return None
    name, plan_id, owner_ref = row
    if get_plan(plan_id) is None or not OWNER_RE.fullmatch(owner_ref):
        _mark_review(order_id)
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_PLAN_INVALID")
    return Claim(order_id, name, plan_id, owner_ref)


def _mark_review(order_id: str) -> None:
    try:
        with psycopg.connect(
            _db_url(), connect_timeout=4
        ) as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE vainah_sandbox_auto_h1
                SET state = 'needs_review'
                WHERE order_id = %s AND state = 'claimed'
            """, (order_id,))
    except (psycopg.Error, OSError, SandboxAutoH1Error):
        # The durable claimed state remains locked even if DB is unavailable.
        pass


def _mark_failed_before_write(order_id: str) -> None:
    """Release only when this invocation has not attempted a provider write."""
    try:
        with psycopg.connect(
            _db_url(), connect_timeout=4
        ) as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE vainah_sandbox_auto_h1
                SET state = 'failed_before_write'
                WHERE order_id = %s AND state = 'claimed'
            """, (order_id,))
    except (psycopg.Error, OSError, SandboxAutoH1Error):
        # Failure to persist never releases the durable claim.
        pass


def _mark_issued(order_id: str, url: str) -> None:
    try:
        encrypted = seal_live_secret(url)
        with psycopg.connect(
            _db_url(), connect_timeout=4
        ) as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE vainah_sandbox_auto_h1 d
                SET state = 'issued', subscription_cipher = %s,
                    issued_at = now()
                FROM vainah_sandbox_orders s
                WHERE d.order_id = %s AND d.state = 'claimed'
                  AND s.order_id = d.order_id AND s.status = 'paid'
                  AND s.mode = 'provider' AND s.paid_webhook_received = TRUE
                  AND s.owner_ref = d.owner_ref AND s.plan_id = d.plan_id
                RETURNING d.order_id
            """, (encrypted, order_id))
            if cur.fetchone() is None:
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_CLAIM_LOST")
    except (psycopg.Error, OSError, LiveLedgerError):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_DATABASE_UNAVAILABLE") from None


def read_delivery(
    order_id: str, *, owner_ref: str | None = None,
    with_access: bool = False,
) -> dict:
    """Read state; decrypt only for a verified matching owner and paid order."""
    if not ORDER_RE.fullmatch(order_id):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_ORDER_INVALID")
    if with_access and (
        not isinstance(owner_ref, str) or not OWNER_RE.fullmatch(owner_ref)
    ):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_OWNER_REQUIRED")
    try:
        with psycopg.connect(
            _db_url(), connect_timeout=4
        ) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT d.state, d.subscription_cipher
                FROM vainah_sandbox_auto_h1 d
                JOIN vainah_sandbox_orders s
                    ON s.order_id = d.order_id
                WHERE d.order_id = %s
                    AND s.status = 'paid'
                    AND s.paid_webhook_received = TRUE
                    AND s.mode = 'provider'
                    AND s.owner_ref = d.owner_ref
                    AND (%s::text IS NULL OR s.owner_ref = %s)
            """, (order_id, owner_ref, owner_ref))
            row = cur.fetchone()
    except (psycopg.Error, OSError):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_DATABASE_UNAVAILABLE") from None
    if not row:
        return {"status": "not_issued", "vpn_delivered": False}
    state, encrypted = row
    result = {"status": state, "vpn_delivered": state == "issued"}
    if with_access and state == "issued" and encrypted:
        try:
            result["subscription_url"] = unseal_live_secret(encrypted)
        except LiveLedgerError:
            raise SandboxAutoH1Error("SANDBOX_AUTO_H1_LINK_UNAVAILABLE") from None
    return result


async def auto_issue_paid_sandbox(
    order_id: str, *, transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """After an already-verified test-paid webhook, issue at most one H1 user.

    Only the same durable order record that passed the provider webhook gate
    can be claimed. Never issue from a mock payment, polling or a browser flag.
    """
    if not auto_enabled():
        return {"status": "disabled", "vpn_delivered": False}
    claim = _claim_once(order_id)
    if claim is None:
        return read_delivery(order_id)
    write_attempted = False
    requires_review = False
    try:
        plan = get_plan(claim.plan_id)
        if plan is None:
            raise SandboxAutoH1Error("SANDBOX_AUTO_H1_PLAN_INVALID")
        settings = panel_settings()
        if settings is None:
            raise SandboxAutoH1Error("SANDBOX_AUTO_H1_PANEL_NOT_READY")
        verify = panel_tls_verify()
        headers = {
            "Authorization": "Bearer " + settings.token,
            "Accept": "application/json",
        }
        path = "/api/info?" + urlencode({"name": claim.client_name})
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False,
            verify=verify, transport=transport,
        ) as client:
            preflight = await client.get(settings.origin + path, headers=headers)
            # An existing deterministic user may be a historical write whose
            # response was lost. Never create or overwrite it automatically.
            requires_review = preflight.status_code == 200
            if preflight.status_code != 404 or len(preflight.content) > 32768:
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_PREFLIGHT_FAILED")
            try:
                body = preflight.json()
            except ValueError:
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_PREFLIGHT_FAILED") from None
            if not isinstance(body, dict) or body.get("error") != "user_not_found":
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_PREFLIGHT_FAILED")

            write_started_at = int(time.time())
            write_attempted = True
            created = await client.post(
                settings.origin + "/api/create",
                headers=headers,
                json={
                    "name": claim.client_name, "days": plan["days"],
                    "device_limit": plan["devices"],
                },
            )
            if created.status_code not in (200, 201) or len(created.content) > 32768:
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_WRITE_REVIEW")
            try:
                reply = created.json()
            except ValueError:
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_WRITE_REVIEW") from None
            if not isinstance(reply, dict) or reply.get("ok") is not True:
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_WRITE_REVIEW")
            after = await client.get(settings.origin + path, headers=headers)
            if after.status_code != 200 or len(after.content) > 32768:
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_POSTCHECK_FAILED")
            try:
                profile = _client(after.json(), claim.client_name)
                expiry = _expiry(profile)
                disabled = _disabled(profile)
                devices = profile.get("device_limit")
                link = _validate_subscription_url(
                    profile.get("subscription_url") or profile.get("sub_url")
                )
            except (ValueError, KeyError, TypeError, LiveH1Error):
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_POSTCHECK_FAILED") from None
            if (
                # Permit clock/processing skew while verifying the paid term,
                # rather than accepting any account expiring in the future.
                expiry < write_started_at + plan["days"] * 86400 - 300
                or disabled
                or type(devices) is not int
                or devices != plan["devices"]
            ):
                raise SandboxAutoH1Error("SANDBOX_AUTO_H1_POSTCHECK_FAILED")
            _mark_issued(claim.order_id, link)
            return {"status": "issued", "vpn_delivered": True}
    except (
        SandboxAutoH1Error, H1PanelError,
        httpx.RequestError, httpx.TimeoutException,
    ):
        # A POST may have committed even when the response/persistence failed.
        # Only failures known to precede all writes can be retried safely.
        if write_attempted or requires_review:
            _mark_review(claim.order_id)
            state = "needs_review"
        else:
            _mark_failed_before_write(claim.order_id)
            state = "failed_before_write"
        return {"status": state, "vpn_delivered": False}


def mark_refunded(order_id: str) -> None:
    """Disable test-link access following a verified provider reversal."""
    if not auto_enabled() or not ORDER_RE.fullmatch(order_id):
        return
    try:
        with psycopg.connect(
            _db_url(), connect_timeout=4
        ) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_sandbox_auto_h1
                SET state = 'needs_review'
                WHERE order_id = %s AND state = 'issued'
            """, (order_id,))
    except (psycopg.Error, OSError):
        raise SandboxAutoH1Error("SANDBOX_AUTO_H1_DATABASE_UNAVAILABLE") from None
