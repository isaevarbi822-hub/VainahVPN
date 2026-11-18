"""No money moves: HTTP adapters are mocked, DB checks use disposable schemas."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from vainah import (
    live_checkout,
    live_fulfillment,
    live_receipt,
    platega,
    platega_checkout,
)
from vainah.live_ledger import LiveLedgerError, PostgresLiveOrderLedger
from vainah.main import app

MERCHANT = "123e4567-e89b-42d3-a456-426614174001"
PAYMENT = "123e4567-e89b-42d3-a456-426614174002"
ORDER = "vainah_live_" + "a" * 32
OWNER = "v1_" + "b" * 64
SECRET = "test-platega-only-" + "s" * 32
ORIGIN = "https://vainahvpn.onrender.com"
URL = f"https://pay.platega.io/?id={PAYMENT}&mh={MERCHANT}"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("PLATEGA_MERCHANT_ID", MERCHANT)
    monkeypatch.setenv("PLATEGA_SECRET", SECRET)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-owner-" + "s" * 40)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)


def provider_payment(**overrides):
    return {"id": PAYMENT, "payload": ORDER, "mechantId": MERCHANT,
            "status": "PENDING", "paymentDetails": {"amount": 149, "currency": "RUB"},
            **overrides}


def event(**overrides):
    return {"id": PAYMENT, "payload": ORDER, "status": "CONFIRMED", "amount": 149,
            "currency": "RUB", "paymentMethod": 2, **overrides}


def test_hosted_v2_checkout_uses_server_price_and_verified_identity():
    requests = []

    def provider(request):
        requests.append(request)
        assert request.url.host == "app.platega.io"
        assert request.headers["X-MerchantId"] == MERCHANT
        assert request.headers["X-Secret"] == SECRET
        if request.method == "POST":
            body = json.loads(request.content)
            assert request.url.path == "/v2/transaction/process"
            assert body["paymentDetails"] == {"amount": 149, "currency": "RUB"}
            assert body["payload"] == ORDER
            assert body["metadata"] == {"user_email": "owner@example.com", "userId": OWNER}
            assert body["return"] == ORIGIN + "/account.html#orders"
            assert "paymentMethod" not in body  # The hosted form offers the available methods.
            return httpx.Response(200, json={"transactionId": PAYMENT, "status": "PENDING", "url": URL})
        assert request.url.path == "/transaction/" + PAYMENT
        return httpx.Response(200, json=provider_payment())

    invoice = asyncio.run(platega.create_invoice(
        order_id=ORDER, plan_id="30", verified_email="owner@example.com", owner_ref=OWNER,
        transport=httpx.MockTransport(provider),
    ))
    assert invoice.pay_url == URL and invoice.amount_rub == "149.00"
    assert [r.method for r in requests] == ["POST", "GET"]


@pytest.mark.parametrize("change", [
    {"id": MERCHANT}, {"payload": "vainah_live_" + "c" * 32}, {"mechantId": PAYMENT},
    {"merchantId": PAYMENT}, {"paymentDetails": {"amount": 1, "currency": "RUB"}},
    {"paymentDetails": {"amount": 149, "currency": "USD"}}, {"status": ["CONFIRMED"]},
    {"paymentDetails": {"amount": True, "currency": "RUB"}},
    {"paymentDetails": {"amount": "149.001", "currency": "RUB"}},
])
def test_readback_rejects_any_immutable_payment_mismatch(change):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=provider_payment(**change)))
    with pytest.raises(platega.PlategaError):
        asyncio.run(platega.read_payment(PAYMENT, order_id=ORDER, expected_amount="149.00", transport=transport))


@pytest.mark.parametrize("bad", [
    URL.replace("https:", "http:"), URL.replace("pay.platega.io", "pay.platega.io.evil.example"),
    URL.replace("pay.platega.io", "user@pay.platega.io"), URL + "#bad", URL + "&redirect=https://evil.example",
    URL + "&id=" + PAYMENT, URL.replace("pay.platega.io", "pay.platega.io:443"),
    "https://pay.platega.io/", "\n" + URL, URL.replace("/?", "/other?"),
])
def test_only_documented_platega_payform_urls_are_allowed(bad):
    assert platega.safe_pay_url(URL) == URL
    with pytest.raises(platega.PlategaError):
        platega.safe_pay_url(bad)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"{", b'{"id":1,"id":2}', b"{}" * 20000])
def test_malformed_and_oversized_notifications_fail_closed(raw):
    with pytest.raises(platega.PlategaError):
        platega.callback(raw)


def test_provider_redirect_and_body_limit_never_leak_secrets():
    for response in [httpx.Response(302, headers={"Location": "https://evil.example"}),
                     httpx.Response(200, content=b"x" * 65537)]:
        with pytest.raises(platega.PlategaError) as exc:
            asyncio.run(platega.read_payment(
                PAYMENT, order_id=ORDER, expected_amount="149.00",
                transport=httpx.MockTransport(lambda _, r=response: r),
            ))
        assert SECRET not in str(exc.value)


def test_public_gate_is_independent_of_rollypay_and_pilot_flags(monkeypatch):
    monkeypatch.setattr(live_checkout, "_live_infrastructure_ready", lambda gateway: gateway == "platega")
    for name in ("PLATEGA_MERCHANT_APPROVED", "VAINAH_H1_WRITE_CONTRACT_APPROVED",
                 "VAINAH_LIVE_FULFILLMENT_APPROVED"):
        monkeypatch.setenv(name, "approved")
    monkeypatch.setenv("PLATEGA_PILOT_ENABLED", "enabled")
    monkeypatch.delenv("PLATEGA_PAID_E2E_VERIFIED", raising=False)
    assert platega_checkout.processing_ready()
    assert not platega_checkout.ready()
    monkeypatch.setenv("VAINAH_LIVE_CHECKOUT_ENABLED", "enabled")
    monkeypatch.setenv("PLATEGA_CHECKOUT_ENABLED", "enabled")
    monkeypatch.setenv("PLATEGA_PAID_E2E_VERIFIED", "verified")
    assert platega_checkout.ready()
    monkeypatch.setenv("PLATEGA_CHECKOUT_ENABLED", "disabled")
    assert not platega_checkout.ready()
    assert platega_checkout.processing_ready()  # Existing invoices still get delivered.


def test_webhook_auth_checked_before_ledger_or_api(monkeypatch):
    def forbidden():
        pytest.fail("unauthenticated callback reached ledger")

    monkeypatch.setattr(live_checkout, "_ledger", forbidden)
    with TestClient(app) as client:
        for headers in [{}, {"X-MerchantId": MERCHANT, "X-Secret": "bad"},
                        [("X-MerchantId", MERCHANT), ("X-Secret", SECRET), ("X-Secret", SECRET)]]:
            response = client.post("/api/shop/webhooks/platega", headers=headers, json=event())
            assert response.status_code == 403
    assert not platega.authentic_callback(MERCHANT, "ключ")


def bind(ledger, *, gateway="platega", nonce=None, pilot=False, payment=PAYMENT):
    order_id, _ = ledger.reserve_checkout(
        owner_ref=OWNER, verified_email="owner@example.com", plan_id="30",
        idempotency_key=nonce or str(uuid4()), gateway=gateway, pilot=pilot,
    )
    assert ledger.attach_hosted_invoice(
        order_id=order_id, payment_id=payment, gateway=gateway,
        pay_url=URL if gateway == "platega" else "https://pay.rollypay.io/pay/abc123456",
    )
    return order_id


def test_provider_binding_idempotency_and_pilot_quotas(postgres_url):
    ledger = PostgresLiveOrderLedger(postgres_url)
    nonce = str(uuid4())
    order = bind(ledger, nonce=nonce, pilot=True)
    args = {"owner_ref": OWNER, "verified_email": "owner@example.com", "plan_id": "30",
            "idempotency_key": nonce, "pilot": True}
    assert ledger.reserve_checkout(**args, gateway="platega") == (order, URL)
    with pytest.raises(LiveLedgerError):
        ledger.reserve_checkout(**args, gateway="rollypay")
    with pytest.raises(LiveLedgerError, match="PILOT_ALREADY_RESERVED"):
        ledger.reserve_checkout(**{**args, "idempotency_key": str(uuid4())}, gateway="platega")
    # Same opaque payment ID from different providers is a separate identity.
    rolly = bind(ledger, gateway="rollypay", pilot=True)
    assert ledger.is_live_pilot_order(rolly)
    assert not ledger.is_live_pilot_order(order)
    with pytest.raises(LiveLedgerError, match="ORDER_UNKNOWN"):
        ledger.platega_order(rolly)


def test_rollypay_signature_cannot_fund_a_platega_order(postgres_url):
    ledger = PostgresLiveOrderLedger(postgres_url)
    order = bind(ledger)
    raw = json.dumps({"event_type": "payment.paid", "status": "paid", "order_id": order,
                      "payment_id": PAYMENT, "amount": "149.00", "currency": "RUB"}).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    with pytest.raises(LiveLedgerError, match="ORDER_UNKNOWN"):
        ledger.record_signed_paid(raw_body=raw, timestamp=timestamp, signature=signature, secret=SECRET)
    assert ledger.claim_delivery_once(order) is None


@pytest.mark.parametrize("status", ["DISPUTED", "PARTIALLY_REFUNDED", "CHARGEBACKED", "CANCELED"])
def test_reversals_and_late_confirmation_never_issue_access(postgres_url, status):
    ledger = PostgresLiveOrderLedger(postgres_url)
    order = bind(ledger)
    proof = platega.PaymentProof(order, PAYMENT, Decimal("149.00"), status)
    assert not ledger.record_platega_status(proof)
    ledger.record_platega_status(replace(proof, status="CONFIRMED"))
    assert ledger.claim_delivery_once(order) is None


def test_callback_replays_claim_delivery_once_and_survive_paused_sales(postgres_url, monkeypatch):
    ledger = PostgresLiveOrderLedger(postgres_url)
    order = bind(ledger)
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    monkeypatch.setattr(platega_checkout, "processing_ready", lambda: True)
    monkeypatch.setattr(platega_checkout, "ready", lambda: False)
    calls = []

    async def read(payment, **kwargs):
        assert payment == PAYMENT and kwargs["order_id"] == order
        return platega.PaymentProof(order, payment, Decimal("149.00"), "CONFIRMED")

    async def deliver(*, ledger, order_id):
        claim = ledger.claim_delivery_once(order_id)
        if claim:
            calls.append(order_id)
        return {"ok": True, "vpn_delivered": False}

    monkeypatch.setattr(platega, "read_payment", read)
    monkeypatch.setattr(live_checkout, "deliver_confirmed_order", deliver)
    with TestClient(app) as client:
        for _ in range(3):
            response = client.post("/api/shop/webhooks/platega", json=event(payload=order),
                                   headers={"X-MerchantId": MERCHANT, "X-Secret": SECRET})
            assert response.status_code == 200, response.text
    assert calls == [order]


def test_lost_invoice_response_never_repeats_provider_post(postgres_url, monkeypatch):
    ledger = PostgresLiveOrderLedger(postgres_url)
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    monkeypatch.setattr(live_checkout, "current_email", lambda _: "owner@example.com")
    monkeypatch.setattr(platega_checkout, "ready", lambda: True)
    calls = []

    async def uncertain(**kwargs):
        calls.append(kwargs)
        raise platega.PlategaError("PLATEGA_PROVIDER_UNAVAILABLE")

    monkeypatch.setattr(platega, "create_invoice", uncertain)
    with TestClient(app) as client:
        headers = {"Origin": ORIGIN, "Idempotency-Key": str(uuid4())}
        first = client.post("/api/shop/checkout", headers=headers, json={"plan": "30", "gateway": "platega"})
        second = client.post("/api/shop/checkout", headers=headers, json={"plan": "30", "gateway": "platega"})
    assert first.status_code == 503 and second.status_code == 409
    assert len(calls) == 1
    with psycopg.connect(postgres_url) as conn:
        assert conn.execute("SELECT count(*) FROM vainah_live_orders").fetchone()[0] == 1


def test_confirmed_payment_delivers_h1_and_receipt_once(postgres_url, monkeypatch):
    ledger = PostgresLiveOrderLedger(postgres_url)
    order = bind(ledger)
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    monkeypatch.setattr(platega_checkout, "processing_ready", lambda: True)
    writes, emails = [], []

    async def read(payment, **kwargs):
        return platega.PaymentProof(order, payment, Decimal("149.00"), "CONFIRMED")

    async def inspect(_name, *, transport=None):
        return {"panel_ready": True, "found": False, "banned": False}

    class Node:
        def __init__(self, **kwargs):
            assert kwargs["write_contract_approved"]

        async def provision_once(self, *, claim, intent, operation):
            writes.append((claim.order_id, intent.days, intent.devices, operation))
            return SimpleNamespace(subscription_url="https://sub.example.com/platega-test",
                                   expires_at=int(time.time()) + 30 * 86400)

    async def send(to, subject, body, **kwargs):
        emails.append((to, kwargs["idempotency_key"]))

    monkeypatch.setattr(platega, "read_payment", read)
    monkeypatch.setattr(live_fulfillment, "read_h1_issued_client_status", inspect)
    monkeypatch.setattr(live_fulfillment, "LiveH1CloudNode", Node)
    monkeypatch.setattr(live_receipt, "send_email", send)
    with TestClient(app) as client:
        for _ in range(3):
            response = client.post("/api/shop/webhooks/platega", json=event(payload=order),
                                   headers={"X-MerchantId": MERCHANT, "X-Secret": SECRET})
            assert response.status_code == 200, response.text
            assert response.json()["vpn_delivered"] is True
    assert writes == [(order, 30, 3, "create")]
    assert emails == [("owner@example.com", "live-access/" + order)]
    assert ledger.owner_subscription_url(OWNER) == "https://sub.example.com/platega-test"


@pytest.mark.parametrize("failure", ["amount", "api", "pending"])
def test_no_delivery_without_verified_provider_proof(postgres_url, monkeypatch, failure):
    ledger = PostgresLiveOrderLedger(postgres_url)
    order = bind(ledger)
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    monkeypatch.setattr(platega_checkout, "processing_ready", lambda: True)

    async def read(payment, **kwargs):
        if failure == "amount":
            pytest.fail("wrong callback amount reached provider")
        if failure == "api":
            raise platega.PlategaError("PLATEGA_PROVIDER_UNAVAILABLE")
        return platega.PaymentProof(order, payment, Decimal("149.00"), "PENDING")

    monkeypatch.setattr(platega, "read_payment", read)
    with TestClient(app) as client:
        response = client.post("/api/shop/webhooks/platega",
                               json=event(payload=order, amount=1 if failure == "amount" else 149),
                               headers={"X-MerchantId": MERCHANT, "X-Secret": SECRET})
    assert response.status_code == (400 if failure == "amount" else 503)
    assert ledger.claim_delivery_once(order) is None


def test_checkout_rejects_unverified_account_origin_and_client_price(monkeypatch):
    monkeypatch.setattr(platega_checkout, "ready", lambda: True)
    monkeypatch.setattr(live_checkout, "current_email", lambda _: None)
    with TestClient(app) as client:
        body = {"plan": "30", "gateway": "platega"}
        assert client.post("/api/shop/checkout", json=body).status_code == 403
        headers = {"Origin": ORIGIN, "Idempotency-Key": str(uuid4())}
        assert client.post("/api/shop/checkout", headers=headers, json=body).status_code == 401
        assert client.post("/api/shop/checkout", headers=headers, json={**body, "amount": 1}).status_code == 422
        assert client.post("/api/shop/checkout", headers=headers,
                           json={**body, "gateway": "fake"}).status_code == 422


def test_pilot_routes_are_operator_only_and_status_excludes_secrets(postgres_url, monkeypatch):
    ledger = PostgresLiveOrderLedger(postgres_url)
    bind(ledger, pilot=True)
    monkeypatch.setattr(live_checkout, "_ledger", lambda: ledger)
    monkeypatch.setattr(live_checkout, "live_account_ready", lambda: True)
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", "test-operator-" + "a" * 32)
    with TestClient(app) as client:
        assert client.get("/api/shop/operator/platega/status").status_code == 401
        assert client.post("/api/shop/operator/platega/checkout", json={"plan": "30"}).status_code == 401
        response = client.get("/api/shop/operator/platega/status",
                              headers={"X-Sandbox-Token": "test-operator-" + "a" * 32})
    assert response.status_code == 200
    report = response.json()
    assert report["pilot_order_exists"] is True and report["payment_state"] == "created"
    assert report["verified_webhook_received"] is False
    assert SECRET not in response.text and MERCHANT not in response.text
    assert PAYMENT not in response.text and "owner@example.com" not in response.text
