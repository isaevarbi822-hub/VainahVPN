"""Protected subscription portal. Paid orders must be verified before access.

No public endpoint creates receipts or can mark a payment paid.
Receipt rows are reserved for a future verified and idempotent
RollyPay -> H1Cloud fulfillment transaction.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlencode

import httpx
import psycopg
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .email_auth import current_email
from .email_delivery import (
    cancel_challenge,
    confirm_challenge,
    database_url,
    email_paid_subscription,
    email_service_ready,
    send_verification_code,
    start_challenge,
    verified_email,
)
from .h1_live_provision import LiveH1Error, _validate_subscription_url
from .h1_panel import (
    H1PanelError,
    panel_settings,
    panel_tls_verify,
    parse_client_status,
    read_h1_issued_client_status,
    read_h1_status,
)
from .production_contracts import LiveContractError, h1_provision_intent
from .telegram_auth import current_user, require_same_origin, require_user

router = APIRouter(prefix="/api/account", tags=["Customer account"])
ORDER_RE = re.compile(r"[0-9a-zA-Z_-]{12,100}")
PLAN_LABELS = {
    "30": ("1 месяц", 3),
    "60": ("2 месяца", 3),
    "90": ("3 месяца", 3),
    "180": ("6 месяцев", 3),
    "365": ("1 год", 3),
    "365-family": ("Семейный год", 6),
}




def telegram_id_for_verified_email(email: str) -> str | None:
    """Only a separately verified Telegram/email mapping can share purchases."""
    from .email_delivery import schema as email_schema

    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            email_schema(cur)
            cur.execute("""
                SELECT telegram_id FROM vainah_verified_customer_emails
                WHERE email = %s
            """, (email,))
            row = cur.fetchone()
            return str(row[0]) if row else None
    except psycopg.Error:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None


def portal_identity(
    request: Request, *, include_email: bool = True
) -> tuple[str | None, str | None, str]:
    """A verified mailbox by itself must not claim arbitrary Telegram IDs."""
    telegram = current_user(request)
    if telegram is not None:
        telegram_id = telegram["telegram_id"]
        verified = verified_email(telegram_id) if include_email else None
        return telegram_id, verified, "telegram"
    email = current_email(request)
    if email is not None:
        return telegram_id_for_verified_email(email), email, "email"
    raise HTTPException(401, "ACCOUNT_LOGIN_REQUIRED")


def _receipt_schema(cur) -> None:
    # Only a trusted future fulfillment service may INSERT/UPDATE receipts.
    # Do not accept test orders or client-originated flags as proof of payment.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_customer_deliveries (
            order_id VARCHAR(100) PRIMARY KEY,
            telegram_id VARCHAR(18) NOT NULL,
            plan_id VARCHAR(24) NOT NULL,
            payment_status TEXT NOT NULL CHECK (
                payment_status IN ('paid', 'refunded', 'chargeback')
            ),
            delivery_state TEXT NOT NULL CHECK (
                delivery_state IN ('delivered', 'revoked')
            ),
            emailed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_customer_deliveries_owner_idx
        ON vainah_customer_deliveries(telegram_id, created_at DESC)
    """)


def customer_receipts(telegram_id: str) -> list[dict]:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
                _receipt_schema(cur)
                cur.execute("""
                    SELECT order_id, plan_id, payment_status,
                           delivery_state, created_at, emailed_at
                    FROM vainah_customer_deliveries
                    WHERE telegram_id = %s
                    ORDER BY created_at DESC LIMIT 30
                """, (telegram_id,))
                rows = cur.fetchall()
    except psycopg.Error:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None
    return [{
        "order_id": row[0],
        "plan_id": row[1],
        "emailed": row[5] is not None,
        "title": PLAN_LABELS.get(row[1], ("VPN-подписка", 3))[0],
        "status": row[2] if row[3] == "delivered" else "revoked",
        "paid": row[2] == "paid",
        "delivered": row[3] == "delivered",
        "created_at": row[4].isoformat(),
    } for row in rows]


