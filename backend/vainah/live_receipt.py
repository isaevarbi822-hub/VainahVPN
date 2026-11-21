"""One receipt with a personal VPN link for a confirmed real paid order.

This path is not active until the existing production merchant/fulfillment
gates are independently approved. No email is sent for a test or unissued VPN.
"""
from __future__ import annotations

import html
from uuid import uuid4

from fastapi import HTTPException

from .billing import get_plan
from .email_delivery import send_email
from .h1_live_provision import LiveH1Error, _validate_subscription_url
from .live_ledger import LiveLedgerError, PostgresLiveOrderLedger


class LiveReceiptError(Exception):
    """Sanitized internal status. Never contains a recipient or VPN URL."""


async def send_paid_access_receipt_once(
    *, ledger: PostgresLiveOrderLedger, order_id: str,
) -> dict:
    """Use a persisted, email-locked, paid+delivered entitlement.

    Retries may resend the same email with one Resend idempotency key, but
    can NEVER reissue H1Cloud access. The owner is bound at checkout.
    """
    token = uuid4().hex
    try:
        claim = ledger.claim_paid_access_email(order_id, claim_token=token)
    except LiveLedgerError:
        raise LiveReceiptError("LIVE_ACCESS_EMAIL_LEDGER_UNAVAILABLE") from None
    if claim["status"] == "sent":
        return {"status": "sent", "already_sent": True}
    if claim["status"] == "in_progress":
        raise LiveReceiptError("LIVE_ACCESS_EMAIL_IN_PROGRESS")
    if claim["status"] != "claimed":
        raise LiveReceiptError("LIVE_ACCESS_EMAIL_NOT_READY")

    try:
        plan = get_plan(claim["plan_id"])
        if plan is None:
            raise ValueError("LIVE_PLAN_INVALID")
        try:
            url = _validate_subscription_url(claim["subscription_url"])
        except LiveH1Error:
            raise ValueError("LIVE_ACCESS_EMAIL_URL_INVALID") from None
        escaped_url = html.escape(url, quote=True)
        body = (
            "<h2>Vainah VPN — подписка активирована</h2>"
            "<p>Оплата подтверждена. VPN доступен для подключения.</p>"
            "<p>Номер заказа: " + html.escape(order_id) + "</p>"
            "<p>Тариф: " + html.escape(plan["title"]) + "</p>"
            "<p>Срок: " + str(plan["days"]) + " дней, до "
            + str(plan["devices"]) + " устройств.</p>"
            "<p><b>Личная ссылка подписки:</b></p>"
            '<p><a href="' + escaped_url + '">' + escaped_url + "</a></p>"
            "<p>Не передавай эту ссылку другим. Она также доступна "
            "в личном кабинете.</p>"
            "<p>Это подтверждение заказа, не фискальный кассовый чек.</p>"
        )
        await send_email(
            claim["recipient"], "Vainah VPN — оплата и VPN-подписка", body,
            idempotency_key="live-access/" + order_id,
        )
        if not ledger.finish_paid_access_email(order_id, claim_token=token):
            raise LiveReceiptError("LIVE_ACCESS_EMAIL_FINISH_UNCERTAIN")
        return {"status": "sent", "already_sent": False}
    except (HTTPException, ValueError, LiveLedgerError, LiveReceiptError):
        # Email may have reached Resend before its acknowledgement was lost.
        # The stable idempotency key prevents duplicate sends on quick retries.
        try:
            ledger.release_paid_access_email(order_id, claim_token=token)
        except LiveLedgerError:
            pass
        raise LiveReceiptError("LIVE_ACCESS_EMAIL_UNAVAILABLE") from None
