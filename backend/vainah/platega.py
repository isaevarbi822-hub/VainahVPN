"""Platega hosted checkout, authenticated callbacks and provider status verification.

RollyPay stays independent. A Platega callback alone is never proof of payment:
the server rechecks the payment with Platega before a durable paid claim.
No charge, refund, or H1Cloud request is performed by the readiness endpoint.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from .billing import StartSandbox, get_plan, price_rub
from .live_checkout import (
    IDEMPOTENCY_RE,
    _ledger,
    current_email,
    live_ready,
    owner_ref_for_email,
)
from .live_fulfillment import FulfillmentError, fulfill_paid_order_once
from .live_ledger import LiveLedgerError
from .live_receipt import LiveReceiptError, send_paid_access_receipt_once
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/shop", tags=["Shop"])
API_URL = "https://app.platega.io"
RETURN_URL = "https://vainahvpn-python-preview.onrender.com/account.html"
TRANSACTION_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
STATUSES = {
    "CONFIRMED", "CANCELED", "CHARGEBACKED",
    "PARTIALLY_REFUNDED", "DISPUTED",
}
PAYMENT_METHODS = {"2", "3", "11", "12", "13", "14"}


def merchant_id() -> str:
    return os.environ.get("PLATEGA_MERCHANT_ID", "").strip().lower()


def api_secret() -> str:
    # Prefer one explicit secret; accept the two common env names.
    return (
        os.environ.get("PLATEGA_SECRET", "")
        or os.environ.get("PLATEGA_API_KEY", "")
        or os.environ.get("PLATEGA_X_SECRET", "")
    )


def ready() -> bool:
    try:
        UUID(merchant_id())
        method = os.environ.get("PLATEGA_PAYMENT_METHOD", "2")
        return (
            os.environ.get("PLATEGA_ENABLED") == "enabled"
            and len(api_secret()) >= 16
            and method in PAYMENT_METHODS
            and live_ready()
        )
    except (ValueError, AttributeError):
        return False


def safe_pay_url(value: str) -> str:
    """Only permit Platega's hosted payment origin; it uses query tokens."""
    if not isinstance(value, str) or not 10 < len(value) <= 2048:
        raise ValueError("PLATEGA_REDIRECT_INVALID")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or url.hostname != "pay.platega.io"
                or url.port not in (None, 443) or url.username is not None
                or url.password is not None or url.fragment
                or any(c in value for c in "\\
	")
                or ".." in url.path):
            raise ValueError("PLATEGA_REDIRECT_INVALID")
    except ValueError:
        raise ValueError("PLATEGA_REDIRECT_INVALID") from None
    return value


def valid_transaction_id(value: object) -> bool:
    if not isinstance(value, str) or not TRANSACTION_ID_RE.fullmatch(value):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def exact_rub_amount(value: object, expected: object) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        a = Decimal(str(value))
        b = Decimal(str(expected))
        return a.is_finite() and b.is_finite() and a > 0 and a == b
    except (InvalidOperation, TypeError, ValueError):
        return False


def _headers() -> dict[str, str]:
    return {
        "X-MerchantId": merchant_id(),
        "X-Secret": api_secret(),
        "Content-Type": "application/json",
    }


