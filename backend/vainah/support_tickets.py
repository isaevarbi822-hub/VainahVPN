"""Private, rate-limited support tickets with operator replies.

Tickets are scoped to a signed email or Telegram session. Only pseudonymous
HMAC owner hashes are stored (no email or chat ID). An operator key must be
configured before tickets can be accepted; otherwise use the Telegram contact.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets

import psycopg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .email_auth import current_email
from .email_delivery import (
    database_url,
    email_service_ready,
    send_email,
    verified_email,
)
from .google_auth import _origin
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
    notify_email: StrictBool = False


class NotifyPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


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


def _fernet() -> Fernet:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "SUPPORT_NOT_CONFIGURED")
    raw = hashlib.sha256(("vainah-support-email-encryption-v1\n" + secret).encode())
    return Fernet(base64.urlsafe_b64encode(raw.digest()))


def _verified_contact(request: Request) -> str:
    # Telegram must prove mailbox ownership via the existing email challenge.
    # A simultaneous email cookie must not silently redirect Telegram tickets.
    telegram = current_user(request)
    if telegram:
        email = verified_email(telegram["telegram_id"])
    else:
        email = current_email(request)
    if not email:
        raise HTTPException(409, "SUPPORT_EMAIL_VERIFICATION_REQUIRED")
    if not email_service_ready():
        raise HTTPException(503, "EMAIL_DELIVERY_NOT_CONFIGURED")
    return email


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
    # Idempotent migrations preserve existing tickets and operator replies.
    cur.execute("""
        ALTER TABLE vainah_support_tickets
        ADD COLUMN IF NOT EXISTS notify_email BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS email_ciphertext TEXT,
        ADD COLUMN IF NOT EXISTS notification_revision BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS notification_state VARCHAR(16) NOT NULL DEFAULT 'none',
        ADD COLUMN IF NOT EXISTS notification_attempted_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMPTZ
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
        result["email_notifications"] = bool(row[8])
        result["notification_state"] = row[9]
    else:
        result["email_notifications"] = bool(row[7])
        result["notification_state"] = row[8]
    return result


def _create(owner: str, category: str, message: str,
            encrypted_email: str | None = None) -> dict:
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
                    ticket_id, owner_hash, category, message,
                    notify_email, email_ciphertext
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (identifier, owner, category, message,
                  encrypted_email is not None, encrypted_email))
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None
    return {"id": identifier, "status": "open"}


