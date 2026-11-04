"""No real charges or H1Cloud writes: verified test receipt mail lifecycle."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from vainah import billing, email_auth, email_delivery
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "test-only-session-secret-" + "v" * 40
TOKEN = "test-only-operator-token-" + "x" * 40
WEBHOOK_SECRET = "test-only-webhook-secret-" + "y" * 24


class FakeProvider:
    def __init__(self):
        self.orders = {}

    def handle(self, request):
        assert request.url.host == "rollypay.io"
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["test"] is True
            pay_id = "pay_test_" + uuid4().hex
            response = {
                "order_id": payload["order_id"], "payment_id": pay_id,
                "amount": payload["amount"], "payment_currency": "RUB",
                "status": "created", "test": True, "environment": "sandbox",
                "pay_url": "https://pay.rollypay.io/pay/tok_" + uuid4().hex,
            }
            self.orders[pay_id] = response
            return httpx.Response(200, json=response)
        assert request.method == "GET"
        return httpx.Response(200, json=self.orders[request.url.path.rsplit("/", 1)[-1]])


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", TOKEN)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SHOP_PROVIDER_TEST_ENABLED", "enabled")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    provider = FakeProvider()
    db = str(tmp_path / "orders.sqlite3")
    store = billing.BillingSandbox(
        "provider", "fake-test-key", httpx.MockTransport(provider.handle),
        ledger_path=db,
    )
    monkeypatch.setattr(billing, "sandbox", store)
    sent = []

    async def capture(to, subject, body, *, transport=None, idempotency_key=None):
        sent.append({
            "recipient": to, "subject": subject, "body": body,
            "idempotency": idempotency_key,
        })
    monkeypatch.setattr(email_delivery, "send_email", capture)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(
            email_auth.EMAIL_SESSION_COOKIE,
            email_auth._sign_session("owner@example.com"),
        )
        yield client, provider, db, sent


def callback(client, order, payment_id, *, paid=True, amount=None):
    status = "paid" if paid else "canceled"
    payload = {
        "event_type": "payment." + status, "status": status,
        "test": True, "order_id": order["order_id"],
        "payment_id": payment_id,
        "amount": amount if amount is not None else order["amount_rub"],
        "currency": "RUB",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    sig = hmac.new(
        WEBHOOK_SECRET.encode(), stamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/api/shop/webhooks/rollypay", content=raw,
        headers={
            "X-Timestamp": stamp, "X-Signature": sig,
            "X-Test-Mode": "true", "Content-Type": "application/json",
        },
    )


def create_order(client):
    result = client.post(
        "/api/shop/sandbox/start",
        headers={"X-Sandbox-Token": TOKEN}, json={"plan": "30"},
    )
    assert result.status_code == 200, result.text
    order = result.json()
    assert order["owner_bound"] is True
    assert order["receipt_emailed"] is False
    return order


def test_only_verified_paid_owner_gets_test_email_once(setup, monkeypatch):
    client, provider, db, sent = setup
    order = create_order(client)
    path = f'/api/shop/my-test-orders/{order["order_id"]}/email-receipt'
    assert client.post(path, headers={"Origin": ORIGIN}).status_code == 409
    assert client.post(path).status_code == 403
    other_cookie = email_auth._sign_session("other@example.com")
    client.cookies.set(email_auth.EMAIL_SESSION_COOKIE, other_cookie)
    assert client.post(path, headers={"Origin": ORIGIN}).status_code == 404
    client.cookies.set(
        email_auth.EMAIL_SESSION_COOKIE,
        email_auth._sign_session("owner@example.com"),
    )

    payment_id = next(iter(provider.orders))
    assert callback(client, order, payment_id, amount="1.00").status_code == 400
    assert client.post(path, headers={"Origin": ORIGIN}).status_code == 409
    assert callback(client, order, payment_id).status_code == 200

    first = client.post(path, headers={"Origin": ORIGIN})
    assert first.status_code == 200, first.text
    assert first.json() == {
        "sent": True, "already_sent": False,
        "test_only": True, "vpn_delivered": False,
    }
    assert len(sent) == 1
    assert sent[0]["recipient"] == "owner@example.com"
    assert sent[0]["idempotency"] == "sandbox-receipt/" + order["order_id"]
    assert "ТЕСТОВЫЙ" in sent[0]["body"]
    assert "ДЕНЬГИ НЕ СПИСАНЫ" in sent[0]["body"]
    assert "КЛЮЧ ПОДПИСКИ НЕ ВЫДАН" in sent[0]["body"]
    assert "https://vpn" not in sent[0]["body"]
    assert client.post(path, headers={"Origin": ORIGIN}).json()["already_sent"] is True
    assert len(sent) == 1

    # Persisted receipt flag and owner ref survive a full process recreation.
    assert Path(db).exists()
    monkeypatch.setattr(
        billing, "sandbox",
        billing.BillingSandbox(
            "provider", "fake-test-key", httpx.MockTransport(provider.handle),
            ledger_path=db,
        ),
    )
    again = client.post(path, headers={"Origin": ORIGIN})
    assert again.status_code == 200
    assert again.json()["already_sent"] is True
    assert len(sent) == 1


def test_test_email_is_blocked_for_anonymous_and_cancelled_orders(setup):
    client, provider, _, sent = setup
    order = create_order(client)
    url = f'/api/shop/my-test-orders/{order["order_id"]}/email-receipt'
    assert callback(client, order, next(iter(provider.orders)), paid=False).status_code == 200
    assert client.post(url, headers={"Origin": ORIGIN}).status_code == 409
    client.cookies.clear()
    assert client.post(url, headers={"Origin": ORIGIN}).status_code == 401
    assert sent == []


def test_resend_idempotency_header_is_set_without_exposing_subscription(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "fake-key-of-valid-length")
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "Vainah VPN <noreply@verified.example>")
    seen = []

    def fake_email(request):
        assert request.method == "POST"
        assert request.url.host == "api.resend.com"
        assert request.headers["Idempotency-Key"] == "sandbox-receipt/test_123"
        body = json.loads(request.content)
        assert body["to"] == ["owner@example.com"]
        seen.append(body)
        return httpx.Response(200, json={"id": "test_message_id"})

    import asyncio

    asyncio.run(email_delivery.send_email(
        "owner@example.com", "Test", "<p>Testing</p>",
        idempotency_key="sandbox-receipt/test_123",
        transport=httpx.MockTransport(fake_email),
    ))
    assert len(seen) == 1
