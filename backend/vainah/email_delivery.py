"""Verified delivery email management for signed Telegram accounts.

No account may claim another person's email without a time-limited code.
Resend is only used after verified provider configuration; no secret is logged.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import secrets
from email.utils import parseaddr

import httpx
import psycopg
from fastapi import HTTPException
from psycopg.errors import UniqueViolation

CODE_TTL_MINUTES = 10
COOLDOWN_SECONDS = 90
MAX_ATTEMPTS = 5


def email_service_ready() -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    address = os.environ.get("VAINAH_EMAIL_FROM", "")
    return (
        len(api_key) >= 16
        and 5 <= len(address) <= 254
        and parseaddr(address)[1].count("@") == 1
    )


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw.startswith(("postgresql://", "postgres://")):
        raise HTTPException(503, "ACCOUNT_DATABASE_NOT_CONFIGURED")
    return raw


def code_digest(telegram_id: str, email: str, code: str, secret: str) -> str:
    payload = f"{telegram_id}\n{email}\n{code}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def schema(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vainah_verified_customer_emails (
            telegram_id VARCHAR(18) PRIMARY KEY,
            email VARCHAR(254) NOT NULL UNIQUE,
            verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vainah_email_challenges (
            telegram_id VARCHAR(18) PRIMARY KEY,
            email VARCHAR(254) NOT NULL,
            code_hash CHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            next_send_at TIMESTAMPTZ NOT NULL,
            attempts INT NOT NULL DEFAULT 0
        )
    """)


def verified_email(telegram_id: str) -> str | None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn:
            with conn.cursor() as cur:
                schema(cur)
                cur.execute("""
                    SELECT email FROM vainah_verified_customer_emails
                    WHERE telegram_id = %s
                """, (telegram_id,))
                row = cur.fetchone()
                return str(row[0]) if row else None
    except psycopg.Error:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None


def start_challenge(telegram_id: str, email: str) -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "EMAIL_VERIFY_NOT_CONFIGURED")
    code = f"{secrets.randbelow(1000000):06d}"
    digest = code_digest(telegram_id, email, code, secret)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn:
            with conn.cursor() as cur:
                schema(cur)
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 72043)",
                            (telegram_id,))
                cur.execute("""
                    SELECT next_send_at > now() FROM vainah_email_challenges
                    WHERE telegram_id = %s
                """, (telegram_id,))
                row = cur.fetchone()
                if row and row[0]:
                    raise HTTPException(429, "EMAIL_VERIFY_COOLDOWN")
                cur.execute("""
                    INSERT INTO vainah_email_challenges (
                        telegram_id, email, code_hash, expires_at, next_send_at, attempts
                    ) VALUES (
                        %s, %s, %s, now() + interval '10 minutes',
                        now() + interval '90 seconds', 0
                    )
                    ON CONFLICT (telegram_id) DO UPDATE SET
                        email = EXCLUDED.email,
                        code_hash = EXCLUDED.code_hash,
                        expires_at = EXCLUDED.expires_at,
                        next_send_at = EXCLUDED.next_send_at,
                        attempts = 0
                """, (telegram_id, email, digest))
    except psycopg.Error:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None
    return code


def cancel_challenge(telegram_id: str, code: str, email: str) -> None:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    digest = code_digest(telegram_id, email, code, secret)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM vainah_email_challenges
                    WHERE telegram_id = %s AND code_hash = %s
                """, (telegram_id, digest))
    except psycopg.Error:
        return


def confirm_challenge(telegram_id: str, code: str) -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32 or not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(400, "EMAIL_CODE_INVALID")
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn:
            with conn.cursor() as cur:
                schema(cur)
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 72043)",
                            (telegram_id,))
                cur.execute("""
                    SELECT email, code_hash, expires_at > now(), attempts
                    FROM vainah_email_challenges WHERE telegram_id = %s
                    FOR UPDATE
                """, (telegram_id,))
                row = cur.fetchone()
                if not row or not row[2] or row[3] >= MAX_ATTEMPTS:
                    raise HTTPException(400, "EMAIL_CODE_EXPIRED")
                email, expected = str(row[0]), str(row[1])
                if not hmac.compare_digest(
                    code_digest(telegram_id, email, code, secret), expected
                ):
                    cur.execute("""
                        UPDATE vainah_email_challenges
                        SET attempts = attempts + 1
                        WHERE telegram_id = %s
                    """, (telegram_id,))
                    # Commit attempt count before returning 400.
                    conn.commit()
                    raise HTTPException(400, "EMAIL_CODE_INVALID")
                try:
                    cur.execute("""
                        INSERT INTO vainah_verified_customer_emails (
                            telegram_id, email, verified_at
                        ) VALUES (%s, %s, now())
                        ON CONFLICT (telegram_id) DO UPDATE SET
                            email = EXCLUDED.email, verified_at = now()
                    """, (telegram_id, email))
                    cur.execute("""
                        DELETE FROM vainah_email_challenges
                        WHERE telegram_id = %s
                    """, (telegram_id,))
                except UniqueViolation:
                    raise HTTPException(409, "EMAIL_ALREADY_LINKED") from None
                return email
    except psycopg.Error:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None


async def send_email(to: str, subject: str, body: str, *,
                     transport: httpx.AsyncBaseTransport | None = None) -> None:
    if not email_service_ready():
        raise HTTPException(503, "EMAIL_DELIVERY_NOT_CONFIGURED")
    sender = os.environ["VAINAH_EMAIL_FROM"]
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False,
            transport=transport
        ) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": "Bearer " + os.environ["RESEND_API_KEY"],
                    "Content-Type": "application/json",
                },
                json={
                    "from": sender, "to": [to],
                    "subject": subject,
                    "html": "<html><body>" + body + "</body></html>",
                },
            )
    except (httpx.RequestError, httpx.TimeoutException):
        raise HTTPException(503, "EMAIL_DELIVERY_UNAVAILABLE") from None
    if response.status_code not in (200, 201, 202):
        raise HTTPException(503, "EMAIL_DELIVERY_UNAVAILABLE")


async def send_verification_code(email: str, code: str, *,
                                 transport: httpx.AsyncBaseTransport | None = None):
    await send_email(
        email,
        "Vainah VPN — подтверждение почты",
        "<p>Твой код подтверждения:</p><h2>" + html.escape(code) +
        "</h2><p>Код действует 10 минут. Никому его не передавай.</p>",
        transport=transport,
    )


async def email_paid_subscription(
    telegram_id: str, order_id: str, subscription_url: str, *,
    transport: httpx.AsyncBaseTransport | None = None
) -> bool:
    """Internal delivery hook. The caller MUST first verify paid + delivered
    entitlement ownership. Never expose this function via a public API.
    """
    email = verified_email(telegram_id)
    if not email:
        return False
    from urllib.parse import urlsplit

    parsed = urlsplit(subscription_url)
    if (parsed.scheme != "https" or not parsed.hostname or
            parsed.username or parsed.password or parsed.fragment or
            len(subscription_url) > 2048 or
            re.search(r"\s", subscription_url)):
        raise ValueError("INVALID_SUBSCRIPTION_URL")
    await send_email(
        email,
        "Vainah VPN — твоя личная подписка",
        "<p>Подписка для подтверждённой покупки " +
        html.escape(order_id) + ":</p><p><a href=\"" +
        html.escape(subscription_url, quote=True) + "\">" +
        html.escape(subscription_url) +
        "</a></p><p>Это личная VPN-ссылка. Не пересылай её другим.</p>",
        transport=transport,
    )
    return True
