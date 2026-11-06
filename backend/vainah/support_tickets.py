"""Private, rate-limited support tickets with operator replies.

Tickets are scoped to a signed email or Telegram session. Only pseudonymous
HMAC owner hashes are stored (no email or chat ID). An operator key must be
configured before tickets can be accepted; otherwise use the Telegram contact.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .email_auth import current_email
from .email_delivery import database_url
from .telegram_auth import current_user, require_same_origin

router = APIRouter(prefix="/api/support", tags=["Verified customer support"])
TICKET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{18,30}$")
# We deliberately do not take attachments or private VPN URLs.
LINK_RE = re.compile(
    r"(?:https?://|vless://|vmess://|trojan://|hysteria2?://|ss://|"
    r"subscription[_ -]?url\s*[:=])", re.IGNORECASE
)
CATEGORIES = ("connection", "payment", "account", "other")
STATUSES = ("open", "answered", "closed")


class NewTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=3, max_length=20)
    message: str = Field(min_length=12, max_length=1500)


class OperatorReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str = Field(min_length=2, max_length=1500)
    status: str = Field(default="answered", pattern="^(answered|closed)$")


def _operator_key() -> str | None:
    value = os.environ.get("VAINAH_SUPPORT_OPERATOR_KEY", "")
    return value if len(value) >= 40 and value != os.environ.get(
        "SESSION_SIGNING_KEY", ""
    ) else None


def _require_operator(request: Request) -> None:
    correct = _operator_key()
    if correct is None:
        raise HTTPException(503, "SUPPORT_OPERATOR_NOT_CONFIGURED")
    supplied = request.headers.get("X-Vainah-Support-Key", "")
    if len(supplied) > 256 or not hmac.compare_digest(correct, supplied):
        raise HTTPException(403, "SUPPORT_OPERATOR_FORBIDDEN")


def _owner(request: Request) -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "SUPPORT_NOT_CONFIGURED")
    account = current_user(request)
    if account is not None:
        principal = "telegram:" + account["telegram_id"]
    else:
        email = current_email(request)
        if email is None:
            raise HTTPException(401, "SUPPORT_LOGIN_REQUIRED")
        principal = "email:" + email
    return hmac.new(
        secret.encode(), ("support-ticket-v1\n" + principal).encode(),
        hashlib.sha256,
    ).hexdigest()


def _schema(cur) -> None:
    cur.execute("""
        SELECT set_config('lock_timeout','4000ms',TRUE),
               set_config('statement_timeout','8000ms',TRUE)
    """)
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_support_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_support_tickets (
            ticket_id VARCHAR(30) PRIMARY KEY,
            owner_hash CHAR(64) NOT NULL,
            category VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            operator_reply TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT vainah_support_status_valid
                CHECK (status IN ('open','answered','closed'))
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_support_owner_idx
        ON vainah_support_tickets (owner_hash, created_at DESC)
    """)


def _ticket(row: tuple, *, operator: bool = False) -> dict:
    result = {
        "id": row[0], "category": row[1], "message": row[2],
        "status": row[3], "reply": row[4],
        "created_at": row[5].isoformat(),
        "updated_at": row[6].isoformat(),
    }
    if operator:
        result["owner_reference"] = row[7][:12]  # Not an email or Telegram ID.
    return result


def _create(owner: str, category: str, message: str) -> dict:
    identifier = secrets.token_urlsafe(18)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            # Serialize per owner to prevent concurrent requests bypassing the limit.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 7149)", (owner,))
            cur.execute("""
                SELECT count(*) FROM vainah_support_tickets
                WHERE owner_hash=%s AND created_at > now() - interval '24 hours'
            """, (owner,))
            if cur.fetchone()[0] >= 3:
                raise HTTPException(429, "SUPPORT_DAILY_LIMIT")
            cur.execute("""
                INSERT INTO vainah_support_tickets (
                    ticket_id, owner_hash, category, message
                ) VALUES (%s, %s, %s, %s)
            """, (identifier, owner, category, message))
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None
    return {"id": identifier, "status": "open"}


def _owned(owner: str) -> list[dict]:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT ticket_id, category, message, status, operator_reply,
                       created_at, updated_at
                FROM vainah_support_tickets
                WHERE owner_hash=%s ORDER BY created_at DESC LIMIT 25
            """, (owner,))
            return [_ticket(row) for row in cur.fetchall()]
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _operator_list() -> list[dict]:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT ticket_id, category, message, status, operator_reply,
                       created_at, updated_at, owner_hash
                FROM vainah_support_tickets
                ORDER BY created_at DESC LIMIT 100
            """)
            return [_ticket(row, operator=True) for row in cur.fetchall()]
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _operator_reply(identifier: str, reply: str, status: str) -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_support_tickets
                SET operator_reply=%s, status=%s, updated_at=now()
                WHERE ticket_id=%s
                RETURNING ticket_id
            """, (reply, status, identifier))
            if cur.fetchone() is None:
                raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


@router.get("/config")
def config() -> dict:
    return {
        "available": _operator_key() is not None and bool(
            os.environ.get("DATABASE_URL", "").startswith(
                ("postgresql://", "postgres://")
            )
        ),
        "login_required": True,
        "message": (
            "Support tickets can be created by signed-in customers."
            if _operator_key() else
            "Support ticket service is not configured. Use Telegram support."
        ),
    }


@router.get("/tickets")
def list_owned(request: Request) -> dict:
    return {"items": _owned(_owner(request))}


@router.post("/tickets", status_code=201)
def create(request: Request, body: NewTicket) -> dict:
    require_same_origin(request)
    owner = _owner(request)
    if _operator_key() is None:
        raise HTTPException(503, "SUPPORT_OPERATOR_NOT_CONFIGURED")
    category = body.category.strip()
    message = body.message.strip()
    if category not in CATEGORIES:
        raise HTTPException(422, "SUPPORT_CATEGORY_INVALID")
    if len(message) < 12 or LINK_RE.search(message):
        raise HTTPException(422, "SUPPORT_PRIVATE_LINK_BLOCKED")
    return _create(owner, category, message)


@router.get("/operator/tickets")
def list_operator(request: Request) -> dict:
    _require_operator(request)
    return {"items": _operator_list()}


@router.post("/operator/tickets/{ticket_id}/reply")
def reply(request: Request, ticket_id: str, body: OperatorReply) -> dict:
    require_same_origin(request)
    _require_operator(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    message = body.reply.strip()
    if len(message) < 2 or LINK_RE.search(message):
        raise HTTPException(422, "SUPPORT_REPLY_INVALID")
    _operator_reply(ticket_id, message, body.status)
    return {"updated": True}
