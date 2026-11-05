"""Payment-to-H1Cloud fulfillment coordinator (not attached to public routes).

The public checkout and live RollyPay callbacks remain disabled. After merchant
approval, a trusted worker can call this with a persisted paid order. The paid
state must first have been verified from a correctly signed RollyPay callback.
All customer access is claimed atomically in PostgreSQL before any H1 writes.
"""
from __future__ import annotations

import os

import httpx

from .h1_live_provision import LiveH1CloudNode, LiveH1Error
from .h1_panel import H1PanelError, read_h1_issued_client_status
from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger
from .production_contracts import LiveContractError, h1_provision_intent


class FulfillmentError(Exception):
    """Safe error code; no provider responses or subscription secrets."""


async def fulfill_paid_order_once(
    *, ledger: PostgresLiveOrderLedger, order_id: str,
    verified_merchant_approved: bool = False,
    write_contract_approved: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """A server-only, fail-closed coordinator for paid delivery.

    Approval flags must originate from trusted server/operator controls, never
    from HTTP requests or user-submitted JSON. The coordinator is intentionally
    not exposed by FastAPI until merchant checks and one-write validation pass.
    """
    if not (verified_merchant_approved and write_contract_approved):
        raise FulfillmentError("LIVE_FULFILLMENT_DISABLED")
    signing_key = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(signing_key) < 32:
        raise FulfillmentError("LIVE_SIGNING_KEY_UNAVAILABLE")

    # Duplicate callbacks or concurrent workers cannot claim the same order.
    # No paid order => no claim => no H1 request.
    try:
        claim = ledger.claim_delivery_once(order_id)
        snapshot = ledger.delivery_snapshot(order_id) if claim is None else None
    except LiveLedgerError:
        raise FulfillmentError("LIVE_LEDGER_UNAVAILABLE") from None
    if claim is None:
        if snapshot and snapshot["payment_state"] == "paid" and snapshot["signed_paid"]:
            state = snapshot["delivery_state"]
            if state == "delivered" and snapshot["owner_block"] != "manual_review":
                return {"status": "delivered", "vpn_delivered": True}
            if state == "pending" and snapshot["owner_block"] != "manual_review":
                # Another order of this owner may be extending the same H1
                # account. Keep this callback retryable until it can claim.
                raise FulfillmentError("LIVE_DELIVERY_PENDING")
            return {
                "status": "manual_review" if snapshot["owner_block"] == "manual_review" else state,
                "vpn_delivered": False,
            }
        return {"status": "not_claimable", "vpn_delivered": False}

    try:
        email = ledger.claimed_verified_email(
            order_id=claim.order_id, owner_ref=claim.owner_ref,
        )
        intent = h1_provision_intent(
            email=email, plan_id=claim.plan_id, signing_key=signing_key,
        )
        state = await read_h1_issued_client_status(
            intent.client_name, transport=transport,
        )
        if not state.get("panel_ready") or state.get("banned"):
            raise FulfillmentError("LIVE_H1_PREFLIGHT_FAILED")
        operation = "extend" if state.get("found") else "create"
        proof = await LiveH1CloudNode(
            transport=transport, write_contract_approved=True,
        ).provision_once(claim=claim, intent=intent, operation=operation)
        if not ledger.mark_delivered(
            order_id=claim.order_id, subscription_url=proof.subscription_url,
            panel_confirmed=True,
        ):
            raise FulfillmentError("LIVE_DELIVERY_PERSIST_FAILED")
        return {
            "status": "delivered",
            "vpn_delivered": True,
            "operation": operation,
            "expires_at": proof.expires_at,
        }
    except (H1PanelError, LiveH1Error, LiveLedgerError,
            LiveContractError, FulfillmentError) as exc:
        # A write might have succeeded even if the response was lost.
        # Do not release the claim or automatically retry non-idempotent edits.
        try:
            ledger.mark_uncertain(claim.order_id)
        except LiveLedgerError:
            pass
        if isinstance(exc, FulfillmentError):
            raise
        raise FulfillmentError("LIVE_FULFILLMENT_MANUAL_REVIEW") from None
