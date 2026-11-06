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
    return {"enabled": _read(owner), "delivery_active": False,
            "message": "Email reminders are not yet scheduled."}


@router.post("/reminder-preference")
def set_reminder_preference(request: Request, body: ReminderPreference) -> dict:
    require_same_origin(request)
    owner = _identity(request)
    _write(owner, body.enabled)
    return {"enabled": body.enabled, "delivery_active": False,
            "message": "Preference saved; automated email delivery is not active yet."}
