"""Vainah shop: public pricing, authenticated operator-only RollyPay sandbox.

Production charges and VPN provisioning intentionally disabled until secure
accounts, persistent order ledger, approved merchant and H1Cloud activation exist.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

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


class ProviderError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class BillingSandbox:
    """Sandbox-only in-memory orders. Never use as a production sales ledger."""

    def __init__(self, mode: str = "mock", api_key: str = "",
                 transport: httpx.AsyncBaseTransport | None = None,
                 ledger_path: str | None = None):
        if mode not in {"mock", "provider"}:
            raise ValueError("INVALID_SHOP_MODE")
        self.mode = mode
        self.api_key = api_key
        self.transport = transport
        self.lock = RLock()
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
        """Read-only, authorized test of merchant API connectivity.

        Never returns provider response bodies, payment IDs, tokens or orders.
        A successful list read proves API access, NOT checkout availability.
        """
        if not self.api_key:
            raise ProviderError("PROVIDER_NOT_CONFIGURED")
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                         transport=self.transport) as client:
                response = await client.get(
                    API + "?environment=sandbox",
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
        return {"connected": True, "mode": "provider-sandbox",
                "request": "GET payments?environment=sandbox",
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

    async def create(self, plan_id: str) -> dict:
        self._ensure_loaded()
        plan = get_plan(plan_id)
        if not plan:
            raise HTTPException(422, "PLAN_UNKNOWN")
        order_id = "vainah_test_" + uuid4().hex
        amount = price_rub(plan)
        if self.mode == "mock":
            order = TestOrder(order_id, plan_id, amount,
                              "mock_" + uuid4().hex, "created", "mock")
        else:
            result = await self.provider_create(order_id, plan)
            if result.get("order_id") != order_id or str(result.get("amount")) != amount:
                raise ProviderError("PROVIDER_ORDER_OR_AMOUNT_MISMATCH")
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
                              status, "provider", pay_url)
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
        expected = self.read(order_id)
        if (result.get("test") is not True
                or result.get("environment") != "sandbox"):
            raise ProviderError("PROVIDER_SANDBOX_NOT_CONFIRMED")
        if (result.get("order_id") != order_id
                or result.get("payment_id") != self.orders[order_id].payment_id
                or str(result.get("amount")) != expected["amount_rub"]
                or result.get("payment_currency") != "RUB"):
            raise ProviderError("PROVIDER_ORDER_OR_AMOUNT_MISMATCH")
        status = result.get("status")
        if status not in STATUS:
            raise ProviderError("PROVIDER_STATUS_INVALID")
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
                    or str(data.get("amount")) != order.amount):
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
            self._set_status(order, status)
            return {"ok": True, "test_only": True, "status": order.status,
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
        # Preview ONLY. This method intentionally does not call H1Cloud.
        self.read(order_id)
        with self.lock:
            order = self.orders[order_id]
            plan = get_plan(order.plan_id)
            if plan is None:
                raise HTTPException(409, "PLAN_UNKNOWN")
            return {
                "order_id": order.order_id,
                "payment_status": order.status,
                "status": "demo_ready" if order.status == "paid" else "blocked",
                "plan": plan["id"],
                "duration_days": plan["days"],
                "device_limit": plan["devices"],
                "sandbox_only": True,
                "h1cloud_connected": False,
                "vpn_delivered": False,
                "subscription_url": None,
                "message": (
                    "Тестовая оплата подтверждена. Это только план выдачи VPN; "
                    "H1Cloud не подключён и реальный VPN не выдан."
                    if order.status == "paid" else
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
        }


class StartSandbox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str


router = APIRouter(prefix="/api/shop", tags=["Shop"])
sandbox = BillingSandbox(
    mode=os.environ.get("VAINAH_SHOP_SANDBOX_MODE", "mock"),
    api_key=os.environ.get("ROLLYPAY_API_KEY", ""),
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


@router.get("/plans")
def plans() -> dict:
    return {"currency": "RUB", "items": public_plans(),
            "prices_from": "2026-10-23"}


@router.get("/config")
def config() -> dict:
    return {"gateway": "rollypay", "checkout_ready": False,
            "sandbox_available": (
                len(os.environ.get("VAINAH_SANDBOX_TEST_TOKEN", "")) >= 24
                and os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") == "enabled"
            ), "customer_accounts_ready": False, "provisioning_ready": False,
            "message": "Оформление реальных заказов ещё закрыто: нет авторизованной выдачи VPN."}


@router.post("/checkout")
def public_checkout(_: StartSandbox) -> None:
    # Do not charge guests or pretend successful delivery.
    raise HTTPException(503, "LIVE_CHECKOUT_NOT_READY")


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
        raise HTTPException(502, exc.code) from None


@router.post("/sandbox/start")
async def start_sandbox(body: StartSandbox,
                        x_sandbox_token: str | None = Header(default=None)) -> dict:
    _require_operator(x_sandbox_token)
    if os.environ.get("VAINAH_SHOP_SANDBOX_ENABLED") != "enabled":
        raise HTTPException(503, "SANDBOX_DISABLED")
    if sandbox.mode == "provider" and os.environ.get(
        "VAINAH_SHOP_PROVIDER_TEST_ENABLED"
    ) != "enabled":
        raise HTTPException(503, "PROVIDER_SANDBOX_DISABLED")
    try:
        return await sandbox.create(body.plan)
    except ProviderError as exc:
        raise HTTPException(502, exc.code) from None


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
    try:
        await sandbox.refresh(order_id)
        return sandbox.activation_preview(order_id)
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
        return await sandbox.refresh(order_id)
    except ProviderError as exc:
        raise HTTPException(502, exc.code) from None


@router.post("/sandbox/{order_id}/simulate")
def sandbox_simulate(order_id: str,
                     x_sandbox_token: str | None = Header(default=None)) -> dict:
    _require_operator(x_sandbox_token)
    return sandbox.simulate(order_id)


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
        raise HTTPException(503, "PRODUCTION_PAYMENTS_DISABLED")
    try:
        import json
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "INVALID_JSON") from exc
    return sandbox.process_webhook(data)
