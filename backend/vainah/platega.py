"""Platega hosted v2 payments. Credentials and provider bodies stay server-side.

Contract: https://docs.platega.io/ (checked 2026-11-18).
Callbacks use X-MerchantId/X-Secret, not RollyPay's HMAC format. Every event
is also reconciled against GET /transaction/{id} before it changes an order.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx

from .billing import get_plan, price_rub
from .production_contracts import LIVE_ORDER_RE, LiveContractError, LiveInvoice

API = "https://app.platega.io"
CALLBACK_STATUSES = frozenset({
    "CONFIRMED", "CANCELED", "CHARGEBACKED", "PARTIALLY_REFUNDED", "DISPUTED",
})


class PlategaError(LiveContractError):
    """Fixed error codes only; no remote error text, identifiers or secrets."""


def valid_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def configured() -> bool:
    secret = os.environ.get("PLATEGA_SECRET", "")
    return (
        valid_id(os.environ.get("PLATEGA_MERCHANT_ID"))
        and 16 <= len(secret) <= 1024
        and all(33 <= ord(char) <= 126 for char in secret)
    )


def headers() -> dict[str, str]:
    if not configured():
        raise PlategaError("PLATEGA_NOT_CONFIGURED")
    return {
        "X-MerchantId": os.environ["PLATEGA_MERCHANT_ID"],
        "X-Secret": os.environ["PLATEGA_SECRET"],
        "Accept": "application/json",
    }


def authentic_callback(merchant: str | None, secret: str | None) -> bool:
    if not configured() or not isinstance(merchant, str) or not isinstance(secret, str):
        return False
    # Bytes comparisons also reject arbitrary Unicode without leaking a 500.
    merchant_ok = secrets.compare_digest(
        merchant.encode(), os.environ["PLATEGA_MERCHANT_ID"].encode(),
    )
    secret_ok = secrets.compare_digest(secret.encode(), os.environ["PLATEGA_SECRET"].encode())
    return merchant_ok and secret_ok


def safe_pay_url(value: object) -> str:
    """Only the documented v2 payform; never follow a provider-supplied URL."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or "\\" in value):
        raise PlategaError("PLATEGA_PAYMENT_URL_INVALID")
    try:
        url = urlsplit(value)
        query = parse_qs(url.query, strict_parsing=True)
    except ValueError:
        raise PlategaError("PLATEGA_PAYMENT_URL_INVALID") from None
    if (url.scheme != "https" or url.netloc != "pay.platega.io"
            or url.path not in {"", "/"} or url.fragment
            or set(query) != {"id", "mh"}
            or any(len(v) != 1 or not valid_id(v[0]) for v in query.values())):
        raise PlategaError("PLATEGA_PAYMENT_URL_INVALID")
    return value


