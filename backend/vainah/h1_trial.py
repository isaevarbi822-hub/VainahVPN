"""One-time operator-only H1Cloud trial issuance for real integration validation.

This endpoint does NOT validate payments or enable public checkout. It can
create one genuine 1-day, 1-device VPN test account on the operator's node.
A durable PostgreSQL claim prevents duplicate writes across Render workers.
After an ambiguous write, a human must reconcile the node; never auto-retry.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlencode

import httpx
import psycopg
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from .billing import _require_operator
from .h1_live_provision import (
    LiveH1Error,
    _client,
    _disabled,
    _expiry,
    _validate_subscription_url,
)
from .h1_panel import H1PanelError, panel_settings, panel_tls_verify
from .live_ledger import LiveLedgerError, seal_live_secret
from .postgres_ledger import LOCK_TIMEOUT_MS, STATEMENT_TIMEOUT_MS

router = APIRouter(prefix="/api/site/integrations", tags=["H1Cloud trial"])
TRIAL_ID = "h1cloud-operator-trial-v1"


class TrialError(Exception):
    """A sanitized error, never provider text, tokens or subscription URLs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class TrialConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


def _ready() -> tuple[str, str]:
    if os.environ.get("VAINAH_H1_TRIAL_ENABLED") != "enabled":
        raise TrialError("H1_TRIAL_DISABLED")
    signing_key = os.environ.get("SESSION_SIGNING_KEY", "")
    database_url = os.environ.get("DATABASE_URL", "")
    if len(signing_key) < 32 or not database_url.startswith(
        ("postgresql://", "postgres://")
    ):
        raise TrialError("H1_TRIAL_STORAGE_NOT_READY")
    name = "vn" + hmac.new(
        signing_key.encode(), b"vainah-h1-operator-trial-v1", hashlib.sha256
    ).hexdigest()[:28]
    return name, database_url


def _transaction_limits(cursor) -> None:
    cursor.execute("""
        SELECT set_config('lock_timeout', %s, TRUE),
               set_config('statement_timeout', %s, TRUE)
    """, (f"{LOCK_TIMEOUT_MS}ms", f"{STATEMENT_TIMEOUT_MS}ms"))


def _schema(cursor) -> None:
    _transaction_limits(cursor)
    # IF NOT EXISTS alone can race on pg_type during concurrent first use.
    cursor.execute("SELECT pg_advisory_xact_lock(1447960899, hashtext(current_schema()))")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vainah_h1_trial_issuance (
            trial_id VARCHAR(40) PRIMARY KEY,
            client_name VARCHAR(30) NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('claimed', 'issued', 'needs_review')
            ),
            subscription_cipher TEXT,
            issued_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def _claim_once(database_url: str, name: str) -> bool:
    try:
        with psycopg.connect(
            database_url, connect_timeout=4
        ) as conn, conn.cursor() as cursor:
            _schema(cursor)
            cursor.execute("""
                INSERT INTO vainah_h1_trial_issuance
                    (trial_id, client_name, state)
                VALUES (%s, %s, 'claimed')
                ON CONFLICT (trial_id) DO NOTHING
                RETURNING trial_id
            """, (TRIAL_ID, name))
            return cursor.fetchone() is not None
    except (psycopg.Error, OSError):
        raise TrialError("H1_TRIAL_DATABASE_UNAVAILABLE") from None


def _mark_uncertain(database_url: str) -> None:
    try:
        with psycopg.connect(
            database_url, connect_timeout=4
        ) as conn, conn.cursor() as cursor:
            _transaction_limits(cursor)
            cursor.execute("""
                UPDATE vainah_h1_trial_issuance
                SET state = 'needs_review'
                WHERE trial_id = %s AND state = 'claimed'
            """, (TRIAL_ID,))
    except (psycopg.Error, OSError):
        # Keep the claim locked if the database is temporarily unavailable.
        pass


def _save_success(database_url: str, subscription_url: str) -> None:
    try:
        encrypted = seal_live_secret(subscription_url)
        with psycopg.connect(
            database_url, connect_timeout=4
        ) as conn, conn.cursor() as cursor:
            _transaction_limits(cursor)
            cursor.execute("""
                UPDATE vainah_h1_trial_issuance
                SET state = 'issued', subscription_cipher = %s,
                    issued_at = now()
                WHERE trial_id = %s AND state = 'claimed'
                RETURNING trial_id
            """, (encrypted, TRIAL_ID))
            if cursor.fetchone() is None:
                raise TrialError("H1_TRIAL_CLAIM_LOST")
    except (psycopg.Error, OSError, LiveLedgerError):
        raise TrialError("H1_TRIAL_DATABASE_UNAVAILABLE") from None


