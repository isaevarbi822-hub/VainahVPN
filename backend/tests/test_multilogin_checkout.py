"""Cross-login RollyPay checkout identity: no real provider calls or database writes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vainah import email_auth, live_checkout, telegram_auth
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "unit-test-signing-key-" + "x" * 48
EMAIL = "linked@example.com"
TELEGRAM_ID = "123456789"
NONCE = "123e4567-e89b-42d3-a456-426614174000"
PAY_URL = "https://pay.rollypay.io/pay/checkout123456"
ORDER = "vainah_live_" + "c" * 32


@pytest.fixture
def telegram_config(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567"
    )


def telegram_cookie() -> str:
    return telegram_auth.make_session(
        {"telegram_id": TELEGRAM_ID, "username": "exampleuser",
         "first_name": "Test"},
        SECRET,
    )


def test_verified_telegram_link_used_as_email_checkout_owner(
    telegram_config, monkeypatch
):
    reads = []

    def get_link(telegram_id):
        reads.append(telegram_id)
        return EMAIL

    monkeypatch.setattr(live_checkout, "telegram_verified_email", get_link)
    req = SimpleNamespace(cookies={
        telegram_auth.SESSION_COOKIE: telegram_cookie(),
    })
    assert live_checkout.current_email(req) == EMAIL
    assert reads == [TELEGRAM_ID]


def test_unlinked_telegram_cannot_create_checkout(
    telegram_config, monkeypatch
):
    monkeypatch.setattr(live_checkout, "telegram_verified_email", lambda _: None)
    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)

    def should_not_create_ledger():
        raise AssertionError("Unverified Telegram must never reserve a payment")

    monkeypatch.setattr(live_checkout, "_ledger", should_not_create_ledger)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(telegram_auth.SESSION_COOKIE, telegram_cookie())
        response = client.post("/api/shop/checkout", headers={
            "Origin": ORIGIN, "Idempotency-Key": NONCE,
        }, json={"plan": "30"})
    assert response.status_code == 401
    assert response.json()["detail"] == "VERIFIED_EMAIL_REQUIRED"


def test_tampered_telegram_session_never_reads_email_link(
    telegram_config, monkeypatch
):
    def no_link(_):
        raise AssertionError("Invalid Telegram session must not read mappings")

    monkeypatch.setattr(live_checkout, "telegram_verified_email", no_link)
    req = SimpleNamespace(cookies={
        telegram_auth.SESSION_COOKIE: telegram_cookie() + "X",
    })
    assert live_checkout.current_email(req) is None


def test_google_and_email_signed_session_keeps_priority(
    telegram_config, monkeypatch
):
    def no_link(_):
        raise AssertionError("Verified email should not use Telegram mapping")

    monkeypatch.setattr(live_checkout, "telegram_verified_email", no_link)
    req = SimpleNamespace(cookies={
        telegram_auth.SESSION_COOKIE: telegram_cookie(),
        email_auth.EMAIL_SESSION_COOKIE: email_auth._sign_session("google@example.com"),
    })
    assert live_checkout.current_email(req) == "google@example.com"


def test_verified_telegram_checkout_and_status_use_same_owner(
    telegram_config, monkeypatch
):
    monkeypatch.setattr(live_checkout, "telegram_verified_email",
                        lambda user_id: EMAIL if user_id == TELEGRAM_ID else None)
    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    monkeypatch.setattr(live_checkout, "live_account_ready", lambda: True)
    monkeypatch.setenv("ROLLYPAY_API_KEY", "test-provider-key-only")

    class FakeLedger:
        def __init__(self):
            self.reservations = []
            self.lookups = []
        def reserve_checkout(self, **kwargs):
            self.reservations.append(kwargs)
            return ORDER, PAY_URL
        def checkout_intent_status(self, **kwargs):
            self.lookups.append(kwargs)
            return {"found": True, "payment_state": "created",
                    "renewal_ready": False}

    ledger = FakeLedger()
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)

    # A pre-existing hosted invoice is reused, so RollyPay is never called.
    async def no_new_invoice(**kwargs):
        raise AssertionError("Never generate a new RollyPay invoice in this test")

    monkeypatch.setattr(live_checkout, "create_hosted_live_invoice", no_new_invoice)

    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(telegram_auth.SESSION_COOKIE, telegram_cookie())
        checkout = client.post("/api/shop/checkout", headers={
            "Origin": ORIGIN, "Idempotency-Key": NONCE,
        }, json={"plan": "30"})
        status = client.get("/api/shop/checkout-intent?plan=30",
                            headers={"Idempotency-Key": NONCE})

    assert checkout.status_code == 200
    assert checkout.json()["pay_url"] == PAY_URL
    assert status.status_code == 200
    assert ledger.reservations[0]["verified_email"] == EMAIL
    assert ledger.reservations[0]["owner_ref"] == ledger.lookups[0]["owner_ref"]
    assert ledger.reservations[0]["idempotency_key"] == NONCE
