"""Additional hosted gateway, sharing verified accounts and once-only H1 delivery."""
from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request

from . import live_checkout, platega
from .billing import CATALOG
from .live_ledger import LiveLedgerError
from .telegram_auth import require_same_origin


def processing_ready() -> bool:
    # Closing NEW sales must not abandon an invoice already paid by a customer.
    return (
        os.environ.get("PLATEGA_MERCHANT_APPROVED") == "approved"
        and os.environ.get("VAINAH_H1_WRITE_CONTRACT_APPROVED") == "approved"
        and os.environ.get("VAINAH_LIVE_FULFILLMENT_APPROVED") == "approved"
        and live_checkout._live_infrastructure_ready("platega")
    )


def ready() -> bool:
    return (
        os.environ.get("VAINAH_LIVE_CHECKOUT_ENABLED") == "enabled"
        and os.environ.get("PLATEGA_CHECKOUT_ENABLED") == "enabled"
        and os.environ.get("PLATEGA_PAID_E2E_VERIFIED") == "verified"
        and processing_ready()
    )


def pilot_ready() -> bool:
    email = os.environ.get("VAINAH_LIVE_PILOT_EMAIL", "").strip().lower()
    return (
        os.environ.get("PLATEGA_PILOT_ENABLED") == "enabled"
        and live_checkout._pilot_token_configured()
        and 5 <= len(email) <= 254 and email.count("@") == 1
        and processing_ready()
    )


async def start_checkout(*, request: Request, plan_id: str,
                         idempotency_key: str | None, pilot: bool = False) -> dict:
    if not (pilot_ready() if pilot else ready()):
        raise HTTPException(503, "PLATEGA_CHECKOUT_NOT_READY")
    require_same_origin(request)
    email = live_checkout.current_email(request)
    if email is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    if pilot and not secrets.compare_digest(
        email.lower().encode(), os.environ["VAINAH_LIVE_PILOT_EMAIL"].strip().lower().encode(),
    ):
        raise HTTPException(403, "LIVE_PILOT_EMAIL_NOT_ALLOWED")
    if (plan_id not in {p["id"] for p in CATALOG}
            or (pilot and plan_id != "30")):
        raise HTTPException(422, "LIVE_PLAN_INVALID")
    if not isinstance(idempotency_key, str) or not live_checkout.IDEMPOTENCY_RE.fullmatch(idempotency_key):
        raise HTTPException(422, "LIVE_IDEMPOTENCY_REQUIRED")
    owner_ref = live_checkout.owner_ref_for_email(email)
    ledger = live_checkout._ledger()
    try:
        order_id, pay_url = ledger.reserve_checkout(
            owner_ref=owner_ref, verified_email=email, plan_id=plan_id,
            idempotency_key=idempotency_key, gateway="platega", pilot=pilot,
        )
        if pay_url is None:
            invoice = await platega.create_invoice(
                order_id=order_id, plan_id=plan_id, verified_email=email, owner_ref=owner_ref,
            )
            if not ledger.attach_hosted_invoice(
                order_id=order_id, payment_id=invoice.payment_id,
                pay_url=invoice.pay_url, gateway="platega",
            ):
                raise LiveLedgerError("LIVE_CHECKOUT_RECONCILIATION_REQUIRED")
            pay_url = invoice.pay_url
        platega.safe_pay_url(pay_url)
    except LiveLedgerError as exc:
        if str(exc) in {"LIVE_CHECKOUT_RECONCILIATION_REQUIRED", "LIVE_IDEMPOTENCY_CONFLICT",
                        "LIVE_PILOT_ALREADY_RESERVED"}:
            raise HTTPException(409, str(exc)) from None
        raise HTTPException(503, "LIVE_CHECKOUT_UNAVAILABLE") from None
    except platega.PlategaError:
        raise HTTPException(503, "PLATEGA_CHECKOUT_UNAVAILABLE") from None
    return {"order_id": order_id, "pay_url": pay_url, "status": "created", "gateway": "platega"}


async def handle_callback(*, request: Request) -> dict:
    if not platega.configured():
        raise HTTPException(503, "PLATEGA_NOT_CONFIGURED")
    # Reject duplicate authentication headers as well as incorrect credentials.
    if (len(request.headers.getlist("x-merchantid")) != 1
            or len(request.headers.getlist("x-secret")) != 1
            or not platega.authentic_callback(
                request.headers.get("x-merchantid"), request.headers.get("x-secret"))):
        raise HTTPException(403, "PLATEGA_CALLBACK_UNAUTHORIZED")
    if not processing_ready():
        raise HTTPException(503, "PLATEGA_PROCESSING_NOT_READY")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 32768:
            raise HTTPException(413, "BODY_TOO_LARGE")
        body.extend(chunk)
    try:
        event = platega.callback(bytes(body))
    except platega.PlategaError:
        raise HTTPException(400, "PLATEGA_CALLBACK_INVALID") from None
    ledger = live_checkout._ledger()
    try:
        order = ledger.platega_order(event.order_id)
        if (order["payment_id"] != event.payment_id
                or platega.amount(order["amount_rub"]) != event.amount_rub):
            raise HTTPException(400, "LIVE_PAYMENT_MISMATCH")
        proof = await platega.read_payment(
            event.payment_id, order_id=event.order_id, expected_amount=order["amount_rub"],
        )
        if proof.status == "PENDING":
            raise HTTPException(503, "PLATEGA_PAYMENT_PENDING", headers={"Retry-After": "5"})
        eligible = ledger.record_platega_status(proof)
    except LiveLedgerError as exc:
        if str(exc) in {"LIVE_ORDER_UNKNOWN", "LIVE_PAYMENT_MISMATCH"}:
            raise HTTPException(400, str(exc)) from None
        raise HTTPException(503, "LIVE_LEDGER_UNAVAILABLE") from None
    except platega.PlategaError:
        # An authenticated notification is not enough when API proof is unavailable.
        raise HTTPException(503, "PLATEGA_VERIFICATION_UNAVAILABLE") from None
    if not eligible:
        return {"ok": True, "vpn_delivered": False}
    return await live_checkout.deliver_confirmed_order(ledger=ledger, order_id=event.order_id)