async def _new_invoice(*, order_id: str, amount_rub: int,
                       email: str, owner_ref: str) -> tuple[str, str]:
    payload = {
        "paymentMethod": int(os.environ.get("PLATEGA_PAYMENT_METHOD", "2")),
        "paymentDetails": {"amount": amount_rub, "currency": "RUB"},
        "description": "Подписка Vainah VPN, заказ " + order_id,
        "return": RETURN_URL,
        "failedUrl": RETURN_URL,
        "payload": order_id,
        "metadata": {"user_email": email, "userId": owner_ref},
    }
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False,
        ) as client:
            response = await client.post(
                API_URL + "/transaction/process", json=payload,
                headers=_headers(),
            )
        if response.status_code != 200:
            raise ValueError("PLATEGA_CREATE_UNAVAILABLE")
        result = response.json()
        if (not isinstance(result, dict)
                or result.get("status") != "PENDING"
                or (result.get("merchantId") is not None
                    and result["merchantId"].lower() != merchant_id())):
            raise ValueError("PLATEGA_CREATE_INVALID")
        transaction_id = result.get("transactionId")
        if not valid_transaction_id(transaction_id):
            raise ValueError("PLATEGA_TRANSACTION_INVALID")
        return transaction_id, safe_pay_url(result.get("redirect"))
    except (httpx.RequestError, ValueError, KeyError, TypeError):
        # A timeout after the provider accepted an invoice is ambiguous.
        # The reserved intent MUST stay locked, not be retried automatically.
        raise HTTPException(503, "PLATEGA_INVOICE_RECONCILIATION") from None


async def _provider_transaction(payment_id: str) -> dict:
    if not valid_transaction_id(payment_id):
        raise HTTPException(400, "PLATEGA_TRANSACTION_INVALID")
    try:
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False, trust_env=False,
        ) as client:
            response = await client.get(
                API_URL + "/transaction/" + payment_id, headers=_headers(),
            )
        if response.status_code != 200:
            raise ValueError("PLATEGA_STATUS_UNAVAILABLE")
        result = response.json()
        if not isinstance(result, dict) or result.get("id") != payment_id:
            raise ValueError("PLATEGA_STATUS_INVALID")
        return result
    except (httpx.RequestError, ValueError, TypeError):
        raise HTTPException(
            503, "PLATEGA_VERIFICATION_UNAVAILABLE",
            headers={"Retry-After": "30"},
        ) from None


@router.post("/checkout/platega")
async def start_checkout(
    body: StartSandbox, request: Request,
    idempotency_key: str | None = Header(default=None),
) -> dict:
    if not ready():
        raise HTTPException(503, "PLATEGA_NOT_READY")
    if body.plan == "pilot-1d":
        raise HTTPException(422, "LIVE_PILOT_PLAN_RESTRICTED")
    require_same_origin(request)
    email = current_email(request)
    if email is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    if (not isinstance(idempotency_key, str)
            or not IDEMPOTENCY_RE.fullmatch(idempotency_key)):
        raise HTTPException(422, "LIVE_IDEMPOTENCY_REQUIRED")
    plan = get_plan(body.plan)
    if plan is None:
        raise HTTPException(422, "LIVE_PLAN_INVALID")
    ledger = _ledger()
    try:
        order_id, earlier_url = ledger.reserve_checkout(
            owner_ref=owner_ref_for_email(email),
            verified_email=email, plan_id=body.plan,
            idempotency_key=idempotency_key, gateway="platega",
        )
        if earlier_url:
            return {
                "order_id": order_id, "pay_url": safe_pay_url(earlier_url),
                "status": "created", "gateway": "platega",
            }
        payment_id, pay_url = await _new_invoice(
            order_id=order_id, amount_rub=price_rub(plan),
            email=email, owner_ref=owner_ref_for_email(email),
        )
        if not ledger.attach_hosted_invoice(
            order_id=order_id, payment_id=payment_id, pay_url=pay_url,
            gateway="platega",
        ):
            raise LiveLedgerError("LIVE_CHECKOUT_RECONCILIATION_REQUIRED")
    except LiveLedgerError as exc:
        if str(exc) in {
            "LIVE_IDEMPOTENCY_CONFLICT",
            "LIVE_CHECKOUT_RECONCILIATION_REQUIRED",
        }:
            raise HTTPException(409, str(exc)) from None
        raise HTTPException(503, "PLATEGA_CHECKOUT_UNAVAILABLE") from None
    return {
        "order_id": order_id, "pay_url": pay_url,
        "status": "created", "gateway": "platega",
    }