def active_receipt(telegram_id: str) -> dict | None:
    return next((item for item in customer_receipts(telegram_id)
                 if item["paid"] and item["delivered"]), None)


async def h1_customer_state(telegram_id: str) -> dict:
    try:
        result = await read_h1_status(telegram_id)
    except H1PanelError:
        return {"status": "unavailable",
                "message": "H1Cloud пока недоступен; покупка не подтверждается этим ответом."}
    if not result["panel_ready"]:
        return {"status": "not_configured",
                "message": "Адрес H1Cloud или токен не настроен."}
    if not result["found"]:
        return {"status": "not_found", "message": "Профиль H1Cloud не найден."}
    if not result["active"]:
        return {"status": "inactive", "message": "VPN-профиль сейчас неактивен."}
    return {"status": "active", "message": "Профиль H1Cloud активен.",
            "expires_at": result.get("expires_at")}


async def h1_email_customer_state(email: str) -> dict:
    """Read-only H1 profile check for a verified email session.

    This does not imply a paid order and never grants subscription access.
    Names are deterministically generated using the same signed live contract
    as future purchases, never taken from a caller-supplied client name.
    """
    try:
        intent = h1_provision_intent(
            email=email, plan_id="30",
            signing_key=os.environ.get("SESSION_SIGNING_KEY", ""),
        )
        result = await read_h1_issued_client_status(intent.client_name)
    except (H1PanelError, LiveContractError):
        return {
            "status": "unavailable",
            "message": "Проверка профиля H1Cloud по почте временно недоступна.",
        }
    if not result["panel_ready"]:
        return {"status": "not_configured",
                "message": "H1Cloud API ещё не настроен."}
    if not result["found"]:
        return {
            "status": "not_found",
            "message": "VPN-профиль для подтверждённой почты пока не создан.",
        }
    if not result["active"]:
        return {
            "status": "inactive",
            "message": "VPN-профиль найден, но сейчас неактивен.",
        }
    return {
        "status": "active",
        "message": "VPN-профиль активен; оплаченная выдача отдельно не подтверждена.",
        "expires_at": result.get("expires_at"),
    }


def live_paid_email_orders(email: str) -> list[dict]:
    """Customer-only order list without credentials, links or other owners."""
    from .live_checkout import live_account_ready, owner_ref_for_email
    from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger

    if not live_account_ready():
        return []
    try:
        rows = PostgresLiveOrderLedger(
            os.environ["DATABASE_URL"]
        ).owner_orders(owner_ref_for_email(email))
    except LiveLedgerError:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None
    return [
        {
            "order_id": row["order_id"], "plan_id": row["plan_id"],
            "title": PLAN_LABELS.get(
                row["plan_id"], ("VPN-подписка", 3)
            )[0],
            "status": (
                "delivered" if row["payment_state"] == "paid"
                and row["delivery_state"] == "delivered"
                else row["delivery_state"]
                if row["payment_state"] == "paid"
                else row["payment_state"]
            ),
            "paid": row["payment_state"] == "paid",
            "delivered": (
                row["payment_state"] == "paid"
                and row["delivery_state"] == "delivered"
            ),
            "created_at": row["created_at"],
        } for row in rows
    ]


def live_paid_email_access(email: str) -> str | None:
    from .live_checkout import live_account_ready, owner_ref_for_email
    from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger

    if not live_account_ready():
        return None
    try:
        return PostgresLiveOrderLedger(
            os.environ["DATABASE_URL"]
        ).owner_subscription_url(owner_ref_for_email(email))
    except LiveLedgerError:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None


