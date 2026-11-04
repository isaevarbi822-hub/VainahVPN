"""Customer portal is private and never reveals a VPN URL without paid delivery."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from vainah import customer_portal as portal
from vainah import email_delivery as mail
from vainah.main import app
from vainah.telegram_auth import SESSION_COOKIE, make_session

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
    async def fake_send(to, subject, body, *, transport=None, idempotency_key=None):
        sent.append((to, subject, body))
    monkeypatch.setattr(mail, "send_email", fake_send)
    assert asyncio.run(mail.email_paid_subscription(
        "123456789", "order_123456789012", "https://vpn.example/sub/secret"
    )) is True
    assert len(sent) == 1
    assert sent[0][0] == "owner@example.com"
    assert "https://vpn.example/sub/secret" in sent[0][2]
    assert "квитанция" in sent[0][1].lower()
    assert "подтверждение" in sent[0][2]

    with pytest.raises(ValueError):
        asyncio.run(mail.email_paid_subscription(
            "123456789", "order_123456789012", "http://unsafe.example/key"
        ))


def test_notify_function_rejects_order_not_owned(monkeypatch):
    monkeypatch.setattr(portal, "customer_receipts", lambda _uid: [])
    assert asyncio.run(portal.notify_confirmed_subscription(
        "123456789", "order_123456789012"
    )) is False


def test_paid_customer_access_uses_h1_info_with_verified_tls(monkeypatch):
    import ssl

    import httpx

    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com:25105/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-only-provider-token")
    monkeypatch.setenv("PANEL_CLIENT_PREFIX", "tg")
    monkeypatch.setattr(
        portal, "active_receipt", lambda _uid: {"paid": True, "delivered": True}
    )

    async def fake_read(_uid):
        return {"panel_ready": True, "active": True}

    monkeypatch.setattr(portal, "read_h1_status", fake_read)
    custom_ca_context = ssl.create_default_context()
    monkeypatch.setattr(portal, "panel_tls_verify", lambda: custom_ca_context)
    requests = []
    passed_verifiers = []
    original_client = httpx.AsyncClient

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url),
                         request.headers.get("Authorization")))
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": "tg123456789",
                "subscription_url": "https://sub.example.com/private-subscription",
            },
        })

    def client_with_fake_network(**kwargs):
        passed_verifiers.append(kwargs["verify"])
        return original_client(
            transport=httpx.MockTransport(provider), **kwargs
        )

    monkeypatch.setattr(portal.httpx, "AsyncClient", client_with_fake_network)
    subscription = asyncio.run(portal.own_subscription_url("123456789"))
    assert subscription == "https://sub.example.com/private-subscription"
    assert passed_verifiers == [custom_ca_context]
    assert requests == [
        ("GET", "https://vpn-panel.example.com:25105/api/info?name=tg123456789",
         "Bearer test-only-provider-token"),
    ]


@pytest.mark.parametrize("client_data", [
    {"name": "tg000000000", "subscription_url": "https://sub.example.com/a"},
    {"name": "tg123456789", "subscription_url": "http://unsafe.example/a"},
    {"name": "tg123456789", "subscription_url": "https://sub.example.com/a#fragment"},
])
def test_customer_access_rejects_invalid_h1_profile(monkeypatch, client_data):
    import httpx
    from fastapi import HTTPException

    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-only-provider-token")
    monkeypatch.setenv("PANEL_CLIENT_PREFIX", "tg")
    monkeypatch.setattr(
        portal, "active_receipt", lambda _uid: {"paid": True, "delivered": True}
    )

    async def fake_read(_uid):
        return {"panel_ready": True, "active": True}

    monkeypatch.setattr(portal, "read_h1_status", fake_read)
    original_client = httpx.AsyncClient

    def client_with_fake_network(**kwargs):
        return original_client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, json={"ok": True, "client": client_data}
                )
            ), **kwargs
        )

    monkeypatch.setattr(portal.httpx, "AsyncClient", client_with_fake_network)
    with pytest.raises(HTTPException) as error:
        asyncio.run(portal.own_subscription_url("123456789"))
    assert error.value.status_code == 503
    assert error.value.detail == "H1_ACCESS_UNAVAILABLE"


def test_email_h1_profile_lookup_never_grants_subscription(monkeypatch):
    from vainah.production_contracts import h1_provision_intent

    secret = "email-h1-test-signing-secret-" + "x" * 32
    monkeypatch.setenv("SESSION_SIGNING_KEY", secret)
    seen = []

    async def provider(name):
        seen.append(name)
        return {
            "panel_ready": True, "found": True, "active": True,
            "expires_at": "2030-01-01T00:00:00+00:00",
            "subscription_url": "https://secret.example/private-user-url",
        }

    monkeypatch.setattr(portal, "read_h1_issued_client_status", provider)
    state = asyncio.run(portal.h1_email_customer_state("OWNER@example.com"))
    expected = h1_provision_intent(
        email="owner@example.com", plan_id="30", signing_key=secret,
    )
    assert seen == [expected.client_name]
    assert state["status"] == "active"
    assert "private-user-url" not in str(state)
    assert "оплаченная выдача отдельно не подтверждена" in state["message"]


def test_email_only_overview_shows_h1_but_no_unpaid_access(client, monkeypatch):
    monkeypatch.setattr(
        portal, "portal_identity",
        lambda _request, include_email=True: (None, "owner@example.com", "email"),
    )
    seen = []

    async def state(email):
        seen.append(email)
        return {
            "status": "active",
            "message": "Read-only account status; no delivery",
        }

    monkeypatch.setattr(portal, "h1_email_customer_state", state)
    data = client.get("/api/account/overview")
    assert data.status_code == 200
    assert data.json()["h1cloud"]["status"] == "active"
    assert data.json()["subscription"] is None
    assert data.json()["orders"] == []
    assert seen == ["owner@example.com"]
    assert client.get("/api/account/access").status_code == 404
