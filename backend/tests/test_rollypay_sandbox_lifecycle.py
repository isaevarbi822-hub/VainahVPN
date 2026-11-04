"""Full HTTP sandbox payment lifecycle: zero external calls or real charges.

Provider-side responses are an in-process MockTransport. Live RollyPay delivery
and production H1Cloud activation are deliberately outside this test.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from vainah import billing
from vainah.main import app

TOKEN = "test-operator-token-only-" + "a" * 32
SECRET = "unit-test-webhook-secret-never-production"
HEADERS = {"X-Sandbox-Token": TOKEN}


class FakeRollyPay:
    """Mimics documented sandbox payment responses, never real network."""

    def __init__(self):
        self.orders = {}
        self.requests = []

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "rollypay.io"
        assert request.headers["X-API-Key"] == "fake-sandbox-key"
        assert request.headers.get("X-Nonce")
        if request.method == "POST":
            data = json.loads(request.content)
            assert data["test"] is True
            assert data["payment_currency"] == "RUB"
            assert data["amount"] == "99.00"
            order_id = data["order_id"]
            payment_id = "pay_test_" + uuid4().hex
            payment = {
                "order_id": order_id,
                "payment_id": payment_id,
                "amount": data["amount"],
                "payment_currency": "RUB",
                "status": "created",
                "environment": "sandbox",
                "test": True,
                "pay_url": "https://pay.rollypay.io/pay/test_" + uuid4().hex,
            }
            self.orders[payment_id] = payment
            return httpx.Response(200, json=payment)
        assert request.method == "GET"
        payment_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=self.orders[payment_id])


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", TOKEN)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SHOP_PROVIDER_TEST_ENABLED", "enabled")
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", SECRET)
    fake = FakeRollyPay()
    store = billing.BillingSandbox(
        mode="provider", api_key="fake-sandbox-key",
        transport=httpx.MockTransport(fake.respond),
    )
    monkeypatch.setattr(billing, "sandbox", store)
    with TestClient(app) as client:
        yield client, fake


def signed_callback(client, data, *, test_mode="true", valid_signature=True):
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SECRET.encode(), timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    if not valid_signature:
        signature = "0" * 64
    return client.post(
        "/api/shop/webhooks/rollypay",
        content=raw,
        headers={
            "X-Signature": signature, "X-Timestamp": timestamp,
            "X-Test-Mode": test_mode, "Content-Type": "application/json",
        },
    )


def create_test_order(client, fake):
    response = client.post(
        "/api/shop/sandbox/start", headers=HEADERS, json={"plan": "30"},
    )
    assert response.status_code == 200, response.text
    order = response.json()
    assert order["test_only"] is True
    assert order["real_charge"] is False
    assert order["vpn_delivered"] is False
    assert order["mode"] == "provider"
    assert order["amount_rub"] == "99.00"
    assert order["pay_url"].startswith("https://pay.rollypay.io/pay/")
    payment_id = next(iter(fake.orders))
    assert fake.orders[payment_id]["order_id"] == order["order_id"]
    return order, payment_id


def event(order, payment_id, event_type, status, *, test=True, amount="99.00"):
    return {
        "event_type": event_type, "status": status,
        "test": test, "order_id": order["order_id"],
        "payment_id": payment_id, "amount": amount, "currency": "RUB",
    }


def test_signed_paid_callback_duplicate_and_activation_preview(sandbox):
    client, fake = sandbox
    assert client.post("/api/shop/sandbox/start", json={"plan": "30"}).status_code == 401
    order, payment_id = create_test_order(client, fake)

    # A payment link is not proof of payment.
    blocked = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["subscription_url"] is None

    paid = event(order, payment_id, "payment.paid", "paid")
    fake.orders[payment_id]["status"] = "paid"
    received = signed_callback(client, paid)
    assert received.status_code == 200, received.text
    assert received.json()["status"] == "paid"
    assert received.json()["vpn_delivered"] is False

    # RollyPay may retry. A duplicate must not create a second VPN.
    repeated = signed_callback(client, paid)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "paid"

    checked = client.get(
        f'/api/shop/sandbox/{order["order_id"]}', headers=HEADERS,
    )
    assert checked.status_code == 200
    assert checked.json()["status"] == "paid"
    assert checked.json()["vpn_delivered"] is False

    preview = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    )
    assert preview.status_code == 200
    assert preview.json()["status"] == "demo_ready"
    assert preview.json()["duration_days"] == 30
    assert preview.json()["device_limit"] == 3
    assert preview.json()["h1cloud_connected"] is False
    assert preview.json()["subscription_url"] is None
    assert all(request.url.host == "rollypay.io" for request in fake.requests)


def test_webhook_rejects_bad_signature_non_test_and_wrong_amount(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    paid = event(order, payment_id, "payment.paid", "paid")

    assert signed_callback(client, paid, valid_signature=False).status_code == 403
    assert signed_callback(client, paid, test_mode="false").status_code == 503
    assert signed_callback(client, {**paid, "test": False}).status_code == 400
    assert signed_callback(client, {**paid, "amount": "1.00"}).status_code == 400

    check = client.get(
        f'/api/shop/sandbox/{order["order_id"]}', headers=HEADERS,
    )
    assert check.status_code == 200
    assert check.json()["status"] == "created"
    assert check.json()["vpn_delivered"] is False


def test_cancelled_sandbox_payment_blocks_activation_then_accepts_late_paid(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    fake.orders[payment_id]["status"] = "canceled"
    canceled = signed_callback(
        client, event(order, payment_id, "payment.canceled", "canceled"),
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    blocked = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"

    # RollyPay supports eventual late success, still only demo delivery.
    fake.orders[payment_id]["status"] = "paid"
    late = signed_callback(
        client, event(order, payment_id, "payment.paid", "paid"),
    )
    assert late.status_code == 200
    assert late.json()["status"] == "paid"
    preview = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    )
    assert preview.status_code == 200
    assert preview.json()["status"] == "demo_ready"
    assert preview.json()["vpn_delivered"] is False


def test_real_checkout_stays_off_even_when_sandbox_provider_is_enabled(sandbox):
    client, _ = sandbox
    config = client.get("/api/shop/config")
    assert config.status_code == 200
    assert config.json()["sandbox_available"] is True
    assert config.json()["checkout_ready"] is False
    assert config.json()["provisioning_ready"] is False
    assert client.post(
        "/api/shop/checkout", json={"plan": "30"},
    ).status_code == 503


def test_fulfillment_preview_requires_paid_and_signed_webhook(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    path = f'/api/shop/sandbox/{order["order_id"]}/activation-preview'
    assert client.get(path).status_code == 401
    initial = client.get(path, headers=HEADERS).json()
    assert initial["fulfillment"]["status"] == "blocked"
    assert initial["fulfillment"]["preview_idempotency_key"] is None

    # Polling may confirm paid, but must never substitute a signed webhook.
    fake.orders[payment_id]["status"] = "paid"
    checked = client.get(f'/api/shop/sandbox/{order["order_id"]}', headers=HEADERS)
    assert checked.status_code == 200
    assert checked.json()["status"] == "paid"
    before_hook = client.get(path, headers=HEADERS).json()
    assert before_hook["fulfillment"]["reason"] == "SIGNED_WEBHOOK_REQUIRED"
    assert before_hook["fulfillment"]["status"] == "blocked"

    paid = event(order, payment_id, "payment.paid", "paid")
    response = signed_callback(client, paid)
    assert response.status_code == 200
    assert response.json()["vpn_delivered"] is False
    ready = client.get(path, headers=HEADERS).json()
    plan = ready["fulfillment"]
    assert plan["status"] == "ready_for_review"
    assert plan["operation"] == "create_or_extend"
    assert plan["duration_days"] == 30
    assert plan["device_limit"] == 3
    assert plan["customer_identity_bound"] is False
    assert plan["h1cloud_write_performed"] is False
    assert plan["auto_provisioning_enabled"] is False
    assert plan["subscription_url"] is None
    assert plan["preview_idempotency_key"].startswith("sandbox_")

    # An upstream HTTP failure cannot erase a signed sandbox webhook receipt.
    original = fake.respond
    def provider_unavailable(request):
        if request.method == "GET":
            return httpx.Response(502)
        return original(request)
    fake.requests.clear()
    billing.sandbox.transport = httpx.MockTransport(provider_unavailable)
    assert client.get(path, headers=HEADERS).json()["fulfillment"] == plan
    assert not fake.requests

    assert signed_callback(client, paid).status_code == 200
    after_retry = client.get(path, headers=HEADERS).json()["fulfillment"]
    assert after_retry["preview_idempotency_key"] == plan["preview_idempotency_key"]


def test_refund_blocks_fulfillment_even_after_signed_paid_webhook(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    path = f'/api/shop/sandbox/{order["order_id"]}/activation-preview'
    paid = event(order, payment_id, "payment.paid", "paid")
    assert signed_callback(client, paid).status_code == 200
    assert client.get(path, headers=HEADERS).json()["fulfillment"]["status"] == "ready_for_review"
    refunded = event(order, payment_id, "payment.refunded", "refunded")
    assert signed_callback(client, refunded).status_code == 200
    blocked = client.get(path, headers=HEADERS).json()["fulfillment"]
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "PAYMENT_NOT_PAID"
    assert blocked["preview_idempotency_key"] is None
    assert blocked["h1cloud_write_performed"] is False


def test_mock_payment_never_passes_provider_fulfillment_gate():
    mock = billing.BillingSandbox("mock")
    order = __import__("asyncio").run(mock.create("365-family"))
    mock.simulate(order["order_id"])
    preview = mock.activation_preview(order["order_id"])
    assert preview["status"] == "demo_ready"
    gate = preview["fulfillment"]
    assert gate["status"] == "blocked"
    assert gate["reason"] == "MOCK_PAYMENT_NOT_PROVIDER_VERIFIED"
    assert gate["device_limit"] == 6
    assert gate["duration_days"] == 365
    assert gate["h1cloud_write_performed"] is False
