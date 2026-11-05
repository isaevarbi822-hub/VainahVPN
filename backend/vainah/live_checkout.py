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
import secrets

from fastapi import HTTPException, Request

from .email_auth import current_email
from .email_auth import ready as email_login_ready
from .email_delivery import email_service_ready
from .h1_panel import H1PanelError, panel_settings, panel_tls_verify
from .live_fulfillment import FulfillmentError, fulfill_paid_order_once
from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger
from .live_receipt import LiveReceiptError, send_paid_access_receipt_once
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


def _live_infrastructure_ready() -> bool:
    """Common infrastructure checks for both public sales and one live pilot."""
    if not email_login_ready():
        return False
    if not live_account_ready() or not email_service_ready():
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


def live_ready() -> bool:
    """The public merchant/fulfillment gate; pilot cannot weaken it."""
    required = {
        "VAINAH_LIVE_CHECKOUT_ENABLED": "enabled",
        "VAINAH_MERCHANT_APPROVED": "approved",
        "VAINAH_H1_WRITE_CONTRACT_APPROVED": "approved",
        "VAINAH_LIVE_FULFILLMENT_APPROVED": "approved",
        "VAINAH_LIVE_PAID_E2E_VERIFIED": "verified",
    }
    return (
        all(os.environ.get(k) == v for k, v in required.items())
        and _live_infrastructure_ready()
    )


def _pilot_token_configured() -> bool:
    pilot_token = os.environ.get("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", "")
    return (
        len(pilot_token) >= 32
        and pilot_token != os.environ.get("VAINAH_SANDBOX_TEST_TOKEN", "")
    )


def pilot_processing_ready() -> bool:
    """Allow signed callbacks for a *persisted* pilot after checkout is closed.

    Unlike pilot_ready(), this must not depend on the checkout opt-in, the
    operator tokens, or the allowlisted email: revoking invoice creation
    cannot abandon a payment that was already made. It still requires
    the merchant, H1 write, and fulfillment attestations and infrastructure.
    Only the database's immutable is_pilot order marker grants this path.
    """
    required = {
        "VAINAH_MERCHANT_APPROVED": "approved",
        "VAINAH_H1_WRITE_CONTRACT_APPROVED": "approved",
        "VAINAH_LIVE_FULFILLMENT_APPROVED": "approved",
    }
    return (
        all(os.environ.get(k) == v for k, v in required.items())
        and _live_infrastructure_ready()
    )


def pilot_ready() -> bool:
    """A one-order live checkout, private and disabled unless opted in."""
    email = os.environ.get("VAINAH_LIVE_PILOT_EMAIL", "").strip().lower()
    return (
        pilot_processing_ready()
        and os.environ.get("VAINAH_LIVE_PILOT_ENABLED") == "enabled"
        and _pilot_token_configured()
        and 5 <= len(email) <= 254 and email.count("@") == 1
    )


def pilot_readiness_checks() -> dict[str, bool]:
    """Operator-only readiness, boolean-only; never return credentials."""
    email = os.environ.get("VAINAH_LIVE_PILOT_EMAIL", "").strip().lower()
    return {
        "merchant_approved": (
            os.environ.get("VAINAH_MERCHANT_APPROVED") == "approved"
        ),
        "h1_write_contract_approved": (
            os.environ.get("VAINAH_H1_WRITE_CONTRACT_APPROVED") == "approved"
        ),
        "live_fulfillment_approved": (
            os.environ.get("VAINAH_LIVE_FULFILLMENT_APPROVED") == "approved"
        ),
        "live_customer_account_enabled": live_account_ready(),
        "infrastructure_configured": _live_infrastructure_ready(),
        "pilot_creation_enabled": (
            os.environ.get("VAINAH_LIVE_PILOT_ENABLED") == "enabled"
        ),
        "pilot_operator_token_configured": _pilot_token_configured(),
        "pilot_email_allowlisted": (
            5 <= len(email) <= 254 and email.count("@") == 1
        ),
    }


