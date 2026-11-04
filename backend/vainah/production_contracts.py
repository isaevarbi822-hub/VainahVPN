"""Strict contracts for future LIVE RollyPay -> H1Cloud fulfillment.

No FastAPI live checkout route calls this module. The merchant must first
verify its legal account and H1Cloud write contract; a durable live order
ledger with single-writer fulfillment must be deployed before accepting money.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import httpx

from .billing import PAYMENT_ID_RE, get_plan, price_rub, safe_pay_url, verify_signature

LIVE_ORDER_RE = re.compile(r"vainah_live_[0-9a-f]{32}")
API = "https://rollypay.io/api/v1/payments"


class LiveContractError(ValueError):
    """Public-safe error code; never include response bodies or credentials."""


@dataclass(frozen=True)
class LiveOrderContract:
    order_id: str
    plan_id: str
    owner_ref: str
    payment_id: str
    amount_snapshot: str | None = None

    def __post_init__(self) -> None:
        if not LIVE_ORDER_RE.fullmatch(self.order_id):
            raise LiveContractError("LIVE_ORDER_ID_INVALID")
        if not get_plan(self.plan_id):
            raise LiveContractError("LIVE_PLAN_INVALID")
        if not re.fullmatch(r"v1_[0-9a-f]{64}", self.owner_ref):
            raise LiveContractError("LIVE_OWNER_INVALID")
        if not PAYMENT_ID_RE.fullmatch(self.payment_id):
            raise LiveContractError("LIVE_PAYMENT_ID_INVALID")
        if self.amount_snapshot is not None:
            if not _same_money(self.amount_snapshot, self.amount_snapshot):
                raise LiveContractError("LIVE_AMOUNT_INVALID")
            if Decimal(self.amount_snapshot) <= 0:
                raise LiveContractError("LIVE_AMOUNT_INVALID")

    @property
    def amount_rub(self) -> str:
        if self.amount_snapshot is not None:
            return self.amount_snapshot
        plan = get_plan(self.plan_id)
        if plan is None:
            raise LiveContractError("LIVE_PLAN_INVALID")
        return price_rub(plan)


@dataclass(frozen=True)
class LiveInvoice:
    order_id: str
    payment_id: str
    amount_rub: str
    pay_url: str


def _same_money(value: object, expected: str) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return False
    try:
        amount = Decimal(str(value))
        return amount.is_finite() and amount == Decimal(expected)
    except InvalidOperation:
        return False


def validate_invoice(
    result: object, *, order_id: str, plan_id: str,
) -> LiveInvoice:
    """Check merchant result before returning a hosted payment URL.

    Provider may omit test/environment markers in production; explicit
    sandbox markers are always rejected.
    """
    if not LIVE_ORDER_RE.fullmatch(order_id):
        raise LiveContractError("LIVE_ORDER_ID_INVALID")
    plan = get_plan(plan_id)
    if plan is None:
        raise LiveContractError("LIVE_PLAN_INVALID")
    if not isinstance(result, dict):
        raise LiveContractError("LIVE_PAYMENT_RESPONSE_INVALID")
    if (result.get("order_id") != order_id
            or not _same_money(result.get("amount"), price_rub(plan))
            or result.get("payment_currency") != "RUB"
            or result.get("status") not in {"created", "processing"}
            or result.get("test") not in (None, False)
            or result.get("environment") in {"sandbox", "test"}):
        raise LiveContractError("LIVE_PAYMENT_RESPONSE_MISMATCH")
    payment_id = result.get("payment_id")
    if not isinstance(payment_id, str) or not PAYMENT_ID_RE.fullmatch(payment_id):
        raise LiveContractError("LIVE_PAYMENT_ID_INVALID")
    try:
        pay_url = safe_pay_url(result.get("pay_url"))
    except ValueError:
        raise LiveContractError("LIVE_PAYMENT_URL_INVALID") from None
    return LiveInvoice(order_id, payment_id, price_rub(plan), pay_url)


async def create_hosted_live_invoice(
    *, order_id: str, plan_id: str, api_key: str,
    order_durably_reserved: bool = False,
    verified_merchant_approved: bool = False,
    verified_h1_fulfillment: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LiveInvoice:
    """Internal preparation for hosted checkout; NOT used by any public route.

    This deliberately rejects until the caller can attest all 3 preconditions.
    A trusted service must verify the flags; they must never come from JSON,
    the browser or a user-facing form.
    """
    if not (order_durably_reserved and verified_merchant_approved
            and verified_h1_fulfillment):
        raise LiveContractError("LIVE_CHECKOUT_PREREQUISITES_MISSING")
    if not isinstance(api_key, str) or len(api_key) < 16:
        raise LiveContractError("LIVE_GATEWAY_NOT_CONFIGURED")
    if not LIVE_ORDER_RE.fullmatch(order_id):
        raise LiveContractError("LIVE_ORDER_ID_INVALID")
    plan = get_plan(plan_id)
    if plan is None:
        raise LiveContractError("LIVE_PLAN_INVALID")
    payload = {
        "order_id": order_id,
        "amount": price_rub(plan),
        "payment_currency": "RUB",
        "description": "Vainah VPN — " + plan["title"],
        # No test:true: this is explicitly the live contract.
    }
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False,
            transport=transport,
        ) as client:
            response = await client.post(
                API, json=payload,
                headers={
                    "X-API-Key": api_key,
                    "X-Nonce": str(uuid4()),
                    "Accept": "application/json",
                },
            )
    except (httpx.TimeoutException, httpx.RequestError):
        raise LiveContractError("LIVE_GATEWAY_UNREACHABLE") from None
    if not 200 <= response.status_code < 300:
        raise LiveContractError("LIVE_GATEWAY_REJECTED")
    if len(response.content) > 65536:
        raise LiveContractError("LIVE_PAYMENT_RESPONSE_INVALID")
    try:
        result = response.json()
    except ValueError:
        raise LiveContractError("LIVE_PAYMENT_RESPONSE_INVALID") from None
    return validate_invoice(result, order_id=order_id, plan_id=plan_id)


def verify_live_paid_event(
    raw_body: bytes, *, timestamp: str | None, signature: str | None,
    signing_secret: str, order: LiveOrderContract,
    now: int | None = None,
) -> bool:
    """Validate an immutable, already-persisted order before ANY VPN write.

    True is proof of a correctly signed provider paid event for this order.
    It is NOT proof H1Cloud provisioning succeeded; the caller must claim an
    atomic once-only fulfillment right in PostgreSQL before issuing access.
    """
    if len(raw_body) > 32768 or not verify_signature(
        raw_body, timestamp, signature, signing_secret, now=now
    ):
        raise LiveContractError("LIVE_WEBHOOK_SIGNATURE_INVALID")
    try:
        data = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        raise LiveContractError("LIVE_WEBHOOK_JSON_INVALID") from None
    if not isinstance(data, dict):
        raise LiveContractError("LIVE_WEBHOOK_JSON_INVALID")
    currency = data.get("currency", data.get("payment_currency"))
    if (data.get("event_type") != "payment.paid"
            or data.get("status") != "paid"
            or data.get("order_id") != order.order_id
            or data.get("payment_id") != order.payment_id
            or currency != "RUB"
            or data.get("payment_currency", "RUB") != "RUB"
            or not _same_money(data.get("amount"), order.amount_rub)
            or data.get("test") not in (None, False)
            or data.get("environment") in {"sandbox", "test"}):
        raise LiveContractError("LIVE_WEBHOOK_PAYMENT_MISMATCH")
    return True


@dataclass(frozen=True)
class H1ProvisionIntent:
    """A proposed H1Cloud action; computing it performs NO H1 API writes."""

    client_name: str
    days: int
    devices: int

    def create_payload(self) -> dict:
        return {
            "name": self.client_name,
            "days": self.days,
            "device_limit": self.devices,
        }

    def extend_payload(self) -> dict:
        # H1Cloud /api/edit adds days; do not retry an uncertain PATCH.
        return {"name": self.client_name, "days": self.days,
                "device_limit": self.devices}


def h1_provision_intent(
    *, email: str, plan_id: str, signing_key: str,
) -> H1ProvisionIntent:
    """Stable pseudonymous H1 username across purchases; never expose email."""
    plan = get_plan(plan_id)
    if plan is None or len(signing_key) < 32:
        raise LiveContractError("LIVE_H1_INTENT_INVALID")
    if not (5 <= len(email) <= 254 and email.count("@") == 1):
        raise LiveContractError("LIVE_EMAIL_INVALID")
    principal = email.strip().lower()
    account_hash = hmac.new(
        signing_key.encode("utf-8"),
        ("vainah-h1-live-user-v1:" + principal).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return H1ProvisionIntent(
        client_name="vn" + account_hash[:28],
        days=plan["days"], devices=plan["devices"],
    )


def production_readiness() -> dict:
    """Operator-only non-secret progress snapshot; never opens real checkout."""
    from .email_auth import ready as email_auth_ready
    from .email_delivery import email_service_ready
    from .h1_panel import H1PanelError, panel_settings

    try:
        panel = panel_settings() is not None
    except H1PanelError:
        panel = False
    checks = {
        "verified_email_sessions": email_auth_ready(),
        "postgres_configured": os.environ.get("DATABASE_URL", "").startswith(
            ("postgresql://", "postgres://")
        ),
        "email_delivery_configured": email_service_ready(),
        "rollypay_api_key_configured": len(os.environ.get("ROLLYPAY_API_KEY", "")) >= 16,
        "rollypay_webhook_signing_configured": (
            len(os.environ.get("ROLLYPAY_SIGNING_SECRET", "")) >= 16
        ),
        "h1cloud_read_configured": panel,
        "live_order_ledger_implemented": True,
        "h1cloud_write_contract_verified": False,
        "merchant_authorized_to_take_payments": False,
        "end_to_end_real_delivery_tested": False,
    }
    return {
        "checks": checks,
        "real_checkout_enabled": False,
        "real_money_can_be_charged": False,
        "auto_vpn_delivery_enabled": False,
        "message": (
            "Live gateway and signed-payment contract are prepared. "
            "Production payment and H1Cloud writes remain disabled until "
            "durable ledger, verified merchant and real provisioning tests."
        ),
    }