async def issue_operator_trial(
    *, transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Make at most one non-repeatable write after verified HTTPS + DB claim."""
    name, database_url = _ready()
    try:
        settings = panel_settings()
        verifier = panel_tls_verify()
    except H1PanelError:
        raise TrialError("H1_TRIAL_PANEL_CONFIGURATION_INVALID") from None
    if settings is None:
        raise TrialError("H1_TRIAL_PANEL_NOT_CONFIGURED")
    url = settings.origin + "/api/info?" + urlencode({"name": name})
    headers = {
        "Authorization": "Bearer " + settings.token,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=10, verify=verifier, trust_env=False,
        follow_redirects=False, transport=transport,
    ) as client:
        # Preflight is read-only. Never modify an already existing user.
        try:
            before = await client.get(url, headers=headers)
        except httpx.RequestError:
            raise TrialError("H1_TRIAL_PREFLIGHT_NETWORK_ERROR") from None
        if before.status_code != 404 or len(before.content) > 32768:
            raise TrialError("H1_TRIAL_USER_EXISTS_OR_PREFLIGHT_FAILED")
        try:
            missing = before.json()
        except ValueError:
            raise TrialError("H1_TRIAL_PREFLIGHT_INVALID") from None
        if not isinstance(missing, dict) or missing.get("error") != "user_not_found":
            raise TrialError("H1_TRIAL_PREFLIGHT_INVALID")

        # One immutable claim before POST; never automatically release or retry.
        if not _claim_once(database_url, name):
            raise TrialError("H1_TRIAL_ALREADY_ATTEMPTED")
        try:
            write_started_at = int(time.time())
            try:
                created = await client.post(
                    settings.origin + "/api/create",
                    headers=headers,
                    json={"name": name, "days": 1, "device_limit": 1},
                )
            except httpx.RequestError:
                raise TrialError("H1_TRIAL_WRITE_UNCERTAIN") from None
            if len(created.content) > 32768:
                raise TrialError("H1_TRIAL_WRITE_UNCERTAIN")
            try:
                response = created.json()
            except ValueError:
                raise TrialError("H1_TRIAL_WRITE_UNCERTAIN") from None
            if created.status_code not in (200, 201) or not isinstance(
                response, dict
            ) or response.get("ok") is not True:
                raise TrialError("H1_TRIAL_WRITE_REJECTED_REVIEW_REQUIRED")
            try:
                checked = await client.get(url, headers=headers)
            except httpx.RequestError:
                raise TrialError("H1_TRIAL_POSTCHECK_UNCERTAIN") from None
            if checked.status_code != 200 or len(checked.content) > 32768:
                raise TrialError("H1_TRIAL_POSTCHECK_UNCERTAIN")
            try:
                record = _client(checked.json(), name)
                expiry = _expiry(record)
                disabled = _disabled(record)
                devices = record.get("device_limit")
                sub = _validate_subscription_url(
                    record.get("subscription_url") or record.get("sub_url")
                )
            except (ValueError, TypeError, KeyError, LiveH1Error):
                raise TrialError("H1_TRIAL_POSTCHECK_INVALID") from None
            if (expiry < write_started_at + 86400 - 300 or disabled
                    or type(devices) is not int or devices != 1):
                raise TrialError("H1_TRIAL_POSTCHECK_INVALID")
            # Complete all response validation/formatting before persisting
            # success; a malformed date must never leave an issued record.
            expiry_iso = datetime.fromtimestamp(expiry, UTC).isoformat()
            _save_success(database_url, sub)
            return {
                "status": "issued",
                "test_only": True,
                "payment_created": False,
                "days": 1,
                "device_limit": 1,
                "expires_at": expiry_iso,
                "subscription_url": sub,
            }
        except (TrialError, asyncio.CancelledError):
            _mark_uncertain(database_url)
            raise


@router.post("/h1cloud/trial/issue")
async def issue_h1cloud_operator_trial(
    body: TrialConfirmation,
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    """Operator-initiated, one-shot real test user; never tied to checkout."""
    _require_operator(x_sandbox_token)
    try:
        return await issue_operator_trial()
    except TrialError as exc:
        # Duplicate attempts are intentionally blocked even after a timeout.
        code = 409 if exc.code in {
            "H1_TRIAL_ALREADY_ATTEMPTED",
            "H1_TRIAL_USER_EXISTS_OR_PREFLIGHT_FAILED",
        } else 503
        raise HTTPException(status_code=code, detail=exc.code) from None


@router.get("/h1cloud/trial/readiness")
async def h1cloud_trial_readiness(
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    """Only configuration, no account names, tokens, keys or trial links."""
    _require_operator(x_sandbox_token)
    try:
        _ready()
        enabled = True
    except TrialError:
        enabled = False
    return {
        "enabled": enabled,
        "real_payment_enabled": False,
        "trial_days": 1,
        "device_limit": 1,
        "one_time_only": True,
        "note": "H1Cloud test creates a real VPN account. No RollyPay charge.",
    }
