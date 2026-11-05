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


def pending_provider_order(sandbox, monkeypatch, tmp_path):
    from vainah.postgres_ledger import LedgerUnavailable

    client, fake = sandbox
    store = billing.BillingSandbox(
        "provider", "fake-sandbox-key", httpx.MockTransport(fake.respond),
        ledger_path=str(tmp_path / "pending.sqlite3"),
    )
    monkeypatch.setattr(billing, "sandbox", store)

    def unavailable(*args, **kwargs):
        raise LedgerUnavailable("SANDBOX_LEDGER_UNAVAILABLE")

    with monkeypatch.context() as outage:
        outage.setattr(store.ledger, "attach_provider_payment", unavailable)
        result = client.post("/api/shop/sandbox/start", headers=HEADERS, json={"plan": "30"})
    assert result.status_code == 503
    assert len(fake.requests) == 1 and fake.requests[0].method == "POST"
    payment_id = next(iter(fake.orders))
    payment = fake.orders[payment_id]
    payment["status"] = "paid"
    paid = event({"order_id": payment["order_id"]}, payment_id, "payment.paid", "paid")
    return client, fake, store, paid


def test_signed_paid_callback_recovers_lost_provider_binding_without_second_post(
    sandbox, monkeypatch, tmp_path,
):
    client, fake, store, paid = pending_provider_order(sandbox, monkeypatch, tmp_path)
    assert store.read(paid["order_id"])["paid_webhook_received"] is False
    recovered = signed_callback(client, paid)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "paid"
    assert store.read(paid["order_id"])["paid_webhook_received"] is True
    assert signed_callback(client, paid).status_code == 200
    assert [request.method for request in fake.requests] == ["POST", "GET"]


@pytest.mark.parametrize("overrides", [
    {"test": False}, {"environment": "production"},
    {"test": None}, {"environment": None},
    {"payment_id": "pay_other_123456"}, {"order_id": "vainah_test_" + "f" * 32},
    {"amount": "1.00"}, {"payment_currency": "EUR"}, {"status": "created"},
])
def test_pending_recovery_requires_complete_matching_provider_provenance(
    sandbox, monkeypatch, tmp_path, overrides,
):
    client, fake, store, paid = pending_provider_order(sandbox, monkeypatch, tmp_path)
    fake.orders[paid["payment_id"]].update(overrides)
    response = signed_callback(client, paid)
    assert response.status_code == 503
    saved = store.ledger.load_one(paid["order_id"])
    assert saved["payment_id"].startswith("pending:")
    assert not saved["paid_webhook_received"]
    assert [request.method for request in fake.requests] == ["POST", "GET"]


@pytest.mark.parametrize("overrides", [
    {"amount": "1.00"}, {"currency": "EUR"}, {"test": False},
    {"environment": "production"}, {"payment_id": "../private"},
])
def test_pending_recovery_rejects_invalid_signed_fields_before_provider_get(
    sandbox, monkeypatch, tmp_path, overrides,
):
    client, fake, store, paid = pending_provider_order(sandbox, monkeypatch, tmp_path)
    assert signed_callback(client, {**paid, **overrides}).status_code == 400
    assert not store.read(paid["order_id"])["paid_webhook_received"]
    assert [request.method for request in fake.requests] == ["POST"]


def test_pending_recovery_cannot_start_from_forged_callback_or_get_only(
    sandbox, monkeypatch, tmp_path,
):
    client, fake, store, paid = pending_provider_order(sandbox, monkeypatch, tmp_path)
    assert signed_callback(client, paid, valid_signature=False).status_code == 403
    response = client.get(f'/api/shop/sandbox/{paid["order_id"]}', headers=HEADERS)
    assert response.status_code == 502
    assert [request.method for request in fake.requests] == ["POST"]
    assert not store.read(paid["order_id"])["paid_webhook_received"]


