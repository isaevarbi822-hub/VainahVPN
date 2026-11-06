"""Private 5-minute, one-use QR handoff to another signed-in device.

The QR contains only a single-use high-entropy token in a URL fragment, NEVER
a permanent VLESS/HTTPS subscription key. Redemption requires the SAME
verified email account and an independently confirmed paid H1 subscription.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from io import BytesIO
from urllib.parse import urlsplit

import psycopg
import qrcode
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from qrcode.image.svg import SvgPathImage
from qrcode.constants import ERROR_CORRECT_M

from .customer_portal import access
from .email_delivery import database_url
from .growth import _email, _owner
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/account/handoff", tags=["Private QR handoff"])
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")


class RedeemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")


def _origin() -> str:
    origin = os.environ.get(
        "PUBLIC_SITE_ORIGIN", "https://vainahvpn-python-preview.onrender.com"
    ).rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.netloc
            or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise HTTPException(503, "HANDOFF_PUBLIC_ORIGIN_INVALID")
    return origin


def _schema(cur) -> None:
    cur.execute("""
        SELECT set_config('lock_timeout','4000ms',TRUE),
               set_config('statement_timeout','8000ms',TRUE)
    """)
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_handoff_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_qr_handoffs (
            token_hash CHAR(64) PRIMARY KEY,
            owner_hash CHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            used_at TIMESTAMPTZ
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_qr_handoffs_owner
        ON vainah_qr_handoffs(owner_hash, created_at DESC)
    """)


def _digest(token: str) -> str:
    return hashlib.sha256(("vainah-qr-handoff-v1:" + token).encode()).hexdigest()


def _issue(owner: str) -> str:
    token = secrets.token_urlsafe(24)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 3328)", (owner,))
            cur.execute("""
                SELECT count(*) FROM vainah_qr_handoffs
                WHERE owner_hash=%s AND created_at > now()-interval '15 minutes'
            """, (owner,))
            if int(cur.fetchone()[0]) >= 3:
                raise HTTPException(429, "HANDOFF_RATE_LIMIT")
            cur.execute("""
                INSERT INTO vainah_qr_handoffs(token_hash,owner_hash,expires_at)
                VALUES (%s,%s,now()+interval '5 minutes')
            """, (_digest(token), owner))
    except psycopg.Error:
        raise HTTPException(503, "HANDOFF_DATABASE_UNAVAILABLE") from None
    return token


def _consume(owner: str, token: str) -> bool:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_qr_handoffs SET used_at=now()
                WHERE token_hash=%s AND owner_hash=%s
                  AND used_at IS NULL AND expires_at>now()
                RETURNING token_hash
            """, (_digest(token), owner))
            return cur.fetchone() is not None
    except psycopg.Error:
        raise HTTPException(503, "HANDOFF_DATABASE_UNAVAILABLE") from None


@router.post("/qr")
async def create_handoff_qr(request: Request) -> Response:
    require_same_origin(request)
    owner = _owner(_email(request))
    # Do not create transferable tokens for unpaid or unprovisioned users.
    await access(request)
    token = _issue(owner)
    destination = _origin() + "/handoff.html#t=" + token
    try:
        qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=5, border=4)
        qr.add_data(destination)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        buffer = BytesIO()
        image.save(buffer)
        body = buffer.getvalue()
        if not body or len(body) > 500_000:
            raise ValueError("HANDOFF_QR_SIZE")
    except (ValueError, OverflowError, qrcode.exceptions.DataOverflowError):
        raise HTTPException(422, "HANDOFF_QR_UNSUPPORTED") from None
    return Response(content=body, media_type="image/svg+xml", headers={
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "Content-Disposition": 'inline; filename="vainah-one-time-handoff.svg"',
        "Content-Security-Policy": "default-src 'none'; script-src 'none'; sandbox",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/redeem")
async def redeem_handoff(request: Request, body: RedeemInput) -> dict:
    require_same_origin(request)
    owner = _owner(_email(request))
    # Independently validate active paid access again before releasing a key.
    result = await access(request)
    if not _consume(owner, body.token):
        raise HTTPException(404, "HANDOFF_EXPIRED_OR_ALREADY_USED")
    value = result.get("subscription_url")
    if not isinstance(value, str) or not value.startswith("https://"):
        raise HTTPException(503, "HANDOFF_ACCESS_UNAVAILABLE")
    return {
        "redeemed": True,
        "subscription_url": value,
        "message": "Ключ выдан только авторизованному владельцу и токен погашен.",
    }
