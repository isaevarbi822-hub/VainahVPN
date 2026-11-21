"""One-time PKCE handoff from browser Google/Telegram OIDC to Android.

The browser validates identity with the existing provider callback. The app
alone holds the S256 verifier; browser deep-links carry only a short-lived
single-use authorization code, NEVER an authenticated session. All pending
flows live in PostgreSQL, so Render multi-worker/redeploys work correctly.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from urllib.parse import urlencode
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .email_auth import EMAIL_SESSION_COOKIE, _sign_session
from .google_auth import _config as google_config
from .google_auth import _origin
from .telegram_auth import SESSION_COOKIE, make_session, require_same_origin
from .telegram_oidc import _config as telegram_config

router = APIRouter(prefix="/api/mobile-auth", tags=["Android OAuth PKCE"])
FLOW_MINUTES = 10
CODE_SECONDS = 90
MAX_FLOWS_PER_SOURCE = 15
PKCE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def _secret() -> str:
    value = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(value) < 32:
        raise HTTPException(503, "MOBILE_AUTH_NOT_CONFIGURED")
    return value


def _db_url() -> str:
    value = os.environ.get("DATABASE_URL", "")
    if not value.startswith(("postgresql://", "postgres://")):
        raise HTTPException(503, "MOBILE_AUTH_NOT_CONFIGURED")
    return value


def _digest(kind: str, value: str) -> str:
    return hmac.new(_secret().encode(),
        ("mobile-pkce-" + kind + "-v1\n" + value).encode(),
        hashlib.sha256).hexdigest()


def _schema(cur) -> None:
    cur.execute("SELECT set_config('lock_timeout','4000ms', true), "
                "set_config('statement_timeout','8000ms', true)")
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_mobile_auth_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_mobile_auth (
            flow_id UUID PRIMARY KEY,
            provider VARCHAR(16) NOT NULL CHECK (provider IN ('google', 'telegram')),
            challenge CHAR(43) NOT NULL,
            source_hash CHAR(64) NOT NULL,
            status VARCHAR(12) NOT NULL CHECK (
                status IN ('pending', 'ready', 'consumed')
            ),
            authorization_hash CHAR(64),
            authorization_expires_at TIMESTAMPTZ,
            verified_email VARCHAR(254),
            telegram_user TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_mobile_auth_source_idx
            ON vainah_mobile_auth(source_hash, created_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_mobile_auth_expires_idx
            ON vainah_mobile_auth(expires_at)
    """)


def _flow(value: str) -> UUID | None:
    try:
        parsed = UUID(value)
        return parsed if str(parsed) == value else None
    except (TypeError, ValueError, AttributeError):
        return None


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern="^(google|telegram)$")
    code_challenge: str = Field(min_length=43, max_length=43)


class Exchange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow: str = Field(min_length=36, max_length=36)
    code: str = Field(min_length=32, max_length=128)
    verifier: str = Field(min_length=43, max_length=128)


@router.get("/config")
def config() -> dict:
    database_ready = bool(os.environ.get("DATABASE_URL", "").startswith(
        ("postgresql://", "postgres://"))) and len(
            os.environ.get("SESSION_SIGNING_KEY", "")) >= 32
    return {
        "google": database_ready and google_config() is not None,
        "telegram": database_ready and telegram_config() is not None,
        "pkce": True,
        "enabled": database_ready,
    }


@router.post("/start")
def start(request: Request, body: Start) -> dict:
    require_same_origin(request)
    if not PKCE_RE.fullmatch(body.code_challenge):
        raise HTTPException(422, "INVALID_PKCE_CHALLENGE")
    if ((body.provider == "google" and google_config() is None)
            or (body.provider == "telegram" and telegram_config() is None)):
        raise HTTPException(503, "OAUTH_PROVIDER_NOT_CONFIGURED")
    origin = _origin()
    if not origin:
        raise HTTPException(503, "MOBILE_AUTH_NOT_CONFIGURED")
    ip = request.client.host if request.client else "unknown"
    source = _digest("source", ip)
    identifier = uuid4()
    try:
        with psycopg.connect(_db_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            # Prevent indefinitely retaining expired identity payloads and
            # single-use authorization codes. Bounded batches avoid long
            # DELETE locks on a busy production database.
            cur.execute("""
                DELETE FROM vainah_mobile_auth
                WHERE flow_id IN (
                    SELECT flow_id FROM vainah_mobile_auth
                    WHERE expires_at < now() - interval '1 day'
                    ORDER BY expires_at ASC LIMIT 100
                )
            """)
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 7781)", (source,))
            cur.execute("""
                SELECT COUNT(*) FROM vainah_mobile_auth
                WHERE source_hash=%s AND created_at > now() - interval '10 minutes'
            """, (source,))
            if cur.fetchone()[0] >= MAX_FLOWS_PER_SOURCE:
                raise HTTPException(429, "OAUTH_START_RATE_LIMIT")
            cur.execute("""
                INSERT INTO vainah_mobile_auth
                    (flow_id, provider, challenge, source_hash, status, expires_at)
                VALUES (%s, %s, %s, %s, 'pending', now() + interval '10 minutes')
            """, (identifier, body.provider, body.code_challenge, source))
    except psycopg.Error:
        raise HTTPException(503, "MOBILE_AUTH_DATABASE_UNAVAILABLE") from None
    endpoint = ("/api/google/start" if body.provider == "google"
                else "/api/telegram-oidc/start")
    return {
        "flow": str(identifier),
        "authorize_url": origin + endpoint + "?" + urlencode({
            "mobile_flow": str(identifier),
        }),
        "expires_in_seconds": FLOW_MINUTES * 60,
    }