def require_pilot_operator(pilot_token: str | None) -> None:
    """An extra secret separate from sandbox diagnostics or login cookie."""
    expected = os.environ.get("VAINAH_LIVE_PILOT_OPERATOR_TOKEN", "")
    if (not _pilot_token_configured() or not pilot_token
            or not secrets.compare_digest(expected, pilot_token)):
        raise HTTPException(401, "LIVE_PILOT_OPERATOR_REQUIRED")



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
    pilot: bool = False,
) -> dict:
    if pilot:
        if not pilot_ready():
            raise HTTPException(503, "LIVE_PILOT_NOT_READY")
        if plan_id != "30":
            raise HTTPException(422, "LIVE_PILOT_PLAN_RESTRICTED")
    elif not live_ready():
        raise HTTPException(503, "LIVE_CHECKOUT_NOT_READY")
    require_same_origin(request)
    email = current_email(request)
    if email is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    if pilot and not secrets.compare_digest(
        email.strip().lower(), os.environ["VAINAH_LIVE_PILOT_EMAIL"].strip().lower(),
    ):
        raise HTTPException(403, "LIVE_PILOT_EMAIL_NOT_ALLOWED")
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_RE.fullmatch(
        idempotency_key
    ):
        raise HTTPException(422, "LIVE_IDEMPOTENCY_REQUIRED")
    owner_ref = owner_ref_for_email(email)
    ledger = _ledger()
    try:
        reservation = {
            "owner_ref": owner_ref, "verified_email": email,
            "plan_id": plan_id, "idempotency_key": idempotency_key,
        }
        if pilot:
            reservation["pilot"] = True
        order_id, earlier_url = ledger.reserve_checkout(**reservation)
        if earlier_url:
            return {
                "order_id": order_id, "pay_url": earlier_url,
                "status": "created", "gateway": "rollypay",
                **({"operator_pilot": True} if pilot else {}),
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
            "LIVE_PILOT_ALREADY_RESERVED",
        }:
            raise HTTPException(409, code) from None
        if code in {"LIVE_IDEMPOTENCY_INVALID", "LIVE_PLAN_INVALID",
                    "LIVE_ORDER_INVALID"}:
            raise HTTPException(422, code) from None
        raise HTTPException(503, "LIVE_CHECKOUT_UNAVAILABLE") from None
    return {
        "order_id": order_id, "pay_url": invoice.pay_url,
        "status": "created", "gateway": "rollypay",
        **({"operator_pilot": True} if pilot else {}),
    }


async def handle_live_paid_webhook(
    *, raw: bytes, timestamp: str | None, signature: str | None,
) -> dict:
    """Durably verify paid, atomically claim and provision once.

    Ambiguous H1 writes remain locked for manual review. Never place keys,
    tokens, URLs or raw provider responses into webhook output.
    """
    public_ready = live_ready()
    pilot_callback_ready = pilot_processing_ready() if not public_ready else False
    if not public_ready and not pilot_callback_ready:
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
        # The pilot-only gate must never process a normal production order.
        # Pilot status is immutable, persisted during the single checkout
        # reservation, and is checked only after verifying RollyPay's signature.
        if not public_ready and not ledger.is_live_pilot_order(order_id):
            raise HTTPException(503, "PRODUCTION_PAYMENTS_DISABLED")
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
        paid_recorded = ledger.record_signed_paid(
            raw_body=raw, timestamp=timestamp,
            signature=signature, secret=secret,
        )
        if paid_recorded is False:
            # A correctly signed older PAID event cannot reverse a refund or
            # restart fulfillment. Do not invent a current payment status.
            return {
                "ok": True, "stale_event_ignored": True,
                "vpn_delivered": False,
            }
    except HTTPException:
        raise
    except LiveLedgerError as exc:
        if str(exc) == "LIVE_SIGNATURE_INVALID":
            raise HTTPException(403, "INVALID_SIGNATURE") from None
        if str(exc) in {"LIVE_PAYMENT_MISMATCH", "LIVE_ORDER_UNKNOWN",
                        "LIVE_PAYMENT_INVALID_STATE"}:
            raise HTTPException(400, str(exc)) from None
        raise HTTPException(503, "LIVE_LEDGER_UNAVAILABLE") from None
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(400, "LIVE_WEBHOOK_JSON_INVALID") from None

    try:
        result = await fulfill_paid_order_once(
            ledger=ledger, order_id=order_id,
            verified_merchant_approved=True,
            write_contract_approved=True,
        )
    except FulfillmentError as exc:
        if str(exc) in {"LIVE_LEDGER_UNAVAILABLE", "LIVE_DELIVERY_PENDING"}:
            raise HTTPException(503, str(exc), headers={"Retry-After": "5"}) from None
        # Paid status remains durable; no automatic retry on ambiguous H1 write.
        return {
            "ok": True, "status": "paid",
            "vpn_delivered": False, "delivery_state": "manual_review",
        }
    if result["vpn_delivered"]:
        try:
            await send_paid_access_receipt_once(ledger=ledger, order_id=order_id)
        except LiveReceiptError:
            # Entitlement is already persisted. Retrying this callback only
            # retries the idempotent email claim, never another H1 write.
            raise HTTPException(
                503, "LIVE_ACCESS_EMAIL_RETRY",
                headers={"Retry-After": "125"},
            ) from None
    return {
        "ok": True, "status": "paid",
        "vpn_delivered": result["vpn_delivered"],
        "delivery_state": result["status"],
    }
