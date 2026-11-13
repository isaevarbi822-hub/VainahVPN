"""Funded gift cards: buyer pays RollyPay, recipient redeems once via H1Cloud.

Sales require a separate operator-controlled feature flag. Even if new sales
are stopped, existing verified paid gifts may still be redeemed.
"""
from __future__ import annotations

import os
import re
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from .billing import get_plan
from .email_auth import current_email
from .growth import _email
from .live_checkout import (
    _ledger,
    live_account_ready,
    live_ready,
    owner_ref_for_email,
    start_live_checkout,
)
from .live_fulfillment import FulfillmentError, fulfill_paid_order_once
from .live_ledger import LiveLedgerError
from .live_receipt import LiveReceiptError, send_paid_access_receipt_once
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/account/gift-cards", tags=["Funded gifts"])
ALLOWED_GIFT_PLANS = frozenset(("30", "60", "90", "180", "365", "365-family"))
GIFT_CODE_RE = re.compile(r"VG[A-F0-9]{32}")


class GiftPurchase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=2, max_length=24)


class GiftRedeem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=34, max_length=34)


def gift_checkout_ready(request: Request | None = None) -> bool:
    if not live_ready():
        return False
    mode = os.environ.get("VAINAH_GIFT_CARDS_ENABLED")
    if mode == "enabled":
        return True
    if mode != "pilot" or request is None:
        return False
    email = current_email(request)
    allowed = os.environ.get("VAINAH_LIVE_PILOT_EMAIL", "").strip().lower()
    return bool(
        email and 5 <= len(allowed) <= 254 and allowed.count("@") == 1
        and secrets.compare_digest(email.strip().lower(), allowed)
    )


def gift_redemption_ready() -> bool:
    # Turning off *new gift sales* must not strand already-paid customers.
    return (
        live_account_ready()
        and os.environ.get("VAINAH_MERCHANT_APPROVED") == "approved"
        and os.environ.get("VAINAH_H1_WRITE_CONTRACT_APPROVED") == "approved"
        and os.environ.get("VAINAH_LIVE_FULFILLMENT_APPROVED") == "approved"
    )


@router.get("/status")
def gift_card_status(request: Request) -> dict:
    plans = []
    for plan_id in ("30", "60", "90", "180", "365", "365-family"):
        plan = get_plan(plan_id)
        if plan is not None:
            plans.append({
                "id": plan_id, "title": plan["title"],
                "price_rub": f'{plan["kopeks"] / 100:.2f}',
                "days": plan["days"], "devices": plan["devices"],
            })
    return {
        "plans": plans,
        "purchase_enabled": gift_checkout_ready(request),
        "redemption_available": gift_redemption_ready(),
        "funding_source": "rollypay_signed_paid_only",
        "gift_code_after_payment": True,
        "recipient_receives_vpn_only_on_redemption": True,
        "gift_code_reuse_allowed": False,
        "message": (
            "Подарочные карты доступны для покупки и активации."
            if gift_checkout_ready(request)
            else "Покупка подарочных карт ожидает отдельного подтверждения. "
                 "Черновики не являются оплаченными подарками."
        ),
    }


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
async def gift_checkout(
    request: Request, body: GiftPurchase,
    idempotency_key: str | None = Header(default=None),
) -> dict:
    require_same_origin(request)
    if not gift_checkout_ready(request):
        raise HTTPException(503, "GIFT_CHECKOUT_NOT_VERIFIED")
    if current_email(request) is None:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    if body.plan_id not in ALLOWED_GIFT_PLANS or get_plan(body.plan_id) is None:
        raise HTTPException(422, "GIFT_PLAN_INVALID")
    return await start_live_checkout(
        request=request, plan_id=body.plan_id,
        idempotency_key=idempotency_key, gift=True,
    )


@router.get("/mine")
def my_gift_cards(request: Request) -> dict:
    email = _email(request)
    if not live_account_ready():
        raise HTTPException(503, "GIFT_DATABASE_UNAVAILABLE")
    try:
        records = _ledger().buyer_gift_cards(owner_ref_for_email(email))
    except LiveLedgerError:
        raise HTTPException(503, "GIFT_DATABASE_UNAVAILABLE") from None
    return {"items": records, "codes_only_for_paid_orders": True}


async def _finish_delivery(order_id: str, owner_ref: str) -> dict:
    if not gift_redemption_ready():
        raise HTTPException(503, "GIFT_REDEMPTION_UNAVAILABLE")
    try:
        ledger = _ledger()
        if not ledger.recipient_gift_order(order_id=order_id, recipient_ref=owner_ref):
            raise HTTPException(404, "GIFT_REDEMPTION_NOT_FOUND")
        result = await fulfill_paid_order_once(
            ledger=ledger, order_id=order_id,
            verified_merchant_approved=True,
            write_contract_approved=True,
        )
        if result.get("vpn_delivered") is not True:
            if result.get("status") == "manual_review":
                raise HTTPException(409, "GIFT_REQUIRES_SUPPORT")
            raise HTTPException(503, "GIFT_ISSUANCE_PENDING")
        try:
            await send_paid_access_receipt_once(ledger=ledger, order_id=order_id)
        except LiveReceiptError:
            # The paid VPN delivery is durable, never issue a second H1 write.
            return {"redeemed": True, "vpn_delivered": True, "email_pending": True}
        return {"redeemed": True, "vpn_delivered": True, "email_pending": False}
    except LiveLedgerError:
        raise HTTPException(503, "GIFT_DATABASE_UNAVAILABLE") from None
    except FulfillmentError:
        # Claims are never released on H1 timeout: an ambiguous write
        # requires operator reconciliation, not an automatic second write.
        raise HTTPException(409, "GIFT_REQUIRES_SUPPORT") from None


@router.get("/received")
def my_received_gifts(request: Request) -> dict:
    email = _email(request)
    if not live_account_ready():
        raise HTTPException(503, "GIFT_DATABASE_UNAVAILABLE")
    try:
        items = _ledger().recipient_gift_cards(owner_ref_for_email(email))
    except LiveLedgerError:
        raise HTTPException(503, "GIFT_DATABASE_UNAVAILABLE") from None
    return {"items": items}


@router.post("/redeem")
async def redeem_gift_card(request: Request, body: GiftRedeem) -> dict:
    require_same_origin(request)
    if not gift_redemption_ready():
        raise HTTPException(503, "GIFT_REDEMPTION_UNAVAILABLE")
    email = _email(request)
    code = body.code.strip().upper()
    if not GIFT_CODE_RE.fullmatch(code):
        raise HTTPException(422, "GIFT_CODE_INVALID")
    owner = owner_ref_for_email(email)
    try:
        order_id = _ledger().redeem_paid_gift_once(
            gift_code=code, recipient_ref=owner, verified_email=email,
        )
    except LiveLedgerError as exc:
        if str(exc) in ("GIFT_NOT_REDEEMABLE", "GIFT_CODE_INVALID"):
            raise HTTPException(404, "GIFT_CODE_NOT_AVAILABLE") from None
        raise HTTPException(503, "GIFT_DATABASE_UNAVAILABLE") from None
    result = await _finish_delivery(order_id, owner)
    return {**result, "order_id": order_id}


@router.post("/{order_id}/finish")
async def finish_gift_redemption(request: Request, order_id: str) -> dict:
    require_same_origin(request)
    if not re.fullmatch(r"vainah_live_[0-9a-f]{32}", order_id):
        raise HTTPException(404, "GIFT_REDEMPTION_NOT_FOUND")
    owner = owner_ref_for_email(_email(request))
    return await _finish_delivery(order_id, owner)
