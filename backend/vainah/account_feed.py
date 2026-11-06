"""Owner-scoped inbox from real paid-account/H1Cloud observations.

No fabricated connectivity claims or speculative notifications. The user can
acknowledge actual generated alerts; read state is stored only for that owner.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .customer_portal import overview as customer_overview
from .email_delivery import database_url
from .growth import _email, _owner
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/account/notifications", tags=["Customer notification inbox"])
DAY = 86400


class MarkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notification_id: str = Field(pattern=r"^[a-f0-9]{64}$")


def _schema(cur) -> None:
    cur.execute("""
        SELECT set_config('lock_timeout','4000ms',TRUE),
               set_config('statement_timeout','8000ms',TRUE)
    """)
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_account_feed_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_account_feed_read (
            owner_hash CHAR(64) NOT NULL,
            notification_id CHAR(64) NOT NULL,
            read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (owner_hash, notification_id)
        )
    """)


def _event_id(owner: str, kind: str, scope: str) -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "FEED_NOT_CONFIGURED")
    return hmac.new(
        secret.encode(),
        ("vainah-account-feed-v1:" + owner + ":" + kind + ":" + scope).encode(),
        hashlib.sha256,
    ).hexdigest()


def _notifications(owner: str, data: dict) -> list[dict]:
    orders = data.get("orders") if isinstance(data.get("orders"), list) else []
    sub = data.get("subscription") if isinstance(data.get("subscription"), dict) else {}
    h1 = data.get("h1cloud") if isinstance(data.get("h1cloud"), dict) else {}
    has_paid = any(
        isinstance(o, dict) and o.get("paid") is True
        and (o.get("delivered") is True or o.get("status") == "delivered")
        for o in orders
    )
    confirmed = sub.get("paid") is True and sub.get("status") == "delivered"
    results = []

    def emit(kind, scope, title, detail, level, url):
        results.append({
            "id": _event_id(owner, kind, scope),
            "type": kind, "title": title, "description": detail,
            "level": level, "href": url,
        })

    if has_paid and not confirmed and h1.get("status") in (
        "unavailable", "inactive", "not_found", "not_configured"
    ):
        emit(
            "provider_check", str(h1.get("status")),
            "Состояние оплаченной подписки требует проверки",
            "H1Cloud не подтвердил активный профиль в этой проверке. Не оплачивай второй раз из-за этого сообщения.",
            "warning" if h1.get("status") in ("inactive", "not_found") else "info",
            "/support-center.html",
        )

    if confirmed:
        raw_expiry = sub.get("expires_at")
        try:
            expiry = datetime.fromisoformat(raw_expiry)
            delta = (expiry - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, AttributeError):
            delta = None
            expiry = None
        if delta is not None and expiry is not None and expiry.tzinfo is not None:
            scope = expiry.isoformat()
            if delta <= 0:
                emit(
                    "expiry", "passed:" + scope,
                    "Дата окончания H1Cloud уже прошла",
                    "Обнови данные и уточни состояние подписки. Это не доказательство отключения VPN.",
                    "warning", "/account.html",
                )
            elif delta <= DAY * 3:
                emit(
                    "expiry", "three:" + scope,
                    "Подписка заканчивается в ближайшие 3 дня",
                    "Дата получена от H1Cloud. Проверь продление в кабинете.",
                    "warning", "/account.html",
                )
            elif delta <= DAY * 7:
                emit(
                    "expiry", "seven:" + scope,
                    "Подписка заканчивается в ближайшие 7 дней",
                    "Дата получена от H1Cloud. Доступно напоминание в календаре.",
                    "info", "/account.html",
                )

        traffic = sub.get("traffic") if isinstance(sub.get("traffic"), dict) else {}
        used, limit = traffic.get("used_bytes"), traffic.get("limit_bytes")
        if type(used) is int and type(limit) is int and used >= 0 and limit > 0:
            fraction = used / limit
            bucket = 100 if fraction >= 1 else 90 if fraction >= .9 else 75 if fraction >= .75 else 0
            if bucket:
                scope = str(bucket) + ":" + str(sub.get("order_id") or sub.get("expires_at") or "")
                emit(
                    "traffic", scope, "Использовано " + str(bucket) + "% лимита трафика",
                    "Расчёт основан на доступных счётчиках H1Cloud; данные могут обновляться с задержкой.",
                    "warning" if bucket >= 90 else "info", "/account.html",
                )
    return results[:12]