@router.post("/webhooks/platega")
async def webhook(
    request: Request,
    x_merchantid: str | None = Header(default=None),
    x_secret: str | None = Header(default=None),
) -> dict:
    # Keep processing existing invoices even if new Platega sales are paused.
    if not live_ready() or len(api_secret()) < 16:
        raise HTTPException(503, "PLATEGA_NOT_CONFIGURED")
    if (not isinstance(x_merchantid, str)
            or not secrets.compare_digest(x_merchantid.strip().lower(), merchant_id())
            or not isinstance(x_secret, str)
            or not secrets.compare_digest(x_secret, api_secret())):
        raise HTTPException(403, "PLATEGA_CALLBACK_UNAUTHORIZED")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 16384:
            raise HTTPException(413, "BODY_TOO_LARGE")
        body.extend(chunk)
    try:
        event = json.loads(bytes(body))
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "PLATEGA_CALLBACK_INVALID") from None
    if not isinstance(event, dict):
        raise HTTPException(400, "PLATEGA_CALLBACK_INVALID")
    payment_id = event.get("id")
    order_id = event.get("payload")
    status = event.get("status")
    from .production_contracts import LIVE_ORDER_RE

    if (not valid_transaction_id(payment_id)
            or not isinstance(order_id, str)
            or not LIVE_ORDER_RE.fullmatch(order_id)
            or status not in STATUSES
            or event.get("currency") != "RUB"
            or not exact_rub_amount(event.get("amount"), event.get("amount"))):
        raise HTTPException(400, "PLATEGA_CALLBACK_INVALID")

    # The callback headers authenticate the sender, but we also independently
    # confirm exact transaction ID, order payload and amount with Platega.
    verified = await _provider_transaction(payment_id)
    details = verified.get("paymentDetails")
    if (not isinstance(details, dict)
            or details.get("currency") != "RUB"
            or verified.get("payload") != order_id
            or not exact_rub_amount(details.get("amount"), event["amount"])):
        raise HTTPException(400, "PLATEGA_PAYMENT_MISMATCH")
    if verified.get("status") != status:
        if status == "CONFIRMED":
            raise HTTPException(503, "PLATEGA_PAYMENT_NOT_FINAL",
                                headers={"Retry-After": "30"})
        return {"ok": True, "stale_event_ignored": True}

    ledger = _ledger()
    try:
        outcome = ledger.record_platega_verified(
            order_id=order_id, payment_id=payment_id,
            amount=details["amount"], currency=details["currency"],
            status=status,
        )
    except LiveLedgerError as exc:
        if str(exc) in {"LIVE_ORDER_UNKNOWN", "LIVE_PAYMENT_MISMATCH"}:
            raise HTTPException(400, str(exc)) from None
        raise HTTPException(503, "LIVE_LEDGER_UNAVAILABLE") from None

    if status != "CONFIRMED" or not outcome["paid"]:
        return {
            "ok": True, "status": status,
            "vpn_delivered": False,
            "manual_h1_revocation_required": outcome["manual_review"],
        }
    try:
        result = await fulfill_paid_order_once(
            ledger=ledger, order_id=order_id,
            verified_merchant_approved=True, write_contract_approved=True,
        )
    except FulfillmentError as exc:
        if str(exc) in {"LIVE_LEDGER_UNAVAILABLE", "LIVE_DELIVERY_PENDING"}:
            raise HTTPException(503, str(exc), headers={"Retry-After": "30"}) from None
        return {"ok": True, "status": "paid", "vpn_delivered": False,
                "delivery_state": "manual_review"}
    if result["vpn_delivered"]:
        try:
            await send_paid_access_receipt_once(ledger=ledger, order_id=order_id)
        except LiveReceiptError:
            raise HTTPException(
                503, "LIVE_ACCESS_EMAIL_RETRY",
                headers={"Retry-After": "125"},
            ) from None
    return {
        "ok": True, "status": "paid",
        "vpn_delivered": result["vpn_delivered"],
        "delivery_state": result["status"],
    }
