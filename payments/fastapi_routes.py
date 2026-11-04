"""Optional FastAPI adapter: include_router(router) in an EXISTING app.

A webhook is durably received, not treated as verified order fulfillment.
Do not issue VPN entitlements from this adapter alone.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from .rollypay import RollyPayClient, RollyPayError, parse_payment_event, verify_signature

router = APIRouter()


@router.get("/api/health/rollypay")
def check_rollypay():
    if not os.environ.get("ROLLYPAY_API_KEY"):
        return {"connected": False, "reason": "api_key_missing"}
    try:
        ok = RollyPayClient().api_healthy()
    except RollyPayError:
        return {"connected": False, "reason": "api_unavailable"}
    return {"connected": ok, "reason": "api_verified" if ok else "unexpected_response"}


@router.get("/api/health/rollypay-webhook")
def check_webhook_setup():
    return {
        "configured": bool(os.environ.get("ROLLYPAY_SIGNING_SECRET") and
                           os.environ.get("DATABASE_URL")),
        "verified_delivery": False,  # No claim until a signed callback is observed.
    }


@router.post("/webhooks/rollypay")
async def receive_rollypay(request: Request):
    secret = os.environ.get("ROLLYPAY_SIGNING_SECRET")
    database_url = os.environ.get("DATABASE_URL")
    if not secret or not database_url:
        raise HTTPException(503, "Webhook is not configured")
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("x-timestamp"),
                            request.headers.get("x-signature"), secret):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        event = parse_payment_event(raw)
    except ValueError:
        raise HTTPException(400, "Invalid payment event") from None
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO rollypay_webhook_events
                      (payment_id, order_id, event_type, status, amount, currency,
                       is_test, payload_sha256)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (payment_id, payload_sha256) DO NOTHING
                """, (event["payment_id"], event["order_id"], event["event_type"],
                      event["status"], event["amount"], event["currency"],
                      event["is_test"], event["payload_sha256"]))
    except Exception as exc:
        # The provider must retry when durable recording fails; no secrets in response.
        raise HTTPException(503, "Could not persist webhook") from exc
    return {"ok": True}