async def own_subscription_url(telegram_id: str) -> str:
    # Restrict this to authenticated + owned, paid, delivered receipt.
    receipt = active_receipt(telegram_id)
    if receipt is None:
        raise HTTPException(404, "PAID_DELIVERY_NOT_FOUND")
    try:
        state = await read_h1_status(telegram_id)
        settings = panel_settings()
        if not state.get("active") or settings is None:
            raise HTTPException(409, "H1_SUBSCRIPTION_NOT_ACTIVE")
        name = settings.prefix + telegram_id
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False, trust_env=False,
            verify=panel_tls_verify(),
        ) as client:
            response = await client.get(
                settings.origin + "/api/info?" + urlencode({"name": name}),
                headers={"Authorization": "Bearer " + settings.token,
                         "Accept": "application/json"},
            )
        if response.status_code != 200 or len(response.content) > 100000:
            raise ValueError("bad response")
        record = response.json()
        if not isinstance(record, dict) or record.get("ok") is not True:
            raise ValueError("invalid panel")
        profile = record.get("client")
        if not isinstance(profile, dict) or profile.get("name") != name:
            raise ValueError("mismatched user")
        if not parse_client_status(profile)["active"]:
            raise HTTPException(409, "H1_SUBSCRIPTION_NOT_ACTIVE")
        value = _validate_subscription_url(
            profile.get("subscription_url") or profile.get("sub_url")
        )
        # The first receipt read predates two network awaits; a signed reversal
        # may have revoked it while the panel was responding.
        if active_receipt(telegram_id) is None:
            raise HTTPException(404, "PAID_DELIVERY_NOT_FOUND")
        return value
    except HTTPException:
        raise
    except (H1PanelError, httpx.RequestError, httpx.TimeoutException,
            ValueError, KeyError, TypeError, RecursionError, LiveH1Error):
        raise HTTPException(503, "H1_ACCESS_UNAVAILABLE") from None


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=5, max_length=254)


class EmailCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{6}$")


@router.get("/overview")
async def overview(request: Request) -> dict:
    telegram_id, email, method = portal_identity(request)
    if telegram_id is None:
        # Email-only identity: query only orders signed to this exact mailbox.
        # A Vainah H1 profile alone is never proof of a paid order.
        state = await h1_email_customer_state(email)
        orders = live_paid_email_orders(email)
        delivered = next((
            order for order in orders
            if order["paid"] and order["delivered"]
        ), None)
        subscription = None
        if delivered and state["status"] == "active":
            title, devices = PLAN_LABELS.get(
                delivered["plan_id"], ("VPN-подписка", 3)
            )
            subscription = {
                "status": "delivered", "paid": True,
                "order_id": delivered["order_id"],
                "plan_title": title, "device_limit": devices,
                "expires_at": state.get("expires_at"),
            }
        return {
            "authenticated": True,
            "auth_method": method,
            "email": {"verified": True, "address": email},
            "orders": orders,
            "subscription": subscription,
            "h1cloud": state,
        }
    orders = customer_receipts(telegram_id)
    last = next((o for o in orders if o["paid"] and o["delivered"]), None)
    state = await h1_customer_state(telegram_id)
    subscription = None
    if last and state["status"] == "active":
        title, limit = PLAN_LABELS.get(last["plan_id"], ("VPN-подписка", 3))
        subscription = {
            "status": "delivered", "paid": True,
            "order_id": last["order_id"],
            "plan_title": title, "device_limit": limit,
            "expires_at": state.get("expires_at"),
        }
    return {
        "authenticated": True,
        "auth_method": method,
        "email": {"verified": bool(email), "address": email},
        "orders": orders,
        "subscription": subscription,
        "h1cloud": state,
    }


