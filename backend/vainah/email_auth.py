"""Passwordless email login on Render: one-time codes, DB throttling, signed sessions.

A verified email login is an independent identity. Its association with an
existing Telegram customer comes only from the separately verified ownership
mapping in PostgreSQL, never from an untrusted browser-supplied Telegram ID.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import UTC, datetime, timedelta

import psycopg
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .email_delivery import database_url, email_service_ready, send_verification_code
from .telegram_auth import SESSION_COOKIE, require_same_origin

EMAIL_SESSION_COOKIE = "__Host-vainah_email_session"
SESSION_SECONDS = 12 * 3600
CODE_SECONDS = 600
RESEND_COOLDOWN = 90
HOUR_LIMIT = 5
IP_HOUR_LIMIT = 20
CODE_ATTEMPTS = 5
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{3,189}$")
SESSION_TOKEN_RE = re.compile(r"([A-Za-z0-9_-]+)\.([0-9a-f]{64})")


def _secret() -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "EMAIL_LOGIN_NOT_CONFIGURED")
    return secret


def ready() -> bool:
    db = os.environ.get("DATABASE_URL", "")
    return (
        len(os.environ.get("SESSION_SIGNING_KEY", "")) >= 32
        and email_service_ready()
        and db.startswith(("postgresql://", "postgres://"))
    )


def normalize_email(value: str) -> str:
    try:
        result = validate_email(value, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(422, "EMAIL_INVALID") from None
    if len(result) > 254 or not EMAIL_RE.fullmatch(result):
        raise HTTPException(422, "EMAIL_INVALID")
    return result


def _hmac(secret: str, purpose: str, value: str) -> str:
    return hmac.new(
        secret.encode(), (purpose + "\n" + value).encode(), hashlib.sha256
    ).hexdigest()


def _schema(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_email_login_codes (
            email VARCHAR(254) PRIMARY KEY,
            code_hash CHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            next_send_at TIMESTAMPTZ NOT NULL,
            attempts INT NOT NULL DEFAULT 0,
            window_start TIMESTAMPTZ NOT NULL,
            sends_in_window INT NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_email_login_ip_limits (
            source_hash CHAR(64) PRIMARY KEY,
            window_start TIMESTAMPTZ NOT NULL,
            sends_in_window INT NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_email_login_accounts (
            email VARCHAR(254) PRIMARY KEY,
            verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def _locked_send_code(email: str, source_hash: str) -> str:
    secret = _secret()
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = _hmac(secret, "login-otp-v1:" + email, code)
    now = datetime.now(UTC)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            # Deterministic ordering: email lock followed by source lock.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 3171)", (email,))
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 3172)", (source_hash,))
            cur.execute("""
                SELECT next_send_at, window_start, sends_in_window
                FROM vainah_email_login_codes WHERE email = %s FOR UPDATE
            """, (email,))
            entry = cur.fetchone()
            if entry:
                next_send, window_start, count = entry
                if next_send > now:
                    raise HTTPException(429, "EMAIL_LOGIN_COOLDOWN")
                hourly = count if window_start > now - timedelta(hours=1) else 0
                if hourly >= HOUR_LIMIT:
                    raise HTTPException(429, "EMAIL_LOGIN_LIMIT")
            else:
                hourly = 0
                window_start = now
            cur.execute("""
                SELECT window_start, sends_in_window
                FROM vainah_email_login_ip_limits
                WHERE source_hash = %s FOR UPDATE
            """, (source_hash,))
            per_ip = cur.fetchone()
            ip_count = 0
            if per_ip and per_ip[0] > now - timedelta(hours=1):
                ip_count = per_ip[1]
            if ip_count >= IP_HOUR_LIMIT:
                raise HTTPException(429, "EMAIL_LOGIN_LIMIT")
            ip_start = per_ip[0] if ip_count else now
            window_start = window_start if hourly else now
            cur.execute("""
                INSERT INTO vainah_email_login_codes(
                    email, code_hash, expires_at, next_send_at,
                    attempts, window_start, sends_in_window
                ) VALUES (%s, %s, %s, %s, 0, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    code_hash = EXCLUDED.code_hash,
                    expires_at = EXCLUDED.expires_at,
                    next_send_at = EXCLUDED.next_send_at,
                    attempts = 0,
                    window_start = EXCLUDED.window_start,
                    sends_in_window = EXCLUDED.sends_in_window
            """, (email, digest, now + timedelta(seconds=CODE_SECONDS),
                  now + timedelta(seconds=RESEND_COOLDOWN),
                  window_start, hourly + 1))
            cur.execute("""
                INSERT INTO vainah_email_login_ip_limits (
                    source_hash, window_start, sends_in_window
                ) VALUES (%s, %s, %s)
                ON CONFLICT (source_hash) DO UPDATE SET
                    window_start = EXCLUDED.window_start,
                    sends_in_window = EXCLUDED.sends_in_window
            """, (source_hash, ip_start, ip_count + 1))
    except psycopg.Error:
        raise HTTPException(503, "EMAIL_LOGIN_DATABASE_UNAVAILABLE") from None
    return code


def _cancel_failed_delivery(email: str, code: str) -> None:
    digest = _hmac(_secret(), "login-otp-v1:" + email, code)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            cur.execute("""
                DELETE FROM vainah_email_login_codes
                WHERE email = %s AND code_hash = %s
            """, (email, digest))
    except psycopg.Error:
        return


def _verify_code(email: str, code: str) -> bool:
    digest = _hmac(_secret(), "login-otp-v1:" + email, code)
    now = datetime.now(UTC)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT code_hash, expires_at, attempts
                FROM vainah_email_login_codes
                WHERE email = %s FOR UPDATE
            """, (email,))
            row = cur.fetchone()
            if not row or row[1] <= now or row[2] >= CODE_ATTEMPTS:
                return False
            if not hmac.compare_digest(str(row[0]), digest):
                cur.execute("""
                    UPDATE vainah_email_login_codes
                    SET attempts = attempts + 1 WHERE email = %s
                """, (email,))
                return False
            cur.execute("""
                INSERT INTO vainah_email_login_accounts(email, verified_at)
                VALUES (%s, now())
                ON CONFLICT (email) DO UPDATE SET verified_at = now()
            """, (email,))
            cur.execute("DELETE FROM vainah_email_login_codes WHERE email = %s",
                        (email,))
            return True
    except psycopg.Error:
        raise HTTPException(503, "EMAIL_LOGIN_DATABASE_UNAVAILABLE") from None


