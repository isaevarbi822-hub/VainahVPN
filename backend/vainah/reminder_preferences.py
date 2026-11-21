"""Verified-account opt-in settings for future subscription expiry emails.

Preferences never trigger a message by themselves. A separate verified,
scheduled dispatcher is required before automated delivery is enabled.
"""
from __future__ import annotations

import hashlib
import hmac
import os

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from .email_auth import current_email
from .email_delivery import database_url, verified_email
from .telegram_auth import current_user, require_same_origin

router = APIRouter(prefix="/api/account", tags=["Subscription reminder preferences"])


class ReminderPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


def delivery_active() -> bool:
    """Only advertise email reminders with a verified scheduled runner.

    The workflow in a non-default GitHub branch cannot run on schedule.
    An operator must verify scheduling and set an explicit confirmation
    in addition to the protected dispatcher feature flags. No emails
    are sent from a user's preference endpoint.
    """
    from .email_delivery import email_service_ready
    from .reminder_dispatch import enabled

    runner = os.environ.get("VAINAH_REMINDER_RUNNER_KEY", "")
    signing = os.environ.get("SESSION_SIGNING_KEY", "")
    return (
        enabled() and email_service_ready()
        and os.environ.get("VAINAH_REMINDER_SCHEDULE_CONFIRMED") == "confirmed"
        and len(runner) >= 40 and runner != signing and len(signing) >= 32
    )


def _delivery_state() -> dict:
    active = delivery_active()
    return {
        "delivery_active": active,
        "message": (
            "Email reminders are scheduled for opted-in accounts."
            if active else "Email reminders are not yet scheduled."
        ),
    }


def _identity(request: Request) -> str:
    email = current_email(request)
    if not email:
        telegram = current_user(request)
        if telegram:
            email = verified_email(telegram["telegram_id"])
    if not email:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    signing_key = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(signing_key) < 32:
        raise HTTPException(503, "REMINDER_SERVICE_NOT_CONFIGURED")
    return hmac.new(
        signing_key.encode(),
        ("subscription-reminder-v1\n" + email.strip().lower()).encode(),
        hashlib.sha256,
    ).hexdigest()


def _schema(cur):
    cur.execute("""
        SELECT set_config('lock_timeout','4000ms',TRUE),
               set_config('statement_timeout','8000ms',TRUE)
    """)
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_reminder_prefs_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_reminder_preferences (
            owner_hash CHAR(64) PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def _read(owner: str) -> bool:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute(
                "SELECT enabled FROM vainah_reminder_preferences WHERE owner_hash=%s",
                (owner,),
            )
            row = cur.fetchone()
            return bool(row[0]) if row else False
    except psycopg.Error:
        raise HTTPException(503, "REMINDER_DATABASE_UNAVAILABLE") from None


def _write(owner: str, enabled: bool) -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                INSERT INTO vainah_reminder_preferences (owner_hash, enabled)
                VALUES (%s, %s)
                ON CONFLICT (owner_hash) DO UPDATE SET
                    enabled=EXCLUDED.enabled, changed_at=now()
            """, (owner, enabled))
    except psycopg.Error:
        raise HTTPException(503, "REMINDER_DATABASE_UNAVAILABLE") from None


@router.get("/reminder-preference")
def get_reminder_preference(request: Request) -> dict:
    owner = _identity(request)
    return {"enabled": _read(owner), **_delivery_state()}


@router.post("/reminder-preference")
def set_reminder_preference(request: Request, body: ReminderPreference) -> dict:
    require_same_origin(request)
    owner = _identity(request)
    _write(owner, body.enabled)
    return {"enabled": body.enabled, **_delivery_state()}