def _owned(owner: str) -> list[dict]:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT ticket_id, category, message, status, operator_reply,
                       created_at, updated_at, notify_email,
                       notification_state
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
                       created_at, updated_at, owner_hash,
                       notify_email, notification_state
                FROM vainah_support_tickets
                ORDER BY created_at DESC LIMIT 100
            """)
            return [_ticket(row, operator=True) for row in cur.fetchall()]
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _operator_reply(identifier: str, reply: str, status: str) -> dict:
    """A changed answer schedules exactly one notification revision.

    Same reply text + new status does not resend the same notification.
    All writes happen atomically before any network request to Resend.
    """
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT operator_reply, notify_email, email_ciphertext,
                       notification_revision, notification_state
                FROM vainah_support_tickets WHERE ticket_id=%s FOR UPDATE
            """, (identifier,))
            previous = cur.fetchone()
            if previous is None:
                raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
            changed = previous[0] != reply
            send = changed and bool(previous[1]) and bool(previous[2])
            next_revision = int(previous[3]) + (1 if send else 0)
            next_state = ("pending" if send else
                          "none" if changed else previous[4])
            cur.execute("""
                UPDATE vainah_support_tickets
                SET operator_reply=%s, status=%s, updated_at=now(),
                    notification_revision=%s, notification_state=%s,
                    notification_attempted_at=CASE WHEN %s THEN NULL
                                                   ELSE notification_attempted_at END,
                    notification_sent_at=CASE WHEN %s THEN NULL
                                              ELSE notification_sent_at END
                WHERE ticket_id=%s
            """, (reply, status, next_revision, next_state,
                  changed, changed, identifier))
            return {"notification": next_state, "revision": next_revision}
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _set_notifications(owner: str, identifier: str,
                       ciphertext: str | None) -> bool:
    """Only ticket owner can change delivery preferences.

    Enrollment never mails an old reply retroactively.
    """
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_support_tickets
                SET notify_email=%s, email_ciphertext=%s,
                    notification_state='none',
                    notification_attempted_at=NULL,
                    notification_sent_at=NULL
                WHERE ticket_id=%s AND owner_hash=%s
                RETURNING ticket_id
            """, (ciphertext is not None, ciphertext, identifier, owner))
            return cur.fetchone() is not None
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _claim_notification(identifier: str) -> tuple[int, str] | None:
    """Lease one pending email; never hold a DB transaction during network IO."""
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_support_tickets
                SET notification_attempted_at=now()
                WHERE ticket_id=%s AND notify_email=TRUE
                  AND email_ciphertext IS NOT NULL
                  AND notification_state='pending'
                  AND (notification_attempted_at IS NULL
                       OR notification_attempted_at < now() - interval '2 minutes')
                RETURNING notification_revision, email_ciphertext
            """, (identifier,))
            row = cur.fetchone()
            return (int(row[0]), str(row[1])) if row else None
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _finish_notification(identifier: str, revision: int, sent: bool) -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_support_tickets
                SET notification_state=%s,
                    notification_sent_at=CASE WHEN %s THEN now()
                                              ELSE notification_sent_at END
                WHERE ticket_id=%s AND notification_revision=%s
                  AND notification_state='pending' AND notify_email=TRUE
            """, ("sent" if sent else "pending", sent, identifier, revision))
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


async def _notify_reply(identifier: str) -> str:
    """Send promptly, retaining a retryable state if Resend is unavailable."""
    claim = await run_in_threadpool(_claim_notification, identifier)
    if claim is None:
        return "not_pending"
    revision, encrypted = claim
    try:
        recipient = _fernet().decrypt(encrypted.encode()).decode()
        origin = _origin()
        if not origin:
            raise ValueError("SUPPORT_PUBLIC_ORIGIN_INVALID")
        body = (
            "<p>Служба поддержки Vainah VPN ответила на твоё обращение.</p>"
            "<p>Чтобы прочитать ответ, войди в свой аккаунт:</p>"
            '<p><a href="' + origin +
            '/support-center.html">Открыть мои обращения</a></p>'
            "<p>В этом письме нет VPN-ключей и данных платежа.</p>"
        )
        await send_email(
            recipient, "Vainah VPN — ответ службы поддержки", body,
            idempotency_key=f"vainah-support-reply-{identifier}-{revision}",
        )
    except (HTTPException, ValueError, InvalidToken, UnicodeDecodeError):
        await run_in_threadpool(_finish_notification, identifier, revision, False)
        return "pending"
    await run_in_threadpool(_finish_notification, identifier, revision, True)
    return "sent"


@router.get("/config")
def config() -> dict:
    return {
        "available": _operator_key() is not None and bool(
            os.environ.get("DATABASE_URL", "").startswith(
                ("postgresql://", "postgres://")
            )
        ),
        "login_required": True,
        "email_notifications_available": email_service_ready(),
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
    encrypted = None
    if body.notify_email:
        encrypted = _fernet().encrypt(_verified_contact(request).encode()).decode()
    return _create(owner, category, message, encrypted)


@router.post("/tickets/{ticket_id}/email-notifications")
def configure_notifications(request: Request, ticket_id: str,
                            body: NotifyPreference) -> dict:
    require_same_origin(request)
    owner = _owner(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    ciphertext = None
    if body.enabled:
        ciphertext = _fernet().encrypt(_verified_contact(request).encode()).decode()
    if not _set_notifications(owner, ticket_id, ciphertext):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    return {"updated": True, "email_notifications": body.enabled}


@router.get("/operator/tickets")
def list_operator(request: Request) -> dict:
    _require_operator(request)
    return {"items": _operator_list()}


@router.post("/operator/tickets/{ticket_id}/reply")
async def reply(request: Request, ticket_id: str, body: OperatorReply) -> dict:
    require_same_origin(request)
    _require_operator(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    message = body.reply.strip()
    if len(message) < 2 or LINK_RE.search(message):
        raise HTTPException(422, "SUPPORT_REPLY_INVALID")
    stored = await run_in_threadpool(_operator_reply, ticket_id, message, body.status)
    notification = stored.get("notification", "none") if stored else "none"
    if notification == "pending":
        try:
            notification = await _notify_reply(ticket_id)
        except HTTPException:
            notification = "pending"
    return {"updated": True, "notification": notification}


@router.post("/operator/tickets/{ticket_id}/retry-email")
async def retry_email(request: Request, ticket_id: str) -> dict:
    require_same_origin(request)
    _require_operator(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    try:
        outcome = await _notify_reply(ticket_id)
    except HTTPException:
        outcome = "pending"
    return {"notification": outcome}