def _sign_session(email: str, *, now: int | None = None) -> str:
    stamp = int(time.time()) if now is None else now
    payload = json.dumps({"v": 1, "email": email, "iat": stamp,
                          "exp": stamp + SESSION_SECONDS}, separators=(",", ":"))
    value = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    return value + "." + _hmac(_secret(), "email-session-v1", value)


def _read_session(raw: str | None, *, now: int | None = None) -> str | None:
    if not isinstance(raw, str) or len(raw) > 1024:
        return None
    match = SESSION_TOKEN_RE.fullmatch(raw)
    if not match or len(os.environ.get("SESSION_SIGNING_KEY", "")) < 32:
        return None
    if not hmac.compare_digest(
        match.group(2), _hmac(_secret(), "email-session-v1", match.group(1))
    ):
        return None
    try:
        value = match.group(1)
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(decoded)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    stamp = int(time.time()) if now is None else now
    if not isinstance(payload, dict) or payload.get("v") != 1:
        return None
    if (type(payload.get("iat")) is not int
            or type(payload.get("exp")) is not int
            or payload["iat"] > stamp + 60
            or payload["exp"] <= stamp
            or payload["exp"] > payload["iat"] + SESSION_SECONDS):
        return None
    email = payload.get("email")
    if not isinstance(email, str) or len(email) > 254 or not EMAIL_RE.fullmatch(email):
        return None
    return email


def current_email(request: Request) -> str | None:
    return _read_session(request.cookies.get(EMAIL_SESSION_COOKIE))


class EmailAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=5, max_length=254)


class EmailVerify(EmailAddress):
    code: str = Field(pattern=r"^[0-9]{6}$")


router = APIRouter(prefix="/api/email-auth", tags=["Email login"])


@router.get("/config")
def login_config() -> dict:
    return {
        "available": ready(),
        "method": "email_code",
        "requires_verified_email": True,
        "message": (
            "Вход по email настроен. Пришли код подтверждения для входа."
            if ready() else
            "Не настроены PostgreSQL, SESSION_SIGNING_KEY или отправитель Resend."
        ),
    }


@router.get("/account")
def account(request: Request) -> dict:
    email = current_email(request)
    return {"authenticated": email is not None,
            "user": {"auth_method": "email", "email": email} if email else None}


@router.post("/request")
async def request_code(request: Request, body: EmailAddress) -> dict:
    require_same_origin(request)
    if not ready():
        raise HTTPException(503, "EMAIL_LOGIN_NOT_CONFIGURED")
    email = normalize_email(body.email)
    ip = request.client.host if request.client else "unknown"
    source_hash = _hmac(_secret(), "login-source-v1", ip)
    code = _locked_send_code(email, source_hash)
    try:
        await send_verification_code(email, code)
    except HTTPException:
        _cancel_failed_delivery(email, code)
        raise
    return {"sent": True, "expires_in_seconds": CODE_SECONDS}


@router.post("/verify")
def verify_code(request: Request, body: EmailVerify, response: Response) -> dict:
    require_same_origin(request)
    if not ready():
        raise HTTPException(503, "EMAIL_LOGIN_NOT_CONFIGURED")
    email = normalize_email(body.email)
    if not _verify_code(email, body.code):
        raise HTTPException(401, "EMAIL_LOGIN_INVALID_CODE")
    response.set_cookie(
        EMAIL_SESSION_COOKIE, _sign_session(email),
        secure=True, httponly=True, samesite="lax",
        path="/", max_age=SESSION_SECONDS,
    )
    # Prevent two different customer identities being active in one browser.
    response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True,
                           samesite="lax", path="/")
    return {"authenticated": True, "user": {
        "auth_method": "email", "email": email,
    }}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    require_same_origin(request)
    for name in (EMAIL_SESSION_COOKIE, SESSION_COOKIE):
        response.delete_cookie(name, secure=True, httponly=True,
                               samesite="lax", path="/")
    return {"authenticated": False}