def _gift_alerts(owner: str, email: str) -> list[dict]:
    """Only paid, verified gift lifecycle events; no voucher code is read."""
    from .live_checkout import live_account_ready, owner_ref_for_email
    from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger

    if not live_account_ready():
        return []
    try:
        rows = PostgresLiveOrderLedger(database_url()).owner_gift_notification_states(
            owner_ref_for_email(email)
        )
    except (LiveLedgerError, HTTPException):
        # Optional gift ledger must not break existing VPN expiry alerts.
        return []
    templates = {
        "ready_to_share": (
            "Подарочная карта оплачена",
            "Подписанный платёж подтверждён. Код доступен в разделе подарков.",
            "info", "/gifts.html",
        ),
        "pending_delivery": (
            "Подарок ожидает завершения выдачи",
            "Получатель может завершить выдачу в разделе подарков без повторной оплаты.",
            "info", "/gifts.html",
        ),
        "needs_support": (
            "Выдача подарка требует проверки",
            "Не покупай повторно. Создай обращение: повторная выдача VPN может быть небезопасна.",
            "warning", "/support-center.html",
        ),
    }
    result = []
    for order_id, state in rows:
        template = templates.get(state)
        if template is None:
            continue
        title, description, level, href = template
        result.append({
            "id": _event_id(owner, "gift_" + state, order_id),
            "type": "gift_" + state,
            "title": title,
            "description": description,
            "level": level,
            "href": href,
        })
    return result


def _account_alerts(owner: str, email: str, data: dict) -> list[dict]:
    return (_notifications(owner, data) + _gift_alerts(owner, email))[:20]


def _read_ids(owner: str, identifiers: list[str]) -> set[str]:
    if not identifiers:
        return set()
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT notification_id FROM vainah_account_feed_read
                WHERE owner_hash=%s AND notification_id = ANY(%s)
            """, (owner, identifiers))
            return {str(row[0]).strip() for row in cur.fetchall()}
    except psycopg.Error:
        raise HTTPException(503, "FEED_DATABASE_UNAVAILABLE") from None


def _mark(owner: str, identifier: str) -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                INSERT INTO vainah_account_feed_read (owner_hash, notification_id)
                VALUES (%s,%s) ON CONFLICT DO NOTHING
            """, (owner, identifier))
    except psycopg.Error:
        raise HTTPException(503, "FEED_DATABASE_UNAVAILABLE") from None


@router.get("")
async def inbox(request: Request) -> dict:
    email = _email(request)
    owner = _owner(email)
    data = await customer_overview(request)
    items = _account_alerts(owner, email, data)
    read = _read_ids(owner, [item["id"] for item in items])
    for item in items:
        item["read"] = item["id"] in read
    return {
        "items": items,
        "unread_count": sum(not item["read"] for item in items),
        "source": "verified_customer_account_h1_and_signed_gifts",
        "push_enabled": False,
        "message": "Только события, которые подтверждаются доступными данными подписки.",
    }


@router.post("/read")
async def mark_read(request: Request, body: MarkRead) -> dict:
    require_same_origin(request)
    email = _email(request)
    owner = _owner(email)
    data = await customer_overview(request)
    matches = _account_alerts(owner, email, data)
    if body.notification_id not in {item["id"] for item in matches}:
        raise HTTPException(404, "NOTIFICATION_NOT_FOUND")
    _mark(owner, body.notification_id)
    return {"read": True}