@router.get("/test-subscriptions")
def test_subscriptions(request: Request) -> dict:
    """Show separately labeled sandbox deliveries to their original owner.

    A test delivery never becomes a live purchase or grants /account/access.
    The private URL remains behind the existing owner-checked VPN route.
    """
    from .billing import _require_verified_sandbox_owner, get_plan, sandbox
    from .sandbox_auto_h1 import SandboxAutoH1Error, auto_enabled, read_delivery

    owner = _require_verified_sandbox_owner(request)
    if not auto_enabled():
        return {"items": [], "sandbox_only": True}
    items = []
    for order in sandbox.owned_test_orders(owner, signed_paid_only=True):
        if order["mode"] != "provider" or order["status"] != "paid" or not (
            order.get("paid_webhook_received") and order["webhook_received"]
        ):
            continue
        plan = get_plan(order["plan"])
        if plan is None:
            continue
        try:
            delivery = read_delivery(order["order_id"], owner_ref=owner)
        except SandboxAutoH1Error:
            raise HTTPException(503, "SANDBOX_VPN_ACCESS_UNAVAILABLE") from None
        items.append({
            "order_id": order["order_id"],
            "title": plan["title"],
            "duration_days": plan["days"],
            "device_limit": plan["devices"],
            "delivery_state": delivery["status"],
            "vpn_delivered": delivery["vpn_delivered"],
            "sandbox_only": True,
            "test_payment": True,
        })
    return {"items": items, "sandbox_only": True}


@router.get("/access")
async def access(request: Request) -> dict:
    telegram_id, _, _ = portal_identity(request, include_email=False)
    # An email session can have a live purchase independently from Telegram.
    email = current_email(request)
    if email is not None:
        owned_link = live_paid_email_access(email)
        if owned_link is not None:
            return {"subscription_url": owned_link}
    if telegram_id is None:
        raise HTTPException(404, "PAID_DELIVERY_NOT_FOUND")
    return {"subscription_url": await own_subscription_url(telegram_id)}


@router.post("/email/request")
async def email_request(request: Request, body: EmailRequest) -> dict:
    require_same_origin(request)
    user = require_user(request)
    if not email_service_ready():
        raise HTTPException(503, "EMAIL_DELIVERY_NOT_CONFIGURED")
    try:
        email = validate_email(
            body.email, check_deliverability=False
        ).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(422, "EMAIL_INVALID") from None
    code = start_challenge(user["telegram_id"], email)
    try:
        await send_verification_code(email, code)
    except HTTPException:
        cancel_challenge(user["telegram_id"], code, email)
        raise
    return {"sent": True, "valid_minutes": 10}


@router.post("/email/confirm")
def email_confirm(request: Request, body: EmailCode) -> dict:
    require_same_origin(request)
    user = require_user(request)
    email = confirm_challenge(user["telegram_id"], body.code)
    return {"verified": True, "email": email}


async def notify_confirmed_subscription(telegram_id: str, order_id: str) -> bool:
    """Internal delivery dispatcher reserved for a verified payment reconciler.

    Never call on an unverified webhook or client input. This function refuses
    to send unless an owner-specific paid + delivered database receipt exists.
    """
    if not ORDER_RE.fullmatch(order_id) or order_id.startswith("vainah_test_"):
        raise ValueError("INVALID_ORDER_ID")
    receipt = active_receipt(telegram_id)
    if not receipt or receipt["order_id"] != order_id:
        return False
    if receipt.get("emailed") is True:
        return True
    url = await own_subscription_url(telegram_id)
    title, limit = PLAN_LABELS.get(receipt["plan_id"], ("VPN-подписка", 3))
    sent = await email_paid_subscription(
        telegram_id, order_id, url, plan_title=title, device_limit=limit,
    )
    if not sent:
        return False
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _receipt_schema(cur)
            cur.execute("""
                UPDATE vainah_customer_deliveries
                SET emailed_at = now()
                WHERE order_id = %s AND telegram_id = %s
                  AND payment_status = 'paid' AND delivery_state = 'delivered'
                  AND emailed_at IS NULL
            """, (order_id, telegram_id))
    except psycopg.Error:
        raise HTTPException(503, "ACCOUNT_DATABASE_UNAVAILABLE") from None
    return True
