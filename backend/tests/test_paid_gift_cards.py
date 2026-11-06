"""Paid gifts cannot issue VPN before verified provider payment or reuse a code."""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from fastapi.testclient import TestClient

from vainah import email_auth, gift_cards, live_checkout
from vainah.live_ledger import LiveLedgerError, PostgresLiveOrderLedger
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
KEY = "gift-tests-long-session-key-0123456789-abcdef"
ROOT = Path(__file__).resolve().parents[2]


def customer(email=None):
    c = TestClient(app, base_url=ORIGIN)
    if email:
        c.cookies.set(email_auth.EMAIL_SESSION_COOKIE, email_auth._sign_session(email))
    return c


def test_sales_disabled_by_default_and_guest_cannot_check_out(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", KEY)
    monkeypatch.delenv("VAINAH_GIFT_CARDS_ENABLED", raising=False)
    with customer() as client:
        status = client.get("/api/account/gift-cards/status")
        assert status.status_code == 200
        assert status.json()["purchase_enabled"] is False
        response = client.post(
            "/api/account/gift-cards/checkout",
            headers={"Origin": ORIGIN, "Idempotency-Key": "abc"},
            json={"plan_id": "30"},
        )
        assert response.status_code == 503
    assert gift_cards.GIFT_CODE_RE.fullmatch("VG" + "A" * 32)
    assert not gift_cards.GIFT_CODE_RE.fullmatch("VG" + "A" * 31)


def test_verified_checkout_only_delegates_to_real_payments(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", KEY)
    monkeypatch.setattr(gift_cards, "gift_checkout_ready", lambda: True)
    observed = []
    async def fake_checkout(**kwargs):
        observed.append(kwargs)
        return {"order_id": "vainah_live_" + "a" * 32,
                "pay_url": "https://rollypay.io/pay/examplegift",
                "status": "created"}
    monkeypatch.setattr(gift_cards, "start_live_checkout", fake_checkout)
    with customer() as guest:
        response = guest.post(
            "/api/account/gift-cards/checkout",
            headers={"Origin": ORIGIN}, json={"plan_id": "30"},
        )
        assert response.status_code == 401
    with customer("buyer@example.com") as buyer:
        response = buyer.post(
            "/api/account/gift-cards/checkout",
            headers={"Origin": ORIGIN},
            json={"plan_id": "pilot-1d"},
        )
        assert response.status_code == 422
        response = buyer.post(
            "/api/account/gift-cards/checkout",
            headers={"Origin": ORIGIN, "Idempotency-Key": "a" * 36},
            json={"plan_id": "30"},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "created"
    assert len(observed) == 1
    assert observed[0]["gift"] is True
    assert observed[0]["plan_id"] == "30"


def test_unfunded_gift_is_never_redeemable_and_owner_is_verified(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", KEY)
    monkeypatch.setattr(gift_cards, "gift_redemption_ready", lambda: True)
    attempts = []
    class Ledger:
        def redeem_paid_gift_once(self, *, gift_code, recipient_ref, verified_email):
            attempts.append((gift_code, recipient_ref, verified_email))
            raise LiveLedgerError("GIFT_NOT_REDEEMABLE")
    monkeypatch.setattr(gift_cards, "_ledger", lambda: Ledger())
    with customer() as guest:
        assert guest.post(
            "/api/account/gift-cards/redeem",
            headers={"Origin": ORIGIN},
            json={"code": "VG" + "A" * 32},
        ).status_code == 401
    with customer("receiver@example.com") as user:
        assert user.post(
            "/api/account/gift-cards/redeem",
            json={"code": "VG" + "A" * 32},
        ).status_code == 403
        assert user.post(
            "/api/account/gift-cards/redeem",
            headers={"Origin": ORIGIN}, json={"code": "invalid"},
        ).status_code == 422
        response = user.post(
            "/api/account/gift-cards/redeem",
            headers={"Origin": ORIGIN},
            json={"code": "VG" + "A" * 32},
        )
        assert response.status_code == 404
    assert len(attempts) == 1
    assert attempts[0][2] == "receiver@example.com"
    assert attempts[0][1].startswith("v1_")


def test_funded_gift_paid_callback_does_not_automatically_provision(monkeypatch):
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", "x" * 48)
    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    from vainah import billing
    monkeypatch.setattr(billing, "verify_signature", lambda *a, **k: True)
    observed = []
    class Ledger:
        def record_signed_paid(self, **kwargs):
            observed.append("paid")
            return True
        def is_gift_order(self, order_id):
            observed.append("gift")
            return True
    monkeypatch.setattr(live_checkout, "_ledger", lambda: Ledger())
    async def forbidden_fulfillment(**kwargs):
        raise AssertionError("Gift paid callback cannot issue H1 access")
    monkeypatch.setattr(live_checkout, "fulfill_paid_order_once", forbidden_fulfillment)
    import asyncio
    result = asyncio.run(live_checkout.handle_live_paid_webhook(
        raw=json.dumps({"event_type": "payment.paid", "test": False,
                        "order_id": "vainah_live_" + "a" * 32}).encode(),
        timestamp="1234567890", signature="fake",
    ))
    assert result["gift_card_funded"] is True
    assert result["vpn_delivered"] is False
    assert observed == ["paid", "gift"]


def test_paid_gift_delivery_calls_once_only_after_claim(monkeypatch):
    monkeypatch.setattr(gift_cards, "gift_redemption_ready", lambda: True)
    calls = []
    class Ledger:
        def recipient_gift_order(self, *, order_id, recipient_ref):
            calls.append("owned")
            return True
    monkeypatch.setattr(gift_cards, "_ledger", lambda: Ledger())
    async def fulfill(**kwargs):
        calls.append("fulfill")
        assert kwargs["verified_merchant_approved"] is True
        assert kwargs["write_contract_approved"] is True
        return {"status": "delivered", "vpn_delivered": True}
    async def receipt(**kwargs):
        calls.append("email")
    monkeypatch.setattr(gift_cards, "fulfill_paid_order_once", fulfill)
    monkeypatch.setattr(gift_cards, "send_paid_access_receipt_once", receipt)
    import asyncio
    result = asyncio.run(gift_cards._finish_delivery(
        "vainah_live_" + "a" * 32, "v1_" + "b" * 64,
    ))
    assert result["vpn_delivered"] is True
    assert calls == ["owned", "fulfill", "email"]


def test_gift_ledger_has_atomic_payment_and_one_use_guards():
    src = inspect.getsource(PostgresLiveOrderLedger)
    assert "gift_redeemed_at IS NULL" in src
    assert "gift_code_hash=%s AND is_gift=TRUE" in src
    assert "payment_state='paid' AND webhook_at IS NOT NULL" in src
    assert "delivery_state='pending'" in src
    assert "target.is_gift = FALSE OR target.gift_redeemed_at IS NOT NULL" in src
    assert "gift_buyer_ref" in src
    assert "secrets.token_hex(16)" in src
    assert "ON CONFLICT DO NOTHING" in src


def test_page_never_treats_gift_draft_as_payment():
    js = (ROOT / "storefront" / "gift-cards.js").read_text(encoding="utf-8")
    html = (ROOT / "storefront" / "gifts.html").read_text(encoding="utf-8")
    assert "purchase_enabled" in js
    assert "/api/account/gift-cards/checkout" in js
    assert "/api/account/gift-cards/redeem" in js
    assert "Idempotency-Key" in js
    assert "innerHTML" not in js
    assert "localStorage" not in js
    assert "gift-cards.js" in html