def test_original_create_response_accepts_same_binding_recovered_by_callback(
    sandbox, monkeypatch, tmp_path,
):
    client, fake = sandbox
    store = billing.BillingSandbox(
        "provider", "fake-sandbox-key", httpx.MockTransport(fake.respond),
        ledger_path=str(tmp_path / "racing-create.sqlite3"),
    )
    monkeypatch.setattr(billing, "sandbox", store)
    provider_create = store.provider_create

    async def respond_after_callback(order_id, plan):
        result = await provider_create(order_id, plan)
        payment_id = result["payment_id"]
        fake.orders[payment_id]["status"] = "paid"
        paid = event({"order_id": order_id}, payment_id, "payment.paid", "paid")
        raw = json.dumps(paid, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(SECRET.encode(), timestamp.encode() + b"." + raw,
                             hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ) as callback_client:
            callback = await callback_client.post(
                "/api/shop/webhooks/rollypay", content=raw,
                headers={"X-Timestamp": timestamp, "X-Signature": signature,
                         "X-Test-Mode": "true"},
            )
        assert callback.status_code == 200, callback.text
        return result

    monkeypatch.setattr(store, "provider_create", respond_after_callback)
    response = client.post("/api/shop/sandbox/start", headers=HEADERS, json={"plan": "30"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"
    assert response.json()["paid_webhook_received"] is True
    assert [request.method for request in fake.requests] == ["POST", "GET"]


def test_signed_deeply_nested_callback_is_rejected_as_invalid_json(sandbox):
    client, fake = sandbox
    raw = b'{"unused":' + b'[' * 12000 + b'0' + b']' * 12000 + b'}'
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b"." + raw,
                         hashlib.sha256).hexdigest()
    response = client.post(
        "/api/shop/webhooks/rollypay", content=raw,
        headers={"X-Timestamp": timestamp, "X-Signature": signature, "X-Test-Mode": "true"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_JSON"
    assert not fake.requests


def test_signed_callback_retries_safe_prewrite_failure_then_issues_receipt_once(
    sandbox, monkeypatch,
):
    from vainah import sandbox_auto_h1 as auto

    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-receipt-key-" + "r" * 40)
    stored = billing.sandbox.orders[order["order_id"]]
    stored.owner_ref = "v1_" + "f" * 64
    stored.receipt_recipient = billing._seal_receipt_recipient("owner@example.com")
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    state = {"status": "pending", "vpn_delivered": False}
    attempts = []
    writes = []

    async def issue(order_id):
        attempts.append(order_id)
        if len(attempts) == 1:
            state.update(status="failed_before_write", vpn_delivered=False)
        elif not writes:
            writes.append(order_id)
            state.update(status="issued", vpn_delivered=True)
        return state.copy()

    sent = []

    async def send(recipient, **kwargs):
        sent.append((recipient, kwargs))

    monkeypatch.setattr(auto, "auto_issue_paid_sandbox", issue)

    def fake_delivery(oid, *, owner_ref=None, with_access=False):
        assert oid == order["order_id"]
        result = state.copy()
        if with_access:
            assert owner_ref == stored.owner_ref
            if state["vpn_delivered"]:
                result["subscription_url"] = "https://sub.example.com/retry-test-link"
        return result

    monkeypatch.setattr(auto, "read_delivery", fake_delivery)
    monkeypatch.setattr(billing, "send_sandbox_receipt", send)
    paid = event(order, payment_id, "payment.paid", "paid")
    first = signed_callback(client, paid)
    assert first.status_code == 503
    assert first.json()["detail"] == "SANDBOX_AUTO_H1_RETRY_BEFORE_WRITE"
    assert billing.sandbox.read(order["order_id"])["paid_webhook_received"] is True
    assert not writes and not sent
    before = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    )
    assert before.status_code == 200
    assert before.json()["delivery_state"] == "failed_before_write"
    assert before.json()["fulfillment"]["status"] == "retry_pending"
    assert before.json()["receipt_emailed"] is False
    for _ in range(2):
        retried = signed_callback(client, paid)
        assert retried.status_code == 200
        assert retried.json()["delivery_state"] == "issued"
        assert retried.json()["vpn_delivered"] is True
    assert writes == [order["order_id"]]
    assert len(sent) == 1
    assert sent[0][1]["vpn_issued"] is True
    assert sent[0][1]["subscription_url"] == "https://sub.example.com/retry-test-link"
    after = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    )
    assert after.status_code == 200
    assert after.json()["fulfillment"]["status"] == "delivered"
    assert after.json()["delivery_state"] == "issued"
    assert after.json()["receipt_emailed"] is True
    assert "retry-test-link" not in after.text


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



def test_webhook_400_logs_safe_reason_only(sandbox, caplog):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    wrong = event(
        order, payment_id, "payment.paid", "paid", amount="1.00",
    )
    with caplog.at_level("WARNING", logger="uvicorn.error"):
        response = signed_callback(client, wrong)
    assert response.status_code == 400
    assert response.json()["detail"] == "PAYMENT_MISMATCH"
    line = next(
        msg for msg in caplog.messages
        if "rollypay_webhook_rejected" in msg
    )
    assert line == "rollypay_webhook_rejected mode=sandbox code=PAYMENT_MISMATCH"
    assert order["order_id"] not in line
    assert payment_id not in line
    assert fake.orders[payment_id]["status"] == "created"


def test_real_signed_test_webhook_calls_auto_h1_only_after_paid(sandbox, monkeypatch):
    from vainah import sandbox_auto_h1 as auto

    client, fake = sandbox
    issued = []
    refunds = []
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)

    async def fake_issue(order_id):
        issued.append(order_id)
        return {
            "status": "issued",
            "vpn_delivered": True,
        }

    monkeypatch.setattr(auto, "auto_issue_paid_sandbox", fake_issue)
    monkeypatch.setattr(auto, "mark_refunded", lambda oid: refunds.append(oid))
    order, payment_id = create_test_order(client, fake)
    paid = event(order, payment_id, "payment.paid", "paid")
    invalid = signed_callback(client, paid, valid_signature=False)
    assert invalid.status_code == 403
    assert issued == []

    mismatched = signed_callback(
        client, {**paid, "amount": "1.00"},
    )
    assert mismatched.status_code == 400
    assert issued == []

    for _ in range(2):
        result = signed_callback(client, paid)
        assert result.status_code == 200
        assert result.json()["vpn_delivered"] is True
        assert result.json()["delivery_state"] == "issued"
        assert result.json()["test_only"] is True
    assert issued == [order["order_id"], order["order_id"]]
    # The H1 write itself is safeguarded by durable, once-only claims in auto.

    refunded = signed_callback(
        client, event(order, payment_id, "payment.refunded", "refunded"),
    )
    assert refunded.status_code == 200
    assert refunds == [order["order_id"]]
    assert len(issued) == 2


def test_test_vpn_link_is_only_for_bound_verified_owner(sandbox, monkeypatch):
    import asyncio

    from vainah import sandbox_auto_h1 as auto

    client, _fake = sandbox
    owner = "v1_" + "a" * 64
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-verified-email-" + "b" * 40)
    order = asyncio.run(billing.sandbox.create(
        "30", owner_ref=owner, receipt_email="buyer@example.com",
    ))
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    called = []

    def fake_read(order_id, *, owner_ref=None, with_access=False):
        called.append((order_id, owner_ref, with_access))
        return {
            "status": "issued", "vpn_delivered": True,
            "subscription_url": "https://sub.example.com/secret-test-link",
        }

    monkeypatch.setattr(auto, "read_delivery", fake_read)
    assert client.get(
        "/api/shop/my-test-orders/" + order["order_id"] + "/vpn-access"
    ).status_code == 401

    monkeypatch.setattr(
        billing, "_require_verified_sandbox_owner", lambda _request: "v1_" + "d" * 64
    )
    wrong_owner = client.get(
        "/api/shop/my-test-orders/" + order["order_id"] + "/vpn-access"
    )
    assert wrong_owner.status_code == 404
    assert called == []

    monkeypatch.setattr(
        billing, "_require_verified_sandbox_owner", lambda _request: owner,
    )
    delivered = client.get(
        "/api/shop/my-test-orders/" + order["order_id"] + "/vpn-access"
    )
    assert delivered.status_code == 200
    assert delivered.json() == {
        "subscription_url": "https://sub.example.com/secret-test-link",
        "sandbox_only": True, "test_payment": True,
    }
    assert called == [(order["order_id"], owner, True)]


def test_provider_poll_failure_keeps_last_signed_paid_status(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    path = f'/api/shop/sandbox/{order["order_id"]}'

    # A brand-new order cannot pretend to be paid if provider GET fails.
    billing.sandbox.transport = httpx.MockTransport(
        lambda request: httpx.Response(502)
    )
    blocked = client.get(path, headers=HEADERS)
    assert blocked.status_code == 502
    assert blocked.json()["detail"] == "PROVIDER_HTTP_502"

    # The signed payment callback is independent of provider status polling.
    paid = event(order, payment_id, "payment.paid", "paid")
    assert signed_callback(client, paid).status_code == 200

    # Preserve only the signed, durable status, labeled as non-fresh.
    checked = client.get(path, headers=HEADERS)
    assert checked.status_code == 200
    data = checked.json()
    assert data["status"] == "paid"
    assert data["webhook_received"] is True
    assert data["provider_status_fresh"] is False
    assert data["source"] == "last_signed_webhook"
    assert data["provider_read_error"] == "PROVIDER_HTTP_502"
    assert data["real_charge"] is False


def test_cashier_diagnostics_explains_balance_failure_without_creating_payment(
    sandbox,
):
    client, fake = sandbox

    def provider(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v1/balance"
        return httpx.Response(503, json={"error": "temporary error"})

    billing.sandbox.transport = httpx.MockTransport(provider)
    response = client.get("/api/shop/sandbox/diagnostics", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["reason"] == "PROVIDER_HTTP_503"
    assert body["check"] == "GET /api/v1/balance"
    assert body["new_payment_created"] is False
    assert "fake-sandbox-key" not in response.text
    assert fake.orders == {}


def test_operator_only_payment_diagnostics_locates_exact_amount_mismatch(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    original_post_count = sum(
        request.method == "POST" for request in fake.requests
    )
    fake.orders[payment_id]["amount"] = "98.00"
    path = f'/api/shop/sandbox/{order["order_id"]}/payment-diagnostics'

    assert client.get(path).status_code == 401
    report_response = client.get(path, headers=HEADERS)
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["reason"] == "PROVIDER_AMOUNT_MISMATCH"
    assert report["fields"] == {
        "sandbox_mode": "confirmed_at_creation",
        "order_id": "match", "payment_id": "match",
        "amount": "different", "currency": "match",
        "payment_status": "recognized",
    }
    assert report["expected_amount_rub"] == "99.00"
    assert report["observed_amount_rub"] == "98.00"
    assert report["new_payment_created"] is False
    assert report["signed_paid_webhook_received"] is False
    assert payment_id not in report_response.text
    assert fake.orders[payment_id]["pay_url"] not in report_response.text
    assert sum(request.method == "POST" for request in fake.requests) == original_post_count
    assert client.get(
        f'/api/shop/sandbox/{order["order_id"]}', headers=HEADERS,
    ).json()["detail"] == "PROVIDER_AMOUNT_MISMATCH"


def test_payment_diagnostics_classifies_missing_or_malformed_fields(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    path = f'/api/shop/sandbox/{order["order_id"]}/payment-diagnostics'
    fake.orders[payment_id].pop("amount")
    result = client.get(path, headers=HEADERS).json()
    assert result["fields"]["amount"] == "missing"
    assert result["observed_amount_rub"] is None
    assert result["reason"] == "PROVIDER_AMOUNT_MISMATCH"
    fake.orders[payment_id]["amount"] = {"private": "provider-specific"}
    result = client.get(path, headers=HEADERS).json()
    assert result["fields"]["amount"] == "invalid_format"
    assert "provider-specific" not in str(result)
    assert result["reason"] == "PROVIDER_AMOUNT_MISMATCH"
    fake.orders[payment_id]["amount"] = "99.000000000000"
    result = client.get(path, headers=HEADERS).json()
    assert result["fields"]["amount"] == "match"
    assert result["reason"] == "OK"


def test_payment_diagnostics_never_accepts_other_order_or_paid_without_webhook(
    sandbox,
):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    path = f'/api/shop/sandbox/{order["order_id"]}/payment-diagnostics'
    fake.orders[payment_id]["status"] = "paid"
    result = client.get(path, headers=HEADERS).json()
    assert result["reason"] == "OK"
    assert result["provider_status"] == "paid"
    assert result["signed_paid_webhook_received"] is False
    preview = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    ).json()
    assert preview["vpn_delivered"] is False
    fake.orders[payment_id]["order_id"] = "vainah_test_" + "b" * 32
    report = client.get(path, headers=HEADERS).json()
    assert report["reason"] == "PROVIDER_ORDER_MISMATCH"
    assert report["fields"]["order_id"] == "different"


def test_postgres_other_worker_finds_paid_order_for_signed_callback(monkeypatch):
    """Webhook on worker B must find order created on worker A."""
    from vainah.postgres_ledger import PostgresSandboxLedger

    oid = "vainah_test_" + "c" * 32
    pid = "pay_test_cross_worker_123456"
    saved = {
        "order_id": oid, "plan_id": "30", "amount": "99.00",
        "payment_id": pid, "status": "created", "mode": "provider",
        "webhook_received": False, "owner_ref": "v1_" + "d" * 64,
        "receipt_emailed": False, "receipt_recipient": None,
    }
    db = PostgresSandboxLedger("postgresql://mock/test")
    db.load = list  # Worker B started before worker A created order.
    db.load_one = lambda order_id: dict(saved) if order_id == oid else None

    def save(order):
        saved.update({
            "status": order.status,
            "webhook_received": order.webhook_received,
            "paid_webhook_received": order.paid_webhook_received,
            "receipt_emailed": order.receipt_emailed,
        })
        return dict(saved)

    db.save = save
    store = billing.BillingSandbox("provider", "test-key")
    store.ledger = db
    store._ensure_loaded()
    assert store.orders == {}
    event_data = {
        "event_type": "payment.paid", "order_id": oid,
        "payment_id": pid, "amount": "99.00", "currency": "RUB",
        "test": True, "status": "paid",
    }
    result = store.process_webhook(event_data)
    assert result["status"] == "paid"
    assert store.read(oid)["webhook_received"] is True
    assert saved["status"] == "paid"
    assert saved["webhook_received"] is True
    # Duplicate paid callbacks do not create a new payment.
    assert store.process_webhook(event_data)["status"] == "paid"


def test_postgres_order_save_preserves_other_workers_signed_proof(monkeypatch):
    from types import SimpleNamespace

    from vainah import postgres_ledger
    from vainah.postgres_ledger import PostgresSandboxLedger

    executed = []

    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def execute(self, query, params=None):
            executed.append((query, params))
            if "INSERT INTO vainah_sandbox_orders" in query:
                self.saved = params
        def fetchone(self):
            return self.saved

    class FakeConnection:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        postgres_ledger.psycopg, "connect",
        lambda *_a, **_kw: FakeConnection(),
    )
    record = SimpleNamespace(
        order_id="vainah_test_" + "e" * 32, plan_id="30",
        amount="99.00", payment_id="pay_test_123456",
        status="created", mode="provider", webhook_received=False,
        owner_ref=None, receipt_emailed=False, receipt_recipient=None,
    )
    PostgresSandboxLedger("postgresql://mock/test").save(record)
    statement = next(
        sql for sql, _ in executed
        if "ON CONFLICT (order_id) DO UPDATE" in sql
    )
    assert "vainah_sandbox_orders.webhook_received" in statement
    assert "OR EXCLUDED.webhook_received" in statement
    assert "WHEN vainah_sandbox_orders.status = 'paid'" in statement
    assert "'refunded', 'chargeback'" in statement


def test_stale_signed_callbacks_are_acknowledged_without_payment_regression(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    paid = event(order, payment_id, "payment.paid", "paid")
    assert signed_callback(client, paid).status_code == 200
    before = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    ).json()
    assert before["payment_status"] == "paid"

    # Correctly signed but late 'created' may arrive after 'paid'.
    stale = signed_callback(
        client, event(order, payment_id, "payment.created", "created"),
    )
    assert stale.status_code == 200
    assert stale.json()["stale_event_ignored"] is True
    assert stale.json()["status"] == "paid"
    assert stale.json()["vpn_delivered"] is False
    now = client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    ).json()
    assert now["payment_status"] == "paid"
    assert now["fulfillment"]["signed_webhook_received"] is True

    refund = signed_callback(
        client, event(order, payment_id, "payment.refunded", "refunded"),
    )
    assert refund.status_code == 200
    late_paid = signed_callback(client, paid)
    assert late_paid.status_code == 200
    assert late_paid.json()["status"] == "refunded"
    assert late_paid.json()["stale_event_ignored"] is True
    assert client.get(
        f'/api/shop/sandbox/{order["order_id"]}/activation-preview',
        headers=HEADERS,
    ).json()["fulfillment"]["status"] == "blocked"


def test_stale_provider_poll_displays_saved_signed_payment_with_warning(sandbox):
    client, fake = sandbox
    order, payment_id = create_test_order(client, fake)
    assert signed_callback(
        client, event(order, payment_id, "payment.paid", "paid"),
    ).status_code == 200
    # GET eventually lags behind the independently signed paid callback.
    fake.orders[payment_id]["status"] = "created"
    checked = client.get(
        f'/api/shop/sandbox/{order["order_id"]}', headers=HEADERS,
    )
    assert checked.status_code == 200
    result = checked.json()
    assert result["status"] == "paid"
    assert result["webhook_received"] is True
    assert result["provider_status_fresh"] is False
    assert result["provider_read_error"] == "PROVIDER_STATUS_REGRESSION"
    assert result["source"] == "last_signed_webhook"
    assert result["vpn_delivered"] is False
    # A signed proof can be displayed, but never invented by GET polling.
