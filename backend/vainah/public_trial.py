"""One-time free 1d / 2 devices / 10 GiB H1Cloud trial.

This is NOT a RollyPay purchase. Only a server-verified email may claim.
A durable, account-bound claim is committed BEFORE any H1 API call. No blind
retry is allowed after a potentially committed H1 write. The provider must
confirm the exact traffic quota and device limit before a link is released.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from datetime import UTC, datetime

import httpx
import psycopg
from fastapi import APIRouter, HTTPException, Request

from .email_auth import current_email
from .email_auth import ready as email_ready
from .h1_live_provision import LiveH1Error, _validate_subscription_url
from .h1_panel import (
    H1PanelError,
    client_disabled,
    client_expiry,
    panel_settings,
    panel_tls_verify,
)
from .live_checkout import owner_ref_for_email
from .live_ledger import (
    LiveLedgerError,
    PostgresLiveOrderLedger,
    seal_live_secret,
    unseal_live_secret,
)
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/trial", tags=["Free trial"])
TRIAL_DAYS = 1
TRIAL_DEVICES = 2
TRIAL_TRAFFIC_GB = 10
TRIAL_TRAFFIC_BYTES = TRIAL_TRAFFIC_GB * 1024**3
MAX_NEW_TRIALS_IN_24H = 20


class TrialError(Exception):
    """Operator-safe result code; never expose a secret or H1 URL."""


def enabled() -> bool:
    if os.environ.get("VAINAH_PUBLIC_TRIAL_ENABLED") != "enabled":
        return False
    if not email_ready():
        return False
    if not os.environ.get("DATABASE_URL", "").startswith(
        ("postgresql://", "postgres://")
    ):
        return False
    if len(os.environ.get("SESSION_SIGNING_KEY", "")) < 32:
        return False
    try:
        return panel_settings() is not None and bool(panel_tls_verify())
    except H1PanelError:
        return False


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "")
    if not value.startswith(("postgresql://", "postgres://")):
        raise TrialError("TRIAL_STORAGE_UNAVAILABLE")
    return value


def _owner_name(email: str) -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise TrialError("TRIAL_SIGNING_UNAVAILABLE")
    digest = hmac.new(
        secret.encode(), ("vainah-free-trial-h1-v1:" + email.lower()).encode(),
        hashlib.sha256,
    ).hexdigest()
    return "vt" + digest[:28]


def _schema(cur) -> None:
    cur.execute("""
        SELECT set_config('lock_timeout', '4000ms', true),
               set_config('statement_timeout', '8000ms', true)
    """)
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext('vainah_public_trial_schema'))"
    )
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_public_trials (
            owner_ref VARCHAR(67) PRIMARY KEY,
            client_name VARCHAR(30) NOT NULL UNIQUE,
            state TEXT NOT NULL CHECK (
                state IN ('claimed', 'delivered', 'manual_review')
            ),
            subscription_cipher TEXT,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            delivered_at TIMESTAMPTZ
        )
    """)


