"""Guarded RollyPay hosted checkout and signed callback -> H1Cloud delivery.

Live charging is OFF by default. All approvals are trusted server-side flags;
none can be submitted by customers. The same sandbox test route still handles
signed test callbacks; this service only handles approved real transactions.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

from fastapi import HTTPException, Request

from .email_auth import current_email
from .email_auth import ready as email_login_ready
from .h1_panel import H1PanelError, panel_settings, panel_tls_verify
from .live_fulfillment import FulfillmentError, fulfill_paid_order_once
from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger
from .production_contracts import (
    LiveContractError,
    create_hosted_live_invoice,
)
from .telegram_auth import require_same_origin

IDEMPOTENCY_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)


def live_account_ready() -> bool:
    """Customer paid-order access can remain on when new sales are paused."""
    return (
        os.environ.get("VAINAH_LIVE_CUSTOMER_ACCESS_ENABLED") == "enabled"
        and os.environ.get("DATABASE_URL", "").startswith(
            ("postgresql://", "postgres://")
        )
        and len(os.environ.get("SESSION_SIGNING_KEY", "")) >= 32
    )


def live_ready() -> bool:
    """The complete merchant and fulfillment gate, disabled unless approved."""
    required = {
        "VAINAH_LIVE_CHECKOUT_ENABLED": "enabled",
        "VAINAH_MERCHANT_APPROVED": "approved",
        "VAINAH_H1_WRITE_CONTRACT_APPROVED": "approved",
        "VAINAH_LIVE_FULFILLMENT_APPROVED": "approved",
        "VAINAH_LIVE_PAID_E2E_VERIFIED": "verified",
    }
    if any(os.environ.get(k) != v for k, v in required.items()):
        return False
    if not email_login_ready():
        return False
    if not live_account_ready():
        return False
    if not os.environ.get("DATABASE_URL", "").startswith(
        ("postgresql://", "postgres://")
    ):
        return False
    for name, minimum in (
        ("SESSION_SIGNING_KEY", 32),
        ("ROLLYPAY_API_KEY", 16),
        ("ROLLYPAY_SIGNING_SECRET", 16),
    ):
        if len(os.environ.get(name, "")) < minimum:
            return False
    try:
        if panel_settings() is None:
            return False
        panel_tls_verify()
    except H1PanelError:
        return False
    return True


def _ledger() -> PostgresLiveOrderLedger:
    return PostgresLiveOrderLedger(os.environ["DATABASE_URL"])


def owner_ref_for_email(email: str) -> str:
    """Server-verified mailbox identity, never supplied in payment JSON."""
    key = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(key) < 32 or not isinstance(email, str):
        raise HTTPException(503, "LIVE_OWNER_UNAVAILABLE")
    identity = email.strip().lower()
    if not 5 <= len(identity) <= 254 or identity.count("@") != 1:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    digest = hmac.new(
        key.encode(), ("vainah-live-owner-v1:" + identity).encode(),
        hashlib.sha256,
    ).hexdigest()
    return "v1_" + digest


async def start_live_checkout(
    *, request: Request, plan_id: str, idempotency_key: str | None,
) -> dict:
    if not live_ready():
        raise HTTPException(503, "LIVE_CHECKOUT_NOT_READY")
    require_same_origin(request)
    email = current_email(request)
    if email is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_RE.fullmatch(
        idempotency_key
    ):
        raise HTTPException(422, "LIVE_IDEMPOTENCY_REQUIRED")
    owner_ref = owner_ref_for_email(email)
    ledger = _ledger()
    try:
        order_id, earlier_url = ledger.reserve_checkout(
            owner_ref=owner_ref, verified_email=email,
            plan_id=plan_id, idempotency_key=idempotency_key,
        )
        if earlier_url:
            return {
                "order_id": order_id, "pay_url": earlier_url,
                "status": "created", "gateway": "rollypay",
            }
        invoice = await create_hosted_live_invoice(
            order_id=order_id, plan_id=plan_id,
            api_key=os.environ["ROLLYPAY_API_KEY"],
            order_durably_reserved=True,
            verified_merchant_approved=True,
            verified_h1_fulfillment=True,
        )
        if not ledger.attach_hosted_invoice(
            order_id=order_id, payment_id=invoice.payment_id,
            pay_url=invoice.pay_url,
        ):
            raise LiveLedgerError("LIVE_CHECKOUT_RECONCILIATION_REQUIRED")
    except (LiveLedgerError, LiveContractError) as exc:
        # A gateway request may already have created a payment. Never reissue
        # another gateway POST for an uncertain idempotency key.
        code = str(exc)
        if code in {
            "LIVE_CHECKOUT_RECONCILIATION_REQUIRED",
            "LIVE_IDEMPOTENCY_CONFLICT",
        }:
            raise HTTPException(409, code) from None
        if code in {"LIVE_IDEMPOTENCY_INVALID", "LIVE_PLAN_INVALID",
                    "LIVE_ORDER_INVALID"}:
            raise HTTPException(422, code) from None
        raise HTTPException(503, "LIVE_CHECKOUT_UNAVAILABLE") from None
    return {
        "order_id": order_id, "pay_url": invoice.pay_url,
        "status": "created", "gateway": "rollypay",
    }


async def handle_live_paid_webhook(
    *, raw: bytes, timestamp: str | None, signature: str | None,
) -> dict:
    """Durably verify paid, atomically claim and provision once.

    Ambiguous H1 writes remain locked for manual review. Never place keys,
    tokens, URLs or raw provider responses into webhook output.
    """
    if not live_ready():
        raise HTTPException(503, "PRODUCTION_PAYMENTS_DISABLED")
    if len(raw) > 32768:
        raise HTTPException(413, "BODY_TOO_LARGE")
    from .billing import verify_signature

    secret = os.environ["ROLLYPAY_SIGNING_SECRET"]
    if not verify_signature(raw, timestamp, signature, secret):
        raise HTTPException(403, "INVALID_SIGNATURE")
    try:
        import json

        event = json.loads(raw)
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("event_type"), str)
            or event["event_type"] not in {
                "payment.paid", "payment.refunded", "payment.chargeback",
                "refund_request.completed",
            }
            or ("test" in event and event["test"] is not False)
        ):
            raise HTTPException(400, "LIVE_PAYMENT_EVENT_UNSUPPORTED")
        order_id = event.get("order_id")
        from .production_contracts import LIVE_ORDER_RE

        if not isinstance(order_id, str) or not LIVE_ORDER_RE.fullmatch(order_id):
            raise HTTPException(400, "LIVE_ORDER_INVALID")
        ledger = _ledger()
        if event["event_type"] != "payment.paid":
            state = ledger.record_signed_reversal(
                raw_body=raw, timestamp=timestamp,
                signature=signature, secret=secret,
            )
            return {
                "ok": True, "status": state,
                "vpn_delivered": False,
                "manual_h1_revocation_required": True,
            }
        ledger.record_signed_paid(
            raw_body=raw, timestamp=timestamp,
            signature=signature, secret=secret,
        )
    except HTTPException:
        raise
    except LiveLedgerError as exc:
        if str(exc) == "LIVE_SIGNATURE_INVALID":
            raise HTTPException(403, "INVALID_SIGNATURE") from None
        if str(exc) in {"LIVE_PAYMENT_MISMATCH", "LIVE_ORDER_UNKNOWN",
                        "LIVE_PAYMENT_INVALID_STATE"}:
            raise HTTPException(400, str(exc)) from None
        raise HTTPException(503, "LIVE_LEDGER_UNAVAILABLE") from None
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "LIVE_WEBHOOK_JSON_INVALID") from None

    try:
        result = await fulfill_paid_order_once(
            ledger=ledger, order_id=order_id,
            verified_merchant_approved=True,
            write_contract_approved=True,
        )
    except FulfillmentError:
        # Paid status remains durable; no automatic retry on ambiguous H1 write.
        return {
            "ok": True, "status": "paid",
            "vpn_delivered": False, "delivery_state": "manual_review",
        }
    return {
        "ok": True, "status": "paid",
        "vpn_delivered": result["vpn_delivered"],
        "delivery_state": result["status"],
    }
