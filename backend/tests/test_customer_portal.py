"""Customer portal is private and never reveals a VPN URL without paid delivery."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from vainah.main import app
from vainah import customer_portal as portal
from vainah import email_delivery as mail
from vainah.telegram_auth import make_session, SESSION_COOKIE

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "test-only-secure-cookie-secret-0123456789"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567"
    )
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(
            SESSION_COOKIE,
            make_session({
                "telegram_id": "123456789",
                "username": "tester",
                "first_name": "Tester",
            }, SECRET),
        )
        yield client


def test_no_unauthorized_access_to_account_details(monkeypatch):
    monkeypatch.delenv("SESSION_SIGNING_KEY", raising=False)
    with TestClient(app, base_url=ORIGIN) as outsider:
        assert outsider.get("/api/account/overview").status_code == 401
        assert outsider.get("/api/account/access").status_code == 401
        assert outsider.post("/api/account/email/request", headers={"Origin": ORIGIN},
                             json={"email": "victim@example.com"}).status_code == 401


def test_account_overview_no_fake_orders_or_subscription(client, monkeypatch):
    monkeypatch.setattr(portal, "verified_email", lambda _uid: "verified@example.com")
    monkeypatch.setattr(portal, "customer_receipts", lambda _uid: [])
    async def h1(_uid):
        return {"status": "active", "message": "H1Cloud активен.",
                "expires_at": "2030-01-01T00:00:00Z"}
    monkeypatch.setattr(portal, "h1_customer_state", h1)
    result = client.get("/api/account/overview")
    assert result.status_code == 200
    assert result.json()["email"] == {
        "verified": True, "address": "verified@example.com",
    }
    assert result.json()["subscription"] is None
    assert result.json()["orders"] == []


def test_unpaid_account_cannot_reveal_provider_link(client, monkeypatch):
    monkeypatch.setattr(portal, "customer_receipts", lambda _uid: [])
    result = client.get("/api/account/access")
    assert result.status_code == 404
    assert result.json()["detail"] == "PAID_DELIVERY_NOT_FOUND"


def test_verified_email_code_workflow_requires_cookie_and_origin(client, monkeypatch):
    sent = []
    monkeypatch.setattr(portal, "email_service_ready", lambda: True)
    monkeypatch.setattr(
        portal, "start_challenge",
        lambda uid, email: sent.append((uid, email)) or "123456",
    )
    async def mail_code(email, code):
        sent.append((email, code))
    monkeypatch.setattr(portal, "send_verification_code", mail_code)
    monkeypatch.setattr(
        portal, "confirm_challenge",
        lambda uid, code: "owner@example.com"
        if uid == "123456789" and code == "123456" else None,
    )
    invalid = client.post(
        "/api/account/email/request",
        headers={"Origin": "https://attacker.example"},
        json={"email": "owner@example.com"},
    )
    assert invalid.status_code == 403
    valid = client.post(
        "/api/account/email/request", headers={"Origin": ORIGIN},
        json={"email": "Owner@Example.com"},
    )
    assert valid.status_code == 200
    assert sent[0] == ("123456789", "owner@example.com")
    assert sent[1] == ("owner@example.com", "123456")

    verify = client.post(
        "/api/account/email/confirm", headers={"Origin": ORIGIN},
        json={"code": "123456"},
    )
    assert verify.status_code == 200
    assert verify.json()["email"] == "owner@example.com"


def test_delivery_email_requires_prior_verified_recipient(monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "verified_email", lambda _uid: None)
    assert asyncio.run(mail.email_paid_subscription(
        "123456789", "order_123456789012", "https://vpn.example/sub/secret"
    )) is False

    monkeypatch.setattr(mail, "verified_email", lambda _uid: "owner@example.com")
    async def fake_send(to, subject, body, *, transport=None):
        sent.append((to, subject, body))
    monkeypatch.setattr(mail, "send_email", fake_send)
    assert asyncio.run(mail.email_paid_subscription(
        "123456789", "order_123456789012", "https://vpn.example/sub/secret"
    )) is True
    assert len(sent) == 1
    assert sent[0][0] == "owner@example.com"
    assert "https://vpn.example/sub/secret" in sent[0][2]

    with pytest.raises(ValueError):
        asyncio.run(mail.email_paid_subscription(
            "123456789", "order_123456789012", "http://unsafe.example/key"
        ))


def test_notify_function_rejects_order_not_owned(monkeypatch):
    monkeypatch.setattr(portal, "customer_receipts", lambda _uid: [])
    assert asyncio.run(portal.notify_confirmed_subscription(
        "123456789", "order_123456789012"
    )) is False
