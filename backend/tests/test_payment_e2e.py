"""End-to-end TEST-only billing: signed callbacks cannot deliver a VPN."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
from fastapi.testclient import TestClient

from vainah import billing
from vainah.main import app

client = TestClient(app)


def test_signed_test_payment_cycle_never_issues_real_vpn(monkeypatch):
    operator_token = "test-operator-token-only-" + "x" * 24
    signing_secret = "test-signature-secret-" + "z" * 24
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SHOP_PROVIDER_TEST_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", operator_token)
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", signing_secret)
    calls = []

    def fake_provider(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "rollypay.io"
        assert request.headers.get("X-API-Key") == "nonsecret-unit-test-key"
        if request.method == "POST":
            data = json.loads(request.content)
            assert data["test"] is True
            assert data["amount"] == "149.00"
            assert data["payment_currency"] == "RUB"
            calls.append(data["order_id"])
            return httpx.Response(200, json={
                "order_id": data["order_id"],
                "payment_id": "opaque_test_123456",
                "amount": "149.00",
                "payment_currency": "RUB",
                "test": True,
                "environment": "sandbox",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/tok_123456",
            })
        assert request.method == "GET"
        assert len(calls) == 1
        return httpx.Response(200, json={
            "order_id": calls[0],
            "payment_id": "opaque_test_123456",
            "amount": "149.00",
            "payment_currency": "RUB",
            "test": True,
            "environment": "sandbox",
            "status": "paid",
        })

    fake = billing.BillingSandbox(
        "provider", "nonsecret-unit-test-key",
        httpx.MockTransport(fake_provider),
    )
    monkeypatch.setattr(billing, "sandbox", fake)
    assert client.get("/api/shop/sandbox/orders").status_code == 401

    started = client.post(
        "/api/shop/sandbox/start",
        headers={"X-Sandbox-Token": operator_token},
        json={"plan": "30"},
    )
    assert started.status_code == 200
    order = started.json()
    assert order["status"] == "created"
    assert order["real_charge"] is False
    assert order["vpn_delivered"] is False
    assert len(calls) == 1

    data = {
        "event_type": "payment.paid",
        "status": "paid",
        "order_id": order["order_id"],
        "payment_id": "opaque_test_123456",
        "currency": "RUB",
        "amount": "149.00",
        "test": True,
    }
    raw = json.dumps(data, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        signing_secret.encode(), timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "X-Test-Mode": "true",
        "Content-Type": "application/json",
    }
    wrong = client.post(
        "/api/shop/webhooks/rollypay",
        content=raw + b" ",
        headers=headers,
    )
    assert wrong.status_code == 403
    assert fake.read(order["order_id"])["status"] == "created"

    for _ in range(2):
        callback = client.post(
            "/api/shop/webhooks/rollypay", content=raw, headers=headers
        )
        assert callback.status_code == 200
        assert callback.json() == {
            "ok": True, "test_only": True,
            "status": "paid", "vpn_delivered": False,
        }

    check = client.get(
        "/api/shop/sandbox/" + order["order_id"] + "/activation-preview",
        headers={"X-Sandbox-Token": operator_token},
    )
    assert check.status_code == 200
    result = check.json()
    assert result["status"] == "demo_ready"
    assert result["payment_status"] == "paid"
    assert result["h1cloud_connected"] is False
    assert result["vpn_delivered"] is False
    assert result["subscription_url"] is None

    # Signed but NOT sandbox-only requests never enable live charges.
    assert client.post(
        "/api/shop/webhooks/rollypay", content=raw,
        headers={**headers, "X-Test-Mode": "false"},
    ).status_code == 503
    assert client.post("/api/shop/checkout", json={"plan": "30"}).status_code == 503
