"""Vainah shop: public pricing, authenticated operator-only RollyPay sandbox.

Production charges and VPN provisioning intentionally disabled until secure
accounts, persistent order ledger, approved merchant and H1Cloud activation exist.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .email_delivery import send_sandbox_receipt
from .postgres_ledger import LedgerUnavailable, PostgresSandboxLedger
from .sandbox_ledger import SandboxLedger

API = "https://rollypay.io/api/v1/payments"
PAY_URL_RE = re.compile(r"/pay/[A-Za-z0-9_-]{6,255}/?")
# Payment IDs are opaque. Restrict to safe URL-path bytes rather than pay_-only.
PAYMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,127}")
ORDER_RE = re.compile(r"vainah_test_[0-9a-f]{32}")
STATUS = frozenset(("created", "processing", "paid", "canceled", "expired",
                    "refunded", "chargeback"))
EVENT_TO_STATUS = {
    "payment.created": "created", "payment.paid": "paid",
    "payment.canceled": "canceled", "payment.expired": "expired",
    "payment.refunded": "refunded", "payment.chargeback": "chargeback",
    "refund_request.completed": "refunded",
}
CATALOG = (
    {"id": "30", "title": "1 месяц", "days": 30, "kopeks": 9900, "devices": 3},
    {"id": "60", "title": "2 месяца", "days": 60, "kopeks": 16000, "devices": 3},
    {"id": "90", "title": "3 месяца", "days": 90, "kopeks": 21900, "devices": 3},
    {"id": "180", "title": "6 месяцев", "days": 180, "kopeks": 33900, "devices": 3},
    {"id": "365", "title": "1 год", "days": 365, "kopeks": 70000, "devices": 3},
    {"id": "365-family", "title": "Семейный год", "days": 365,
     "kopeks": 100000, "devices": 6},
)


def get_plan(plan_id: str) -> dict | None:
    return next((p for p in CATALOG if p["id"] == plan_id), None)


def price_rub(plan: dict) -> str:
    return f'{plan["kopeks"] / 100:.2f}'


def public_plans() -> list[dict]:
    return [{**p, "priceRub": price_rub(p)} for p in CATALOG]


def safe_pay_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("PROVIDER_PAYMENT_LINK_INVALID")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or url.netloc != "pay.rollypay.io"
                or url.query or url.fragment or not PAY_URL_RE.fullmatch(url.path)):
            raise ValueError("PROVIDER_PAYMENT_LINK_INVALID")
        return value
    except (TypeError, ValueError) as exc:
        raise ValueError("PROVIDER_PAYMENT_LINK_INVALID") from exc


def verify_signature(raw: bytes, timestamp: str | None, signature: str | None,
                     secret: str, *, now: int | None = None) -> bool:
    if (not secret or not isinstance(timestamp, str)
            or not re.fullmatch(r"\d{10}", timestamp)
            or not isinstance(signature, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", signature)):
        return False
    now = int(time.time()) if now is None else now
    if abs(now - int(timestamp)) > 300:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


@dataclass
class TestOrder:
    order_id: str
    plan_id: str
    amount: str
    payment_id: str
    status: str
    mode: str
    pay_url: str | None = None
    webhook_received: bool = False
    owner_ref: str | None = None
    receipt_emailed: bool = False
    receipt_recipient: str | None = None


def _receipt_fernet() -> Fernet:
    """Authenticated encryption for receipt destination, not for VPN keys."""
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "RECEIPT_ENCRYPTION_NOT_CONFIGURED")
    key = hmac.new(
        secret.encode(), b"vainah-test-receipt-email-v1", hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _seal_receipt_recipient(email: str) -> str:
    return _receipt_fernet().encrypt(email.encode("utf-8")).decode("ascii")


def _unseal_receipt_recipient(ciphertext: str) -> str:
    try:
        email = _receipt_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise HTTPException(503, "RECEIPT_RECIPIENT_UNAVAILABLE") from None
    if not (5 <= len(email) <= 254 and email.count("@") == 1):
        raise HTTPException(503, "RECEIPT_RECIPIENT_UNAVAILABLE")
    return email


class ProviderError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _matches_exact_rub_amount(value: object, expected: str) -> bool:
    """Compare RUB by value, not JSON formatting, without float arithmetic.

    RollyPay may serialize 99 RUB as 99, 99.0 or "99.00".
    Reject booleans, negatives, exponential values, fractional kopeks
    and unbounded inputs; NEVER accept a different monetary amount.
    """
    if type(value) not in (str, int, float):
        return False
    text = str(value)
    # Some JSON serializers retain trailing zeroes after two kopek digits.
    # Exact numeric equivalence is required: under/overpayment never passes.
    if not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,12})?", text):
        return False
    return Decimal(text) == Decimal(expected)


def _matches_rub_currency(data: dict) -> bool:
    """Accept documented payment_currency or webhook-style currency.

    If both aliases occur, both must agree. Never silently default RUB.
    """
    specified = [
        data[name] for name in ("payment_currency", "currency")
        if name in data
    ]
    return bool(specified) and all(value == "RUB" for value in specified)


def _safe_provider_amount(value: object) -> str | None:
    """Only decimal digits may leave operator-only diagnostics; no raw JSON."""
    if type(value) not in (str, int, float):
        return None
    result = str(value)
    if not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,12})?", result):
        return None
    return result


def _payment_status_comparison(result: dict, order: TestOrder) -> dict:
    """Classify ALL status fields without reflecting secrets or provider text."""
    def compare_identifier(key: str, expected: str) -> str:
        if key not in result:
            return "missing"
        return "match" if result[key] == expected else "different"

    mode = (
        "contradictory" if (
            ("test" in result and result["test"] is not True)
            or ("environment" in result and result["environment"] != "sandbox")
        ) else "confirmed_at_creation"
    )
    amount_value = _safe_provider_amount(result.get("amount"))
    amount = (
        "missing" if "amount" not in result else
        "invalid_format" if amount_value is None else
        "match" if _matches_exact_rub_amount(amount_value, order.amount)
        else "different"
    )
    currencies = [
        result[k] for k in ("payment_currency", "currency")
        if k in result
    ]
    currency = (
        "missing" if not currencies else
        "match" if all(v == "RUB" for v in currencies)
        else "different"
    )
    fields = {
        "sandbox_mode": mode,
        "order_id": compare_identifier("order_id", order.order_id),
        "payment_id": compare_identifier("payment_id", order.payment_id),
        "amount": amount,
        "currency": currency,
        "payment_status": (
            "recognized" if result.get("status") in STATUS
            else "unknown_or_missing"
        ),
    }
    checks = (
        ("sandbox_mode", "PROVIDER_SANDBOX_NOT_CONFIRMED",
         "confirmed_at_creation"),
        ("order_id", "PROVIDER_ORDER_MISMATCH", "match"),
        ("payment_id", "PROVIDER_PAYMENT_MISMATCH", "match"),
        ("amount", "PROVIDER_AMOUNT_MISMATCH", "match"),
        ("currency", "PROVIDER_CURRENCY_MISMATCH", "match"),
        ("payment_status", "PROVIDER_STATUS_INVALID", "recognized"),
    )
    reason = next(
        (code for field, code, required in checks if fields[field] != required),
        "OK",
    )
    return {
        "reason": reason,
        "fields": fields,
        "expected_amount_rub": order.amount,
        "observed_amount_rub": amount_value,
        "provider_status": (
            result["status"] if fields["payment_status"] == "recognized"
            else "unknown"
        ),
        "signed_paid_webhook_received": (
            order.status == "paid" and order.webhook_received is True
        ),
        "new_payment_created": False,
        "sandbox_only": True,
    }


class BillingSandbox:
    """Sandbox-only in-memory orders. Never use as a production sales ledger."""

    def __init__(self, mode: str = "mock", api_key: str = "",
                 transport: httpx.AsyncBaseTransport | None = None,
                 ledger_path: str | None = None,
                 terminal_id: str | None = None):
        if mode not in {"mock", "provider"}:
            raise ValueError("INVALID_SHOP_MODE")
        self.mode = mode
        self.api_key = api_key
        self.transport = transport
        self.terminal_id = terminal_id
        self.lock = RLock()
        self.receipt_lock = asyncio.Lock()
        self.orders: dict[str, TestOrder] = {}
        self.ledger = None
        if ledger_path:
            if ledger_path.startswith(("postgresql://", "postgres://")):
                self.ledger = PostgresSandboxLedger(ledger_path)
            else:
                self.ledger = SandboxLedger(ledger_path)
        # Do not connect to PostgreSQL during app import: Render must still
        # start if the database is temporarily unavailable.
        self._ledger_loaded = False

    def _ensure_loaded(self) -> None:
        with self.lock:
            if self._ledger_loaded:
                return
            if self.ledger is not None:
                try:
                    records = self.ledger.load()
                except LedgerUnavailable:
                    raise HTTPException(503, "SANDBOX_LEDGER_UNAVAILABLE") from None
                for record in records:
                    if record["mode"] != self.mode:
                        continue
                    if not get_plan(record["plan_id"]):
                        continue
                    if not ORDER_RE.fullmatch(record["order_id"]):
                        continue
                    if record["status"] not in STATUS:
                        continue
                    record["webhook_received"] = bool(record.get("webhook_received", False))
                    record["owner_ref"] = record.get("owner_ref")
                    record["receipt_emailed"] = bool(record.get("receipt_emailed", False))
                    record["receipt_recipient"] = record.get("receipt_recipient")
                    order = TestOrder(**record, pay_url=None)
                    self.orders[order.order_id] = order
            self._ledger_loaded = True

    def _save(self, order: TestOrder) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.save(order)
        except LedgerUnavailable:
            # Do not include the connection string or provider error text.
            raise HTTPException(503, "SANDBOX_LEDGER_UNAVAILABLE") from None

    def _set_status(self, order: TestOrder, next_status: str) -> None:
        old_status = order.status
        order.status = next_status
        try:
            self._save(order)
        except HTTPException:
            order.status = old_status
            raise

    async def provider_diagnostics(self) -> dict:
        """Verify the merchant API key via a documented, read-only balance GET.

        Never returns the balance, merchant response, customer records, payment
        IDs, or tokens. This confirms authentication, NOT payment fulfillment.
        """
        if not self.api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED")
        params = None
        if self.terminal_id:
            # Invalid configuration must fail closed without leaking its value.
            try:
                params = {"terminal_id": str(UUID(self.terminal_id.strip()))}
            except (ValueError, AttributeError) as exc:
                raise ProviderError("PROVIDER_TERMINAL_ID_INVALID") from exc
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                         transport=self.transport) as client:
                response = await client.get(
                    "https://rollypay.io/api/v1/balance",
                    params=params,
                    headers={"X-API-Key": self.api_key,
                             "X-Nonce": str(uuid4()),
                             "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise ProviderError("PROVIDER_NETWORK") from exc
        if not 200 <= response.status_code <= 299:
            if response.status_code == 400 and len(response.content) <= 2048:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                # Only exact, public provider error categories are exposed.
                # Never print or store arbitrary upstream text or identifiers.
                if isinstance(body, dict) and isinstance(body.get("error"), str):
                    reason = body["error"].strip().casefold()
                    if reason in {"terminal not found", "terminal_id not found"}:
                        raise ProviderError("PROVIDER_TERMINAL_NOT_FOUND")
                    if reason in {"terminal_id is required", "terminal_id required",
                                  "missing terminal_id", "terminal_id is missing"}:
                        raise ProviderError("PROVIDER_TERMINAL_ID_REQUIRED")
            raise ProviderError(f"PROVIDER_HTTP_{response.status_code}")
        if len(response.content) > 65536:
            raise ProviderError("PROVIDER_RESPONSE_INVALID")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("PROVIDER_RESPONSE_INVALID") from exc
        if not isinstance(payload, dict) or not all(
            field in payload for field in ("available_usdt", "hold_usdt")
        ):
            raise ProviderError("PROVIDER_RESPONSE_INVALID")
        return {"connected": True, "mode": "provider-read-only",
                "request": "GET /api/v1/balance",
                "new_payment_created": False, "live_checkout_enabled": False}

    async def provider_create(self, order_id: str, plan: dict) -> dict:
        if not self.api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED")
        # No user-controlled amount; always sandbox, never test:false.
        data = {
            "amount": price_rub(plan),
            "payment_currency": "RUB",
            "order_id": order_id,
            "description": f'Vainah VPN TEST ONLY — {plan["title"]}',
            "test": True,
        }
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                         transport=self.transport) as client:
                response = await client.post(
                    API,
                    json=data,
                    headers={"X-API-Key": self.api_key,
                             "X-Nonce": str(uuid4()),
                             "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise ProviderError("PROVIDER_NETWORK") from exc
        if response.status_code < 200 or response.status_code > 299:
            # Do not reflect provider error body (may contain credentials).
            raise ProviderError(f"PROVIDER_HTTP_{response.status_code}")
        if len(response.content) > 65536:
            raise ProviderError("PROVIDER_RESPONSE_INVALID")
        try:
            result = response.json()
        except ValueError as exc:
            raise ProviderError("PROVIDER_RESPONSE_INVALID") from exc
        if not isinstance(result, dict):
            raise ProviderError("PROVIDER_RESPONSE_INVALID")
        return result

    async def create(self, plan_id: str, *, owner_ref: str | None = None,
                     receipt_email: str | None = None) -> dict:
        self._ensure_loaded()
        plan = get_plan(plan_id)
        if not plan:
            raise HTTPException(422, "PLAN_UNKNOWN")
        order_id = "vainah_test_" + uuid4().hex
        amount = price_rub(plan)
        encrypted_recipient = (
            _seal_receipt_recipient(receipt_email)
            if owner_ref and receipt_email else None
        )
        if self.mode == "mock":
            order = TestOrder(order_id, plan_id, amount,
                              "mock_" + uuid4().hex, "created", "mock",
                              owner_ref=owner_ref,
                              receipt_recipient=encrypted_recipient)
        else:
            result = await self.provider_create(order_id, plan)
            if result.get("order_id") != order_id:
                raise ProviderError("PROVIDER_ORDER_MISMATCH")
            if not _matches_exact_rub_amount(result.get("amount"), amount):
                raise ProviderError("PROVIDER_AMOUNT_MISMATCH")
            if (result.get("payment_currency") != "RUB"
                    or result.get("test") is not True
                    or result.get("environment") != "sandbox"):
                raise ProviderError("PROVIDER_SANDBOX_NOT_CONFIRMED")
            payment_id = result.get("payment_id")
            status = result.get("status")
            if not isinstance(payment_id, str) or not payment_id:
                raise ProviderError("PROVIDER_PAYMENT_ID_MISSING")
            if not PAYMENT_ID_RE.fullmatch(payment_id):
                raise ProviderError("PROVIDER_PAYMENT_ID_FORMAT")
            if status not in {"created", "processing"}:
                raise ProviderError("PROVIDER_PAYMENT_STATUS_INVALID")
            try:
                pay_url = safe_pay_url(result.get("pay_url"))
            except ValueError as exc:
                raise ProviderError("PROVIDER_PAYMENT_LINK_INVALID") from exc
            order = TestOrder(order_id, plan_id, amount, payment_id,
                              status, "provider", pay_url, owner_ref=owner_ref,
                              receipt_recipient=encrypted_recipient)
        with self.lock:
            self._save(order)
            self.orders[order_id] = order
        return self.serialize(order)

    async def provider_read(self, payment_id: str) -> dict:
        """Fetch status from RollyPay; reject any response without sandbox markers."""
        if not self.api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED")
        if not PAYMENT_ID_RE.fullmatch(payment_id):
            raise ProviderError("PROVIDER_PAYMENT_INVALID")
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                         transport=self.transport) as client:
                response = await client.get(
                    API + "/" + payment_id,
                    headers={"X-API-Key": self.api_key,
                             "X-Nonce": str(uuid4()),
                             "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise ProviderError("PROVIDER_NETWORK") from exc
        if not 200 <= response.status_code <= 299:
            raise ProviderError(f"PROVIDER_HTTP_{response.status_code}")
        if len(response.content) > 65536:
            raise ProviderError("PROVIDER_RESPONSE_INVALID")
        try:
            result = response.json()
        except ValueError as exc:
            raise ProviderError("PROVIDER_RESPONSE_INVALID") from exc
        if not isinstance(result, dict):
            raise ProviderError("PROVIDER_RESPONSE_INVALID")
        return result

    async def refresh(self, order_id: str) -> dict:
        existing = self.read(order_id)
        if existing["mode"] != "provider":
            return existing
        result = await self.provider_read(self.orders[order_id].payment_id)
        # GET /api/v1/payments/{id} may omit the sandbox markers even
        # though POST created this exact test payment with test=true and
        # environment=sandbox. We trust only that validated, locally
        # persisted provider test order, with matching immutable payment ID,
        # order ID, currency and amount. Explicit contradictory markers always
        # fail closed; GET alone never substitutes for a signed paid webhook.
        with self.lock:
            known = self.orders[order_id]
            proof = _payment_status_comparison(result, known)
        if proof["reason"] != "OK":
            raise ProviderError(proof["reason"])
        status = result["status"]
        with self.lock:
            order = self.orders[order_id]
            if order.status in {"refunded", "chargeback"} and status not in {
                "refunded", "chargeback"
            }:
                raise ProviderError("PROVIDER_STATUS_REGRESSION")
            if order.status == "paid" and status in {
                "created", "processing", "canceled", "expired"
            }:
                raise ProviderError("PROVIDER_STATUS_REGRESSION")
            self._set_status(order, status)
            return self.serialize(order)

    async def inspect_provider_status(self, order_id: str) -> dict:
        """Read-only operator diagnostic; only sanitized comparisons leave API."""
        snapshot = self.read(order_id)
        if snapshot["mode"] != "provider":
            raise HTTPException(409, "TEST_PROVIDER_ORDER_REQUIRED")
        result = await self.provider_read(self.orders[order_id].payment_id)
        with self.lock:
            known = self.orders[order_id]
            return _payment_status_comparison(result, known)

    def read(self, order_id: str) -> dict:
        if not ORDER_RE.fullmatch(order_id):
            raise HTTPException(404, "TEST_ORDER_NOT_FOUND")
        self._ensure_loaded()
        with self.lock:
            order = self.orders.get(order_id)
            if not order:
                raise HTTPException(404, "TEST_ORDER_NOT_FOUND")
            return self.serialize(order)

    def simulate(self, order_id: str) -> dict:
        if not ORDER_RE.fullmatch(order_id):
            raise HTTPException(404, "TEST_ORDER_NOT_FOUND")
        self._ensure_loaded()
        with self.lock:
            order = self.orders.get(order_id)
            if not order:
                raise HTTPException(404, "TEST_ORDER_NOT_FOUND")
            if order.mode != "mock":
                raise HTTPException(403, "PROVIDER_SIMULATION_FORBIDDEN")
            if order.status == "created":
                self._set_status(order, "paid")
            return self.serialize(order)

    def process_webhook(self, data: object) -> dict:
        if not isinstance(data, dict):
            raise HTTPException(400, "INVALID_WEBHOOK")
        kind = data.get("event_type")
        status = EVENT_TO_STATUS.get(kind)
        if not status or status != data.get("status"):
            raise HTTPException(400, "UNSUPPORTED_PAYMENT_EVENT")
        order_id = data.get("order_id")
        if not isinstance(order_id, str) or not ORDER_RE.fullmatch(order_id):
            raise HTTPException(400, "UNKNOWN_ORDER")
        self._ensure_loaded()
        with self.lock:
            order = self.orders.get(order_id)
            if not order or order.mode != "provider":
                raise HTTPException(404, "UNKNOWN_ORDER")
            if (data.get("test") is not True
                    or data.get("payment_id") != order.payment_id
                    or data.get("currency") != "RUB"
                    or not _matches_exact_rub_amount(
                        data.get("amount"), order.amount,
                    )):
                raise HTTPException(400, "PAYMENT_MISMATCH")
            # Same state is idempotent. Later refund/chargeback overrides paid.
            if order.status in {"refunded", "chargeback"} and status not in {
                "refunded", "chargeback"
            }:
                raise HTTPException(409, "PAYMENT_STATE_REGRESSION")
            if order.status == "paid" and status in {
                "created", "processing", "expired", "canceled"
            }:
                raise HTTPException(409, "PAYMENT_STATE_REGRESSION")
            previous_webhook = order.webhook_received
            order.webhook_received = True
            try:
                self._set_status(order, status)
            except HTTPException:
                order.webhook_received = previous_webhook
                raise
            # Keep the provider callback contract stable. Operator-only
            # fulfillment readiness is exposed via activation-preview instead.
            return {"ok": True, "test_only": True, "status": order.status,
                    "vpn_delivered": False}

    def owned_test_orders(self, owner_ref: str) -> list[dict]:
        """Only account-bound operator sandbox orders; never return provider URLs."""
        self._ensure_loaded()
        with self.lock:
            return [
                {**self.serialize(order), "pay_url": None}
                for order in reversed(list(self.orders.values()))
                if order.owner_ref is not None
                and secrets.compare_digest(order.owner_ref, owner_ref)
            ][:20]

    def require_order_owner(self, order_id: str, owner_ref: str) -> None:
        """Do not allow old anonymous orders to be claimed by knowing their ID."""
        if not ORDER_RE.fullmatch(order_id):
            raise HTTPException(404, "TEST_ORDER_NOT_FOUND")
        self._ensure_loaded()
        with self.lock:
            order = self.orders.get(order_id)
            if not order or order.owner_ref is None or not secrets.compare_digest(
                order.owner_ref, owner_ref
            ):
                raise HTTPException(404, "TEST_ORDER_NOT_FOUND")

    async def send_auto_test_receipt(
        self, order_id: str, *, vpn_issued: bool = False,
    ) -> dict:
        """Send a TEST receipt automatically after the signed paid callback.

        Concurrent workers claim one recipient via the persistent ledger.
        Resend receives the same idempotency key on safe retries.
        """
        self._ensure_loaded()
        async with self.receipt_lock:
            with self.lock:
                order = self.orders.get(order_id)
                if not order or order.mode != "provider" or (
                    order.status != "paid" or not order.webhook_received
                    or not order.owner_ref or not order.receipt_recipient
                    or order.receipt_emailed
                ):
                    return {"sent": False, "already_sent": bool(
                        order and order.receipt_emailed
                    ), "test_only": True, "vpn_delivered": False}
                plan = get_plan(order.plan_id)
                if plan is None:
                    raise HTTPException(409, "PLAN_UNKNOWN")
                encrypted = order.receipt_recipient
                title, days, devices, amount = (
                    plan["title"], plan["days"], plan["devices"], order.amount
                )
            if self.ledger is not None:
                try:
                    encrypted = self.ledger.claim_receipt(order_id)
                except (LedgerUnavailable, OSError):
                    raise HTTPException(503, "SANDBOX_LEDGER_UNAVAILABLE") from None
                if encrypted is None:
                    return {"sent": False, "already_sent": False,
                            "test_only": True, "vpn_delivered": False}
            try:
                recipient = _unseal_receipt_recipient(encrypted)
                await send_sandbox_receipt(
                    recipient, order_id=order_id, plan_title=title,
                    amount_rub=amount, duration_days=days, devices=devices,
                    **({"vpn_issued": True} if vpn_issued is True else {}),
                )
                if self.ledger is not None:
                    try:
                        self.ledger.finish_receipt(order_id)
                    except (LedgerUnavailable, OSError):
                        raise HTTPException(503, "SANDBOX_LEDGER_UNAVAILABLE") from None
                with self.lock:
                    order.receipt_emailed = True
                    if self.ledger is None:
                        self._save(order)
                return {"sent": True, "already_sent": False,
                        "test_only": True, "vpn_delivered": False}
            except (HTTPException, ValueError):
                if self.ledger is not None:
                    try:
                        self.ledger.release_receipt(order_id)
                    except (LedgerUnavailable, OSError):
                        pass
                raise

    async def send_owned_test_receipt(
        self, order_id: str, owner_ref: str, recipient: str
    ) -> dict:
        """Operator fallback for old bound orders; new orders auto-send."""
        self.require_order_owner(order_id, owner_ref)
        with self.lock:
            order = self.orders[order_id]
            if order.mode != "provider" or order.status != "paid" or not order.webhook_received:
                raise HTTPException(409, "SIGNED_TEST_PAYMENT_REQUIRED")
            encrypted_recipient_exists = order.receipt_recipient is not None
        if encrypted_recipient_exists:
            # Never let the user change the saved verified destination.
            return await self.send_auto_test_receipt(order_id)
        async with self.receipt_lock:
            self.require_order_owner(order_id, owner_ref)
            with self.lock:
                order = self.orders[order_id]
                if order.mode != "provider" or not order.webhook_received or order.status != "paid":
                    raise HTTPException(409, "SIGNED_TEST_PAYMENT_REQUIRED")
                if order.receipt_emailed:
                    return {"sent": False, "already_sent": True, "test_only": True,
                            "vpn_delivered": False}
                plan = get_plan(order.plan_id)
                if plan is None:
                    raise HTTPException(409, "PLAN_UNKNOWN")
                title, days, devices, amount = (
                    plan["title"], plan["days"], plan["devices"], order.amount
                )
            await send_sandbox_receipt(
                recipient, order_id=order_id, plan_title=title,
                amount_rub=amount, duration_days=days, devices=devices,
            )
            with self.lock:
                order.receipt_emailed = True
                try:
                    self._save(order)
                except HTTPException:
                    order.receipt_emailed = False
                    raise
            return {"sent": True, "already_sent": False, "test_only": True,
                    "vpn_delivered": False}

    def list_test_orders(self) -> list[dict]:
        self._ensure_loaded()
        with self.lock:
            # Provider IDs and pay URLs must never be exposed in listing.
            return [
                {**self.serialize(order), "pay_url": None}
                for order in reversed(list(self.orders.values()))
            ][:25]

    def activation_preview(self, order_id: str) -> dict:
        """Deterministic fulfillment plan, not an H1Cloud write or live receipt.

        A provider test must be paid AND confirmed by a signed webhook before
        it passes the fulfillment gate. Polling alone never grants this gate.
        No customer identity is associated with sandbox test orders.
        """
        self.read(order_id)
        with self.lock:
            order = self.orders[order_id]
            plan = get_plan(order.plan_id)
            if plan is None:
                raise HTTPException(409, "PLAN_UNKNOWN")
            paid = order.status == "paid"
            signed = order.mode == "provider" and order.webhook_received
            gate_open = paid and signed
            if order.mode == "mock":
                # Mock payments are useful for previewing tariff details but
                # can never enter the real-provider fulfillment gate.
                gate_reason = "MOCK_PAYMENT_NOT_PROVIDER_VERIFIED"
            elif not paid:
                gate_reason = "PAYMENT_NOT_PAID"
            elif not signed:
                gate_reason = "SIGNED_WEBHOOK_REQUIRED"
            else:
                gate_reason = None
            # One immutable identity for the proposed action per sandbox order:
            # duplicate webhook deliveries and process restarts give the same ID.
            # This is a preview key, NOT a production fulfillment receipt.
            preview_key = (
                "sandbox_" + hashlib.sha256(
                    ("vpn-preview:" + order.order_id + ":" + order.plan_id).encode()
                ).hexdigest()[:32]
                if gate_open else None
            )
            fulfillment = {
                "status": "ready_for_review" if gate_open else "blocked",
                "reason": gate_reason,
                "preview_idempotency_key": preview_key,
                "operation": "create_or_extend" if gate_open else None,
                "plan_id": plan["id"],
                "duration_days": plan["days"],
                "device_limit": plan["devices"],
                "signed_webhook_received": signed,
                "operator_review_required": True,
                "customer_identity_bound": bool(order.owner_ref),
                "account_binding_required": not bool(order.owner_ref),
                "h1cloud_write_performed": False,
                "auto_provisioning_enabled": False,
                "subscription_url": None,
            }
            return {
                "order_id": order.order_id,
                "payment_status": order.status,
                "status": "demo_ready" if paid else "blocked",
                "plan": plan["id"],
                "duration_days": plan["days"],
                "device_limit": plan["devices"],
                "sandbox_only": True,
                "h1cloud_connected": False,
                "vpn_delivered": False,
                "subscription_url": None,
                "fulfillment": fulfillment,
                "message": (
                    "Подписанный тестовый webhook подтверждён. План выдачи "
                    "подготовлен к проверке; H1Cloud не изменён и VPN не выдан."
                    if gate_open else
                    "Это демонстрация тарифа. Автовыдача заблокирована: "
                    "требуется подтверждённый тестовый платёж и привязка аккаунта."
                    if paid else
                    "Пока нет подтверждения тестовой оплаты; выдача заблокирована."
                ),
            }

    @staticmethod
    def serialize(order: TestOrder) -> dict:
        return {
            "order_id": order.order_id, "plan": order.plan_id,
            "amount_rub": order.amount, "status": order.status,
            "mode": order.mode, "test_only": True, "real_charge": False,
            "vpn_delivered": False, "pay_url": order.pay_url,
            "webhook_received": order.webhook_received,
            "owner_bound": bool(order.owner_ref),
            "receipt_emailed": order.receipt_emailed,
        }


class StartSandbox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str


router = APIRouter(prefix="/api/shop", tags=["Shop"])
sandbox = BillingSandbox(
    mode=os.environ.get("VAINAH_SHOP_SANDBOX_MODE", "mock"),
    api_key=os.environ.get("ROLLYPAY_API_KEY", ""),
    terminal_id=os.environ.get("ROLLYPAY_TERMINAL_ID", ""),
    ledger_path=(
        os.environ.get("VAINAH_SHOP_SANDBOX_LEDGER_FILE")
        or (
            os.environ.get("DATABASE_URL")
            if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") == "enabled"
            else None
        )
    ),
)


def _require_operator(token: str | None) -> None:
    expected = os.environ.get("VAINAH_SANDBOX_TEST_TOKEN", "")
    if (len(expected) < 24 or not token
            or not secrets.compare_digest(expected, token)):
        raise HTTPException(401, "SANDBOX_OPERATOR_TOKEN_REQUIRED")


def _verified_sandbox_owner(request: Request) -> str | None:
    """Opaque, stable ownership proof from an authenticated server session.

    The test order never trusts a user-supplied email or Telegram ID.
    Older unbound test orders are deliberately not auto-claimed.
    """
    from .email_auth import current_email
    from .telegram_auth import current_user

    email = current_email(request)
    telegram = current_user(request) if email is None else None
    if email:
        principal = "email:" + email.lower()
    elif telegram:
        principal = "telegram:" + telegram["telegram_id"]
    else:
        return None
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        return None
    digest = hmac.new(
        secret.encode(), ("sandbox-owner-v1:" + principal).encode(),
        hashlib.sha256,
    ).hexdigest()
    return "v1_" + digest


def _require_verified_sandbox_owner(request: Request) -> str:
    owner = _verified_sandbox_owner(request)
    if owner is None:
        raise HTTPException(401, "VERIFIED_ACCOUNT_REQUIRED")
    return owner


@router.get("/plans")
def plans() -> dict:
    return {"currency": "RUB", "items": public_plans(),
            "prices_from": "2026-10-23"}


@router.get("/config")
def config() -> dict:
    from .live_checkout import live_ready

    approved = live_ready()
    return {"gateway": "rollypay", "checkout_ready": approved,
            "sandbox_available": (
                len(os.environ.get("VAINAH_SANDBOX_TEST_TOKEN", "")) >= 24
                and os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") == "enabled"
            ), "customer_accounts_ready": approved,
            "provisioning_ready": approved,
            "message": (
                "Подтверждённый email и оплата на сайте RollyPay."
                if approved else
                "Оформление реальных заказов закрыто до подтверждения "
                "полного цикла платежа и выдачи VPN."
            )}


@router.get("/operator/production-readiness")
async def operator_production_readiness(
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    """Operator-only live transport check; never charges or creates VPN users."""
    _require_operator(x_sandbox_token)
    from .h1_panel import inspect_h1_panel
    from .production_contracts import production_readiness

    report = production_readiness()
    if report["checks"]["h1cloud_read_configured"]:
        try:
            h1 = await asyncio.wait_for(inspect_h1_panel(), timeout=10)
        except (TimeoutError, OSError):
            h1 = {"ok": False}
        report["checks"]["h1cloud_tls_reachable_and_authorized"] = (
            h1.get("ok") is True and h1.get("authentication") == "accepted"
        )
    if report["checks"]["h1cloud_tls_reachable_and_authorized"]:
        report["message"] = (
            "H1Cloud accepted a read-only request over verified HTTPS. "
            "Real checkout and automatic VPN delivery are still disabled until "
            "the write contract, verified fulfillment and merchant readiness "
            "have been independently approved."
        )
    return report


@router.post("/checkout")
async def public_checkout(
    body: StartSandbox, request: Request,
    idempotency_key: str | None = Header(default=None),
) -> dict:
    from .live_checkout import start_live_checkout

    return await start_live_checkout(
        request=request, plan_id=body.plan, idempotency_key=idempotency_key,
    )


@router.get("/sandbox/webhook-readiness")
def sandbox_webhook_readiness(
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    """Operator-only configuration checks; no secrets or customer data.

    This checks local readiness only, not whether a callback was delivered.
    Production billing and H1Cloud provisioning remain unavailable.
    """
    _require_operator(x_sandbox_token)
    from .sandbox_auto_h1 import auto_enabled

    checks = {
        "sandbox_h1_auto_enabled": auto_enabled(),
        "sandbox_enabled": os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") == "enabled",
        "provider_test_enabled": (
            sandbox.mode == "provider"
            and os.environ.get("VAINAH_SHOP_PROVIDER_TEST_ENABLED") == "enabled"
        ),
        "signing_secret_configured": len(
            os.environ.get("ROLLYPAY_SIGNING_SECRET", "")
        ) >= 16,
        "persistent_ledger_configured": sandbox.ledger is not None,
    }
    sandbox._ensure_loaded()
    with sandbox.lock:
        verified_count = sum(
            1 for order in sandbox.orders.values()
            if order.mode == "provider" and order.webhook_received
        )
    return {
        "checks": checks,
        "configured": all(checks.values()),
        "verified_test_webhook_order_count": verified_count,
        "webhook_path": "/api/shop/webhooks/rollypay",
        "callback_delivery_verified": False,
        "production_checkout_enabled": False,
        "h1cloud_auto_provisioning_enabled": auto_enabled(),
        "sandbox_auto_h1_test_only": True,
    }


@router.get("/sandbox/diagnostics")
async def sandbox_diagnostics(
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    _require_operator(x_sandbox_token)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    if sandbox.mode != "provider" or os.environ.get(
        "VAINAH_SHOP_PROVIDER_TEST_ENABLED"
    ) != "enabled":
        return {"connected": False, "mode": "mock",
                "reason": "PROVIDER_MODE_NOT_ENABLED",
                "new_payment_created": False}
    try:
        return await sandbox.provider_diagnostics()
    except ProviderError as exc:
        # A failed balance GET does not mean webhook delivery or checkout
        # creation failed. Surface an allowlisted reason for operator UI,
        # without disclosing any merchant secrets or upstream response.
        return {
            "connected": False,
            "mode": "provider-read-only",
            "reason": exc.code,
            "check": "GET /api/v1/balance",
            "new_payment_created": False,
            "live_checkout_enabled": False,
        }


@router.post("/sandbox/start")
async def start_sandbox(body: StartSandbox,
                        request: Request,
                        x_sandbox_token: str | None = Header(default=None)) -> dict:
    _require_operator(x_sandbox_token)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    if sandbox.mode == "provider" and os.environ.get(
        "VAINAH_SHOP_PROVIDER_TEST_ENABLED"
    ) != "enabled":
        raise HTTPException(503, "PROVIDER_SANDBOX_DISABLED")
    try:
        from .email_auth import current_email

        owner = _verified_sandbox_owner(request)
        email = current_email(request)
        return await sandbox.create(
            body.plan, owner_ref=owner,
            receipt_email=email if owner and email else None,
        )
    except ProviderError as exc:
        raise HTTPException(502, exc.code) from None


@router.get("/my-test-orders")
def my_test_orders(request: Request) -> dict:
    """Account-visible only for sandbox orders bound at creation time."""
    owner = _require_verified_sandbox_owner(request)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    return {"items": sandbox.owned_test_orders(owner), "sandbox_only": True}


@router.get("/my-test-orders/{order_id}/vpn-access")
def my_test_vpn_access(order_id: str, request: Request) -> dict:
    """Reveal test VPN URL only to its original verified email owner."""
    from .sandbox_auto_h1 import (
        SandboxAutoH1Error,
        auto_enabled,
        read_delivery,
    )

    owner = _require_verified_sandbox_owner(request)
    sandbox.require_order_owner(order_id, owner)
    if not auto_enabled():
        raise HTTPException(404, "SANDBOX_VPN_NOT_ISSUED")
    try:
        state = read_delivery(order_id, owner_ref=owner, with_access=True)
    except SandboxAutoH1Error:
        raise HTTPException(503, "SANDBOX_VPN_ACCESS_UNAVAILABLE") from None
    if not state.get("vpn_delivered") or not state.get("subscription_url"):
        raise HTTPException(404, "SANDBOX_VPN_NOT_ISSUED")
    return {
        "subscription_url": state["subscription_url"],
        "sandbox_only": True,
        "test_payment": True,
    }


@router.post("/my-test-orders/{order_id}/email-receipt")
async def email_test_receipt(order_id: str, request: Request) -> dict:
    """User-triggered email TEST receipt. No real payment or H1Cloud activation."""
    from .email_auth import current_email
    from .telegram_auth import require_same_origin

    require_same_origin(request)
    email = current_email(request)
    if email is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    owner = _require_verified_sandbox_owner(request)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    return await sandbox.send_owned_test_receipt(order_id, owner, email)


@router.get("/my-test-orders/{order_id}/activation-preview")
def my_test_order_preview(order_id: str, request: Request) -> dict:
    owner = _require_verified_sandbox_owner(request)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    sandbox.require_order_owner(order_id, owner)
    return sandbox.activation_preview(order_id)


@router.get("/sandbox/orders")
def sandbox_orders(
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    _require_operator(x_sandbox_token)
    return {"items": sandbox.list_test_orders(), "sandbox_only": True}


@router.get("/sandbox/{order_id}/activation-preview")
async def sandbox_activation_preview(
    order_id: str,
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    _require_operator(x_sandbox_token)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    if sandbox.mode == "provider" and os.environ.get(
        "VAINAH_SHOP_PROVIDER_TEST_ENABLED"
    ) != "enabled":
        raise HTTPException(503, "PROVIDER_SANDBOX_DISABLED")
    # The operator-only preview uses the signed webhook state already stored
    # in the ledger. Do not require a second provider GET: that call may fail
    # transiently (HTTP 502) even after a valid webhook was recorded.
    preview = sandbox.activation_preview(order_id)
    from .sandbox_auto_h1 import SandboxAutoH1Error, auto_enabled, read_delivery

    if not auto_enabled() or preview["payment_status"] != "paid" or not (
        preview["fulfillment"]["signed_webhook_received"]
    ):
        return preview
    try:
        delivery = read_delivery(order_id)
    except SandboxAutoH1Error:
        raise HTTPException(503, "SANDBOX_AUTO_H1_DATABASE_UNAVAILABLE") from None
    preview["fulfillment"]["auto_provisioning_enabled"] = True
    if delivery["vpn_delivered"]:
        preview["status"] = "issued"
        preview["vpn_delivered"] = True
        preview["h1cloud_connected"] = True
        preview["fulfillment"]["status"] = "delivered"
        preview["fulfillment"]["h1cloud_write_performed"] = True
        preview["fulfillment"]["operator_review_required"] = False
        preview["message"] = (
            "Тестовый VPN создан в H1Cloud автоматически после подписанного "
            "webhook; ссылка доступна только владельцу email-аккаунта."
        )
    elif delivery["status"] in {"claimed", "needs_review"}:
        preview["fulfillment"]["status"] = "needs_review"
        preview["message"] = (
            "Автовыдача уже пыталась обработать заказ. "
            "Повторный H1Cloud POST заблокирован; проверь панель."
        )
    return preview


@router.get("/sandbox/{order_id}/payment-diagnostics")
async def sandbox_payment_diagnostics(
    order_id: str,
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    """Read-only mismatch report. Requires operator token, never exposes keys.

    Inspecting a status does not issue a VPN, charge money or update the ledger.
    Only the original test order's stored payment ID can be queried.
    """
    _require_operator(x_sandbox_token)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    if sandbox.mode != "provider" or os.environ.get(
        "VAINAH_SHOP_PROVIDER_TEST_ENABLED"
    ) != "enabled":
        raise HTTPException(503, "PROVIDER_SANDBOX_DISABLED")
    try:
        return await sandbox.inspect_provider_status(order_id)
    except ProviderError as exc:
        raise HTTPException(502, exc.code) from None


@router.get("/sandbox/{order_id}")
async def sandbox_status(order_id: str,
                         x_sandbox_token: str | None = Header(default=None)) -> dict:
    _require_operator(x_sandbox_token)
    if sandbox.mode == "provider" and os.environ.get(
        "VAINAH_SHOP_PROVIDER_TEST_ENABLED"
    ) != "enabled":
        raise HTTPException(503, "PROVIDER_SANDBOX_DISABLED")
    try:
        result = await sandbox.refresh(order_id)
        result["provider_status_fresh"] = True
    except ProviderError as exc:
        # A provider HTTP 5xx/timeout must not erase a previously validated
        # signed webhook. Only display a clearly labeled, cached paid state.
        # Never use this fallback for a new or merely polled paid order.
        retryable = {
            "PROVIDER_TIMEOUT", "PROVIDER_NETWORK",
            "PROVIDER_HTTP_429", "PROVIDER_HTTP_500",
            "PROVIDER_HTTP_502", "PROVIDER_HTTP_503",
            "PROVIDER_HTTP_504",
        }
        if exc.code not in retryable:
            raise HTTPException(502, exc.code) from None
        snapshot = sandbox.read(order_id)
        if snapshot["status"] != "paid" or snapshot["webhook_received"] is not True:
            raise HTTPException(502, exc.code) from None
        result = {
            **snapshot,
            "provider_status_fresh": False,
            "source": "last_signed_webhook",
            "provider_read_error": exc.code,
        }
    from .sandbox_auto_h1 import SandboxAutoH1Error, auto_enabled, read_delivery

    if auto_enabled() and result["status"] == "paid" and result["webhook_received"]:
        try:
            status = read_delivery(order_id)
        except SandboxAutoH1Error:
            raise HTTPException(503, "SANDBOX_AUTO_H1_DATABASE_UNAVAILABLE") from None
        result["vpn_delivered"] = status["vpn_delivered"]
        result["delivery_state"] = status["status"]
    return result


@router.post("/sandbox/{order_id}/simulate")
def sandbox_simulate(order_id: str,
                     x_sandbox_token: str | None = Header(default=None)) -> dict:
    _require_operator(x_sandbox_token)
    return sandbox.simulate(order_id)


# Diagnostic categories only. Never log callback body, payment identifiers,
# IPs, credentials, email, signatures, or provider error text.
_WEBHOOK_SAFE_REASONS = frozenset({
    "INVALID_WEBHOOK", "UNSUPPORTED_PAYMENT_EVENT", "UNKNOWN_ORDER",
    "PAYMENT_MISMATCH", "INVALID_JSON", "LIVE_PAYMENT_EVENT_UNSUPPORTED",
    "LIVE_ORDER_INVALID", "LIVE_PAYMENT_MISMATCH",
    "LIVE_ORDER_UNKNOWN", "LIVE_PAYMENT_INVALID_STATE",
    "LIVE_WEBHOOK_JSON_INVALID",
})


def _log_webhook_rejection(exc: HTTPException, *, mode: str) -> None:
    if exc.status_code != 400:
        return
    reason = (
        exc.detail if isinstance(exc.detail, str)
        and exc.detail in _WEBHOOK_SAFE_REASONS
        else "UNCLASSIFIED"
    )
    logging.getLogger("uvicorn.error").warning(
        "rollypay_webhook_rejected mode=%s code=%s", mode, reason
    )


@router.post("/webhooks/rollypay")
async def webhook(request: Request, x_signature: str | None = Header(default=None),
                  x_timestamp: str | None = Header(default=None),
                  x_test_mode: str | None = Header(default=None)) -> dict:
    secret = os.environ.get("ROLLYPAY_SIGNING_SECRET", "")
    if len(secret) < 16:
        raise HTTPException(503, "WEBHOOK_NOT_CONFIGURED")
    if request.headers.get("content-length", "0").isdigit() and int(
        request.headers.get("content-length", "0")
    ) > 32768:
        raise HTTPException(413, "BODY_TOO_LARGE")
    raw = await request.body()
    if len(raw) > 32768:
        raise HTTPException(413, "BODY_TOO_LARGE")
    if not verify_signature(raw, x_timestamp, x_signature, secret):
        raise HTTPException(403, "INVALID_SIGNATURE")
    if x_test_mode != "true":
        from .live_checkout import handle_live_paid_webhook

        try:
            return await handle_live_paid_webhook(
                raw=raw, timestamp=x_timestamp, signature=x_signature,
            )
        except HTTPException as exc:
            _log_webhook_rejection(exc, mode="live")
            raise
    try:
        import json
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "INVALID_JSON") from exc
    try:
        result = sandbox.process_webhook(data)
    except HTTPException as exc:
        _log_webhook_rejection(exc, mode="sandbox")
        raise
    from .sandbox_auto_h1 import (
        SandboxAutoH1Error,
        auto_enabled,
        auto_issue_paid_sandbox,
        mark_refunded,
    )

    if auto_enabled() and result["status"] == "paid" and (
        data.get("event_type") == "payment.paid"
    ):
        try:
            delivery = await auto_issue_paid_sandbox(data["order_id"])
        except SandboxAutoH1Error:
            # The webhook is saved; a safe retry cannot bypass the once-only
            # claim. 503 only for storage errors, never retry an H1 write.
            raise HTTPException(
                503, "SANDBOX_AUTO_H1_STORAGE_UNAVAILABLE"
            ) from None
        result = {
            **result, "vpn_delivered": delivery["vpn_delivered"],
            "delivery_state": delivery["status"],
        }
    elif auto_enabled() and result["status"] in {"refunded", "chargeback"}:
        try:
            mark_refunded(data["order_id"])
        except SandboxAutoH1Error:
            raise HTTPException(
                503, "SANDBOX_AUTO_H1_STORAGE_UNAVAILABLE"
            ) from None
    if result["status"] == "paid" and data.get("event_type") == "payment.paid":
        # Only the original account-bound sandbox order has an encrypted email.
        # A failed test receipt may cause provider retries; delivery stays
        # idempotent via the durable claim and never reissues a VPN.
        try:
            await sandbox.send_auto_test_receipt(
                data["order_id"],
                **({"vpn_issued": True} if result.get("vpn_delivered") is True else {}),
            )
        except (HTTPException, ValueError):
            raise HTTPException(503, "TEST_RECEIPT_DELIVERY_RETRY") from None
    return result