def pending(flow: str, provider: str) -> bool:
    identifier = _flow(flow)
    if identifier is None:
        return False
    try:
        with psycopg.connect(_db_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT 1 FROM vainah_mobile_auth
                WHERE flow_id=%s AND provider=%s AND status='pending'
                AND expires_at > now()
            """, (identifier, provider))
            return cur.fetchone() is not None
    except psycopg.Error:
        return False


def complete(
    flow: str, provider: str, *,
    email: str | None = None, telegram_user: dict | None = None,
) -> str | None:
    """Callable only from an already cryptographically verified OIDC callback."""
    identifier = _flow(flow)
    if identifier is None or provider not in ("google", "telegram"):
        return None
    if (provider == "google" and (not email or telegram_user is not None)
            or provider == "telegram" and (telegram_user is None or email)):
        return None
    if provider == "telegram":
        if (not isinstance(telegram_user, dict) or
                not re.fullmatch(r"[1-9][0-9]{0,17}",
                    str(telegram_user.get("telegram_id", "")))):
            return None
        user_json = json.dumps(telegram_user, separators=(",", ":"))
        if len(user_json) > 800:
            return None
    else:
        user_json = None
    code = secrets.token_urlsafe(32)
    digest = _digest("code", str(identifier) + ":" + code)
    try:
        with psycopg.connect(_db_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_mobile_auth
                SET status='ready', authorization_hash=%s,
                    authorization_expires_at=now() + interval '90 seconds',
                    verified_email=%s, telegram_user=%s
                WHERE flow_id=%s AND provider=%s AND status='pending'
                    AND expires_at > now()
                RETURNING flow_id
            """, (digest, email, user_json, identifier, provider))
            if cur.fetchone() is None:
                return None
    except psycopg.Error:
        return None
    # One-time public authorization code has no privileges without the PKCE
    # verifier, and expires after 90 seconds. Never put session cookies in URL.
    return "vainahvpn://oauth?" + urlencode({"flow": str(identifier), "code": code})


@router.post("/exchange")
def exchange(request: Request, body: Exchange) -> dict:
    require_same_origin(request)
    identifier = _flow(body.flow)
    if (identifier is None or not CODE_RE.fullmatch(body.code)
            or not re.fullmatch(r"^[A-Za-z0-9_-]{43,128}$", body.verifier)):
        raise HTTPException(400, "OAUTH_CODE_INVALID")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(body.verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode()
    code_digest = _digest("code", str(identifier) + ":" + body.code)
    try:
        with psycopg.connect(_db_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT provider, challenge, authorization_hash,
                    verified_email, telegram_user
                FROM vainah_mobile_auth
                WHERE flow_id=%s AND status='ready'
                    AND expires_at > now()
                    AND authorization_expires_at > now()
                FOR UPDATE
            """, (identifier,))
            row = cur.fetchone()
            if (row is None or not hmac.compare_digest(row[1], challenge)
                    or not row[2] or not hmac.compare_digest(row[2], code_digest)):
                raise HTTPException(400, "OAUTH_CODE_INVALID")
            provider, _challenge, _digest_value, email, telegram = row
            if provider == "google":
                if not isinstance(email, str) or not email:
                    raise HTTPException(400, "OAUTH_IDENTITY_INVALID")
                cookie_name = EMAIL_SESSION_COOKIE
                token = _sign_session(email)
            else:
                try:
                    user = json.loads(telegram)
                except (ValueError, TypeError):
                    raise HTTPException(400, "OAUTH_IDENTITY_INVALID") from None
                cookie_name = SESSION_COOKIE
                token = make_session(user, _secret())
            cur.execute("""
                UPDATE vainah_mobile_auth
                SET status='consumed', authorization_hash=NULL,
                    verified_email=NULL, telegram_user=NULL
                WHERE flow_id=%s AND status='ready'
            """, (identifier,))
            if cur.rowcount != 1:
                raise HTTPException(400, "OAUTH_CODE_INVALID")
        return {
            "authenticated": True,
            "provider": provider,
            "cookie_name": cookie_name,
            "session": token,
        }
    except psycopg.Error:
        raise HTTPException(503, "MOBILE_AUTH_DATABASE_UNAVAILABLE") from None