def _row(owner_ref: str) -> tuple | None:
    try:
        with psycopg.connect(_database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT state, subscription_cipher, expires_at
                FROM vainah_public_trials WHERE owner_ref = %s
            """, (owner_ref,))
            return cur.fetchone()
    except psycopg.Error:
        raise TrialError("TRIAL_STORAGE_UNAVAILABLE") from None


def _reserve(*, owner_ref: str, client_name: str) -> None:
    """Serialize eligibility checks and one-time claim across Render workers."""
    try:
        with psycopg.connect(_database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            PostgresLiveOrderLedger._schema(cur)
            _schema(cur)
            cur.execute("""
                SELECT 1 FROM vainah_public_trials WHERE owner_ref = %s
            """, (owner_ref,))
            if cur.fetchone():
                raise TrialError("TRIAL_ALREADY_CLAIMED")
            cur.execute("""
                SELECT 1 FROM vainah_live_orders
                WHERE owner_ref = %s AND payment_state = 'paid' LIMIT 1
            """, (owner_ref,))
            if cur.fetchone():
                raise TrialError("TRIAL_FOR_NEW_CUSTOMERS_ONLY")
            cur.execute("""
                SELECT COUNT(*) FROM vainah_public_trials
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            if cur.fetchone()[0] >= MAX_NEW_TRIALS_IN_24H:
                raise TrialError("TRIAL_DAILY_LIMIT_REACHED")
            cur.execute("""
                INSERT INTO vainah_public_trials
                    (owner_ref, client_name, state)
                VALUES (%s, %s, 'claimed')
            """, (owner_ref, client_name))
    except psycopg.Error:
        raise TrialError("TRIAL_STORAGE_UNAVAILABLE") from None


def _mark_manual(owner_ref: str) -> None:
    try:
        with psycopg.connect(_database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_public_trials
                SET state = 'manual_review'
                WHERE owner_ref = %s AND state = 'claimed'
            """, (owner_ref,))
    except (psycopg.Error, TrialError):
        # Never clear an uncertain claim, even when recording review fails.
        pass


def _mark_delivered(owner_ref: str, link: str, expiry: int) -> bool:
    encrypted = seal_live_secret(link)
    when = datetime.fromtimestamp(expiry, UTC)
    try:
        with psycopg.connect(_database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_public_trials SET
                    state = 'delivered', subscription_cipher = %s,
                    expires_at = %s, delivered_at = NOW()
                WHERE owner_ref = %s AND state = 'claimed'
                RETURNING owner_ref
            """, (encrypted, when, owner_ref))
            return cur.fetchone() is not None
    except psycopg.Error:
        raise TrialError("TRIAL_STORAGE_UNAVAILABLE") from None


async def _issue_h1(
    name: str, *, transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, int]:
    try:
        settings = panel_settings()
        tls = panel_tls_verify()
    except H1PanelError:
        raise TrialError("TRIAL_H1_NOT_CONFIGURED") from None
    if settings is None:
        raise TrialError("TRIAL_H1_NOT_CONFIGURED")
    headers = {
        "Authorization": "Bearer " + settings.token,
        "Accept": "application/json",
    }
    path = settings.origin + "/api/info?name=" + name
    async with httpx.AsyncClient(
        timeout=10, verify=tls, follow_redirects=False,
        trust_env=False, transport=transport,
    ) as session:
        before = await session.get(path, headers=headers)
        if before.status_code != 404 or len(before.content) > 32768:
            raise TrialError("TRIAL_H1_PREFLIGHT_REJECTED")
        data = before.json()
        if not isinstance(data, dict) or data.get("error") != "user_not_found":
            raise TrialError("TRIAL_H1_PREFLIGHT_REJECTED")
        # Precisely one H1 POST; no retry even on an ambiguous timeout.
        result = await session.post(
            settings.origin + "/api/create", headers=headers,
            json={
                "name": name,
                "days": TRIAL_DAYS,
                "device_limit": TRIAL_DEVICES,
                "traffic_limit_gb": TRIAL_TRAFFIC_GB,
            },
        )
        if result.status_code not in (200, 201) or len(result.content) > 32768:
            raise TrialError("TRIAL_H1_WRITE_UNCERTAIN")
        response = result.json()
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise TrialError("TRIAL_H1_WRITE_UNCERTAIN")
        after = await session.get(path, headers=headers)
        if after.status_code != 200 or len(after.content) > 100000:
            raise TrialError("TRIAL_H1_POSTCHECK_FAILED")
        payload = after.json()
        if (not isinstance(payload, dict) or payload.get("ok") is not True
                or not isinstance(payload.get("client"), dict)):
            raise TrialError("TRIAL_H1_POSTCHECK_FAILED")
        client = payload["client"]
        if (client.get("name") != name
                or type(client.get("device_limit")) is not int
                or client["device_limit"] != TRIAL_DEVICES
                or type(client.get("traffic_limit_bytes")) is not int
                or client["traffic_limit_bytes"] != TRIAL_TRAFFIC_BYTES):
            raise TrialError("TRIAL_H1_QUOTA_NOT_CONFIRMED")
        try:
            expiry = client_expiry(client)
            is_disabled = client_disabled(client)
            link = _validate_subscription_url(
                client.get("subscription_url") or client.get("sub_url")
            )
        except (H1PanelError, LiveH1Error):
            raise TrialError("TRIAL_H1_POSTCHECK_FAILED") from None
        # Exactly a one-day entitlement, with a small tolerance for provisioning.
        remaining = expiry - int(time.time())
        if is_disabled or not 0 < remaining <= 86400 + 300:
            raise TrialError("TRIAL_H1_EXPIRY_NOT_CONFIRMED")
        return link, expiry


async def issue_trial_once(
    email: str, *, transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    if not enabled():
        raise HTTPException(503, "TRIAL_NOT_AVAILABLE")
    owner = owner_ref_for_email(email)
    name = _owner_name(email)
    try:
        _reserve(owner_ref=owner, client_name=name)
    except TrialError as exc:
        code = str(exc)
        if code in {"TRIAL_ALREADY_CLAIMED", "TRIAL_FOR_NEW_CUSTOMERS_ONLY"}:
            raise HTTPException(409, code) from None
        if code == "TRIAL_DAILY_LIMIT_REACHED":
            raise HTTPException(429, code) from None
        raise HTTPException(503, "TRIAL_STORAGE_UNAVAILABLE") from None
    try:
        url, expiry = await _issue_h1(name, transport=transport)
        if not _mark_delivered(owner, url, expiry):
            raise TrialError("TRIAL_STORAGE_UNAVAILABLE")
    except (TrialError, LiveLedgerError, httpx.HTTPError,
            ValueError, asyncio.CancelledError):
        _mark_manual(owner)
        raise HTTPException(503, "TRIAL_REQUIRES_OPERATOR_REVIEW") from None
    return {
        "status": "delivered", "expires_at": datetime.fromtimestamp(expiry, UTC).isoformat(),
        "days": TRIAL_DAYS, "devices": TRIAL_DEVICES,
        "traffic_gb": TRIAL_TRAFFIC_GB,
        "subscription_url": url,
    }


@router.get("/config")
def config() -> dict:
    return {
        "available": enabled(),
        "days": TRIAL_DAYS, "devices": TRIAL_DEVICES,
        "traffic_gb": TRIAL_TRAFFIC_GB,
        "price_rub": 0, "one_time": True,
        "requires_verified_email": True,
    }


@router.get("/status")
def status(request: Request) -> dict:
    email = current_email(request)
    if email is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    try:
        row = _row(owner_ref_for_email(email))
        if row is None:
            return {"status": "eligible", "can_claim": enabled()}
        state, cipher, expires_at = row
        result = {"status": state, "can_claim": False}
        if (state == "delivered" and cipher and expires_at
                and expires_at > datetime.now(UTC)):
            result.update({
                "subscription_url": unseal_live_secret(cipher),
                "expires_at": expires_at.isoformat(),
                "devices": TRIAL_DEVICES, "traffic_gb": TRIAL_TRAFFIC_GB,
            })
        return result
    except (TrialError, LiveLedgerError):
        raise HTTPException(503, "TRIAL_STATUS_UNAVAILABLE") from None


@router.post("/claim")
async def claim(request: Request) -> dict:
    require_same_origin(request)
    email = current_email(request)
    if email is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    return await issue_trial_once(email)
