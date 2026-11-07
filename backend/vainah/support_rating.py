"""Private post-reply support rating (1–5 stars), no identifying data."""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .email_delivery import database_url
from .support_tickets import TICKET_ID_RE, _owner, _require_operator, _schema
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/support", tags=["Support quality"])


class TicketRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5)


def _save(owner: str, ticket_id: str, rating: int) -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_support_tickets SET
                    customer_rating=%s
                WHERE ticket_id=%s AND owner_hash=%s
                  AND operator_reply IS NOT NULL
                RETURNING ticket_id
            """, (rating, ticket_id, owner))
            if cur.fetchone() is None:
                raise HTTPException(404, "SUPPORT_RATING_NOT_AVAILABLE")
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


def _read(owner: str | None, ticket_id: str) -> int | None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            if owner is None:
                cur.execute(
                    "SELECT customer_rating FROM vainah_support_tickets WHERE ticket_id=%s",
                    (ticket_id,),
                )
            else:
                cur.execute(
                    "SELECT customer_rating FROM vainah_support_tickets WHERE ticket_id=%s AND owner_hash=%s",
                    (ticket_id, owner),
                )
            row=cur.fetchone()
            if row is None:
                raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
            return row[0]
    except psycopg.Error:
        raise HTTPException(503, "SUPPORT_DATABASE_UNAVAILABLE") from None


@router.post("/tickets/{ticket_id}/rating")
def rate_ticket(request: Request, ticket_id: str, body: TicketRating) -> dict:
    require_same_origin(request)
    owner=_owner(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    _save(owner, ticket_id, body.rating)
    return {"saved": True, "rating": body.rating}


@router.get("/tickets/{ticket_id}/rating")
def get_rating(request: Request, ticket_id: str) -> dict:
    owner=_owner(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    return {"rating": _read(owner, ticket_id)}


@router.get("/operator/tickets/{ticket_id}/rating")
def operator_rating(request: Request, ticket_id: str) -> dict:
    _require_operator(request)
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise HTTPException(404, "SUPPORT_TICKET_NOT_FOUND")
    return {"rating": _read(None, ticket_id)}
