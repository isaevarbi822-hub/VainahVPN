"""Server-side RollyPay API client and signed webhook verification.

No public checkout is exposed here. Production fulfillment must be wired to
an authenticated order and checked against an independent provider GET.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_BASE = "https://rollypay.io/api/v1"
SIG_RE = re.compile(r"^[a-fA-F0-9]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
EVENT_STATUS = {
    "payment.created": "created",
    "payment.paid": "paid",
    "payment.canceled": "canceled",
    "payment.expired": "expired",
    "payment.chargeback": "chargeback",
    "payment.refunded": "refunded",
    "refund_request.completed": "refunded",
}


class RollyPayError(Exception):
    """Sanitized integration error (never includes credentials)."""


def verify_signature(raw_body: bytes, timestamp: str | None, signature: str | None,
                     secret: str | None, *, now: int | None = None,
                     max_age_seconds: int = 300) -> bool:
    """Verify X-Signature = hex(HMAC_SHA256(secret, timestamp + '.' + raw bytes))."""
    if not secret or not timestamp or not signature or not SIG_RE.fullmatch(signature):
        return False
    if not timestamp.isascii() or not timestamp.isdecimal():
        return False
    try:
        issued_at = int(timestamp)
    except ValueError:
        return False
    if abs((int(time.time()) if now is None else now) - issued_at) > max_age_seconds:
        return False
    expected = hmac.new(secret.encode("utf-8"),
                        timestamp.encode("ascii") + b"." + raw_body,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def parse_payment_event(raw_body: bytes) -> dict:
    """Validate only payment/refund events, requiring an explicit sandbox flag."""
    if len(raw_body) > 65_536:
        raise ValueError("Oversized webhook")
    try:
        event = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON") from exc
    if not isinstance(event, dict):
        raise ValueError("Invalid webhook structure")
    kind = event.get("event_type")
    if kind not in EVENT_STATUS or event.get("status") != EVENT_STATUS[kind]:
        raise ValueError("Unsupported or inconsistent payment event")
    if not all(isinstance(event.get(k), str) and ID_RE.fullmatch(event[k])
               for k in ("payment_id", "order_id")):
        raise ValueError("Invalid payment or order identifier")
    if type(event.get("test")) is not bool:
        raise ValueError("Missing explicit sandbox flag")
    if event.get("currency") not in ("RUB", "EUR"):
        raise ValueError("Unexpected currency")
    try:
        amount = Decimal(event["amount"])
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid amount") from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Invalid payment amount")
    return {
        "payment_id": event["payment_id"],
        "order_id": event["order_id"],
        "event_type": kind,
        "status": event["status"],
        "amount": amount,
        "currency": event["currency"],
        "is_test": event["test"],
        "payload_sha256": hashlib.sha256(raw_body).hexdigest(),
    }


def confirmed_paid_for_order(event: dict, remote: dict, order: dict) -> bool:
    """Only a real paid transaction for an existing fixed-price order qualifies.

    Caller must also guarantee one-time fulfillment within an order transaction.
    """
    try:
        return (
            event["status"] == remote["status"] == "paid"
            and event["is_test"] is False
            and event["payment_id"] == remote["payment_id"] == order["payment_id"]
            and event["order_id"] == remote["order_id"] == order["id"]
            and event["currency"] == remote["payment_currency"] == order["currency"]
            and Decimal(event["amount"]) == Decimal(remote["amount"]) == Decimal(order["amount"])
        )
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False


class RollyPayClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ROLLYPAY_API_KEY", "")
        if not self.api_key:
            raise RollyPayError("ROLLYPAY_API_KEY not configured")

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        headers = {
            "X-API-Key": self.api_key,
            "X-Nonce": str(uuid.uuid4()),
            "Accept": "application/json",
        }
        body = None
        if data is not None:
            body = json.dumps(data, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(API_BASE + path, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=8) as response:
                data_bytes = response.read(65_537)
                if len(data_bytes) > 65_536:
                    raise RollyPayError("Oversized provider response")
                result = json.loads(data_bytes)
                if not isinstance(result, dict):
                    raise RollyPayError("Unexpected provider response")
                return result
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RollyPayError("RollyPay API unavailable or rejected request") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RollyPayError("Invalid provider JSON") from exc

    def api_healthy(self) -> bool:
        """Make a read-only authenticated GET; never expose account balance."""
        payload = self._request("GET", "/balance")
        return "available_usdt" in payload

    def get_payment(self, payment_id: str) -> dict:
        if not ID_RE.fullmatch(payment_id):
            raise ValueError("Invalid payment ID")
        return self._request("GET", "/payments/" + quote(payment_id, safe=""))

    def create_sandbox_payment(self, *, order_id: str, amount: Decimal,
                               description: str) -> dict:
        """Never creates a live charge. Amount must come from a server-side catalog."""
        if not ID_RE.fullmatch(order_id) or amount <= 0 or not amount.is_finite():
            raise ValueError("Invalid order")
        return self._request("POST", "/payments", {
            "order_id": order_id,
            "amount": f"{amount:.2f}",
            "payment_currency": "RUB",
            "description": description[:200],
            "test": True,
        })