def amount(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PlategaError("PLATEGA_AMOUNT_INVALID")
    try:
        number = Decimal(str(value))
        if (not number.is_finite() or not 0 < number < 10**10
                or number != number.quantize(Decimal("0.01"))):
            raise PlategaError("PLATEGA_AMOUNT_INVALID")
        return number
    except (InvalidOperation, ValueError):
        raise PlategaError("PLATEGA_AMOUNT_INVALID") from None


def _json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    try:
        data = json.loads(raw, parse_float=Decimal, object_pairs_hook=unique)
        if not isinstance(data, dict):
            raise PlategaError("PLATEGA_RESPONSE_INVALID")
        return data
    except (ValueError, UnicodeError, RecursionError):
        raise PlategaError("PLATEGA_RESPONSE_INVALID") from None


async def _request(method: str, path: str, *, body: dict | None = None,
                   transport: httpx.AsyncBaseTransport | None = None) -> dict:
    try:
        async with (
            httpx.AsyncClient(
                timeout=10, follow_redirects=False, trust_env=False, transport=transport,
            ) as client,
            client.stream(method, API + path, headers=headers(), json=body) as response,
        ):
            if not 200 <= response.status_code < 300:
                raise PlategaError("PLATEGA_PROVIDER_UNAVAILABLE")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > 65536:
                    raise PlategaError("PLATEGA_RESPONSE_INVALID")
                raw.extend(chunk)
            return _json(bytes(raw))
    except httpx.HTTPError:
        # POST is never retried: the persisted reservation remains uncertain.
        raise PlategaError("PLATEGA_PROVIDER_UNAVAILABLE") from None


@dataclass(frozen=True)
class PaymentProof:
    order_id: str
    payment_id: str
    amount_rub: Decimal
    status: str


def callback(raw: bytes) -> PaymentProof:
    if len(raw) > 32768:
        raise PlategaError("PLATEGA_CALLBACK_INVALID")
    data = _json(raw)
    order_id, payment_id, status = data.get("payload"), data.get("id"), data.get("status")
    if (not isinstance(order_id, str) or not LIVE_ORDER_RE.fullmatch(order_id)
            or not valid_id(payment_id) or not isinstance(status, str)
            or status not in CALLBACK_STATUSES or data.get("currency") != "RUB"
            or type(data.get("paymentMethod")) is not int
            or "subscriptionId" in data or "paymentLinkId" in data):
        raise PlategaError("PLATEGA_CALLBACK_INVALID")
    return PaymentProof(order_id, payment_id, amount(data.get("amount")), status)


async def read_payment(payment_id: str, *, order_id: str, expected_amount: str,
                       transport: httpx.AsyncBaseTransport | None = None) -> PaymentProof:
    if not valid_id(payment_id):
        raise PlategaError("PLATEGA_PAYMENT_INVALID")
    data = await _request("GET", "/transaction/" + payment_id, transport=transport)
    details = data.get("paymentDetails")
    status = data.get("status")
    # Platega's documented response spells this field mechantId. Also accept
    # the corrected spelling, checking BOTH if both are present.
    merchants = [data[k] for k in ("merchantId", "mechantId") if k in data]
    if (data.get("id") != payment_id or data.get("payload") != order_id
            or not merchants or any(m != os.environ["PLATEGA_MERCHANT_ID"] for m in merchants)
            or not isinstance(details, dict) or details.get("currency") != "RUB"
            or amount(details.get("amount")) != amount(expected_amount)
            or not isinstance(status, str) or status not in CALLBACK_STATUSES | {"PENDING"}):
        raise PlategaError("PLATEGA_PAYMENT_MISMATCH")
    return PaymentProof(order_id, payment_id, amount(details["amount"]), status)


async def create_invoice(*, order_id: str, plan_id: str, verified_email: str,
                         owner_ref: str,
                         transport: httpx.AsyncBaseTransport | None = None) -> LiveInvoice:
    """Caller must durably reserve the immutable order before calling once."""
    plan = get_plan(plan_id)
    if (not plan or not LIVE_ORDER_RE.fullmatch(order_id)
            or not re.fullmatch(r"v1_[0-9a-f]{64}", owner_ref)):
        raise PlategaError("LIVE_ORDER_INVALID")
    origin = os.environ.get("PUBLIC_SITE_ORIGIN", "https://vainahvpn.onrender.com").rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.netloc != parsed.hostname):
        raise PlategaError("PLATEGA_RETURN_URL_INVALID")
    data = await _request("POST", "/v2/transaction/process", body={
        "paymentDetails": {"amount": plan["kopeks"] / 100, "currency": "RUB"},
        "description": "Vainah VPN — " + plan["title"],
        "return": origin + "/account.html#orders",
        "failedUrl": origin + "/checkout.html?plan=" + plan_id,
        "payload": order_id,
        "metadata": {"user_email": verified_email, "userId": owner_ref},
    }, transport=transport)
    payment_id = data.get("transactionId")
    if not valid_id(payment_id) or data.get("status") != "PENDING":
        raise PlategaError("PLATEGA_RESPONSE_INVALID")
    url = safe_pay_url(data.get("url"))
    # v2 creation omits the order/amount. Read them back before exposing a URL.
    proof = await read_payment(payment_id, order_id=order_id,
                               expected_amount=price_rub(plan), transport=transport)
    if proof.status != "PENDING":
        raise PlategaError("PLATEGA_PAYMENT_MISMATCH")
    return LiveInvoice(order_id, payment_id, price_rub(plan), url)
