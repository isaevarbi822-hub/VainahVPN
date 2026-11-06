"""Owner-scoped follow-up messages for existing support tickets.

No attachments, VPN URLs or credential disclosures. Existing ticket records
and the latest operator reply remain compatible with the old support UI.
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .email_delivery import database_url
from .support_tickets import (
    LINK_RE, TICKET_ID_RE, _owner, _require_operator, _schema as ticket_schema,
)
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/support", tags=["Ticket conversation"])


class CustomerFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=4, max_length=1500)


def _schema(cur):
    ticket_schema(cur)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_support_messages (
            message_id BIGSERIAL PRIMARY KEY,
            ticket_id VARCHAR(30) NOT NULL REFERENCES vainah_support_tickets(ticket_id),
            sender VARCHAR(10) NOT NULL CHECK (sender IN ('customer','operator')),
            content TEXT NOT NULL CHECK (char_length(content) BETWEEN 2 AND 1500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_support_messages_ticket_idx
        ON vainah_support_messages(ticket_id, message_id ASC)
    """)


def append_operator_reply(cur, ticket_id: str, message: str) -> None:
    """Runs within the existing operator update transaction."""
    _schema(cur)
    cur.execute("""
        INSERT INTO vainah_support_messages(ticket_id, sender, content)
        VALUES (%s, 'operator', %s)
    """, (ticket_id, message))


def _history(ticket_id: str, owner: str | None) -> list[dict]:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            if owner is None:
                cur.execute("""
                    SELECT message, operator_reply, created_at, updated_at
                    FROM vainah_support_tickets WHERE ticket_id=%s
                """, (ticket_id,))
            else:
                cur.execute("""
                    SELECT message, operator_reply, created_at, updated_at
                    FROM vainah_support_tickets
                    WHERE ticket_id=%s AND owner_hash=%s
                """, (ticket_id, owner))
            ticket=cur.fetchone()
            if ticket is None:
                raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
            cur.execute("""
                SELECT sender, content, created_at
                FROM vainah_support_messages
                WHERE ticket_id=%s ORDER BY message_id ASC LIMIT 50
            """, (ticket_id,))
            records=cur.fetchall()
            result=[{"sender":"customer","message":ticket[0],
                     "created_at":ticket[2].isoformat()}]
            result.extend({"sender":row[0],"message":row[1],
                           "created_at":row[2].isoformat()} for row in records)
            # Existing pre-migration replies did not create message records.
            if ticket[1] and not any(
                row[0] == "operator" and row[1] == ticket[1] for row in records
            ):
                result.append({"sender":"operator","message":ticket[1],
                               "created_at":ticket[3].isoformat()})
            return result
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _followup(owner: str, ticket_id: str, message: str) -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT status FROM vainah_support_tickets
                WHERE ticket_id=%s AND owner_hash=%s FOR UPDATE
            """, (ticket_id, owner))
            row=cur.fetchone()
            if row is None:
                raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
            if row[0] == "closed":
                raise HTTPException(409, "SUPPORT_TICKET_CLOSED")
            cur.execute("""
                SELECT COUNT(*) FROM vainah_support_messages
                WHERE ticket_id=%s AND sender='customer'
            """, (ticket_id,))
            if cur.fetchone()[0] >= 20:
                raise HTTPException(429, "SUPPORT_THREAD_LIMIT")
            cur.execute("""
                SELECT created_at > now() - interval '60 seconds'
                FROM vainah_support_messages
                WHERE ticket_id=%s AND sender='customer'
                ORDER BY message_id DESC LIMIT 1
            """, (ticket_id,))
            recent=cur.fetchone()
            if recent and recent[0]:
                raise HTTPException(429, "SUPPORT_FOLLOWUP_COOLDOWN")
            cur.execute("""
                INSERT INTO vainah_support_messages(ticket_id, sender, content)
                VALUES (%s,'customer',%s)
            """, (ticket_id, message))
            cur.execute("""
                UPDATE vainah_support_tickets SET status='open',updated_at=now()
                WHERE ticket_id=%s AND owner_hash=%s
            """, (ticket_id, owner))
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


@router.get("/tickets/{ticket_id}/messages")
def owned_messages(request: Request, ticket_id: str) -> dict:
    owner = _owner(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    return {"items": _history(ticket_id, owner)}


@router.post("/tickets/{ticket_id}/messages", status_code=201)
def send_followup(request: Request, ticket_id: str, body: CustomerFollowup) -> dict:
    require_same_origin(request)
    owner = _owner(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    message=body.message.strip()
    if len(message) < 4 or LINK_RE.search(message):
        raise HTTPException(422, "SUPPORT_PRIVATE_LINK_BLOCKED")
    _followup(owner, ticket_id, message)
    return {"saved":True,"status":"open"}


@router.get("/operator/tickets/{ticket_id}/messages")
def operator_messages(request: Request, ticket_id: str) -> dict:
    _require_operator(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    return {"items": _history(ticket_id, None)}
