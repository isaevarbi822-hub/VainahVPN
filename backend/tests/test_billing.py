import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah.billing import (
    BillingSandbox,
    ProviderError,
    safe_pay_url,
    verify_signature,
)
from vainah.main import app

client = TestClient(app)


def test_catalog_matches_historical_six_plans():
    r = client.get("/api/shop/plans")
    assert r.status_code == 200
    rows = r.json()["items"]
    assert [x["priceRub"] for x in rows] == [
        "99.00", "160.00", "219.00", "339.00", "700.00", "1000.00"
    ]
    assert [x["id"] for x in rows] == [
        "30", "60", "90", "180", "365", "365-family"
    ]
    assert rows[-1]["devices"] == 6
    assert rows[0]["devices"] == 3


def test_original_website_is_home_and_next_dashboard_still_available():
    page = client.get("/")
    assert page.status_code == 200
    assert "Vainah VPN" in page.text
    assert client.get("/plans.html").status_code == 200
    checkout = client.get("/checkout.html")
    assert checkout.status_code == 200
    assert 'id="shop-plans"' in checkout.text
    assert client.get("/app").status_code == 200
    assert "Vainah VPN" in client.get("/app").text


def test_public_checkout_fail_closed():
    config = client.get("/api/shop/config").json()
    assert config["checkout_ready"] is False
    assert config["provisioning_ready"] is False
    r = client.post("/api/shop/checkout", json={"plan": "30"})
    assert r.status_code == 503
    assert r.json()["detail"] == "LIVE_CHECKOUT_NOT_READY"


def test_operator_token_required_by_default():
    r = client.post("/api/shop/sandbox/start", json={"plan": "30"})
    assert r.status_code == 401


def test_mock_sandbox_order_no_money_no_vpn(monkeypatch):
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", "a" * 32)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    headers = {"X-Sandbox-Token": "a" * 32}
    r = client.post("/api/shop/sandbox/start", headers=headers, json={"plan": "365-family"})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["amount_rub"] == "1000.00"
    assert order["test_only"] is True
    assert order["real_charge"] is False
    assert order["vpn_delivered"] is False
    assert order["pay_url"] is None
    simulated = client.post(
        f'/api/shop/sandbox/{order["order_id"]}/simulate', headers=headers
    )
    assert simulated.status_code == 200
    assert simulated.json()["status"] == "paid"
    assert simulated.json()["vpn_delivered"] is False
    repeated = client.post(
        f'/api/shop/sandbox/{order["order_id"]}/simulate', headers=headers
    )
    assert repeated.json()["status"] == "paid"


def test_test_order_rejects_fake_price_and_invalid_plan(monkeypatch):
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", "a" * 32)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    h = {"X-Sandbox-Token": "a" * 32}
    r = client.post("/api/shop/sandbox/start", headers=h, json={"plan": "30", "amount": "1.00"})
    assert r.status_code == 422
    r = client.post("/api/shop/sandbox/start", headers=h, json={"plan": "nonexistent"})
    assert r.status_code == 422


@pytest.mark.parametrize("url", [
    "http://pay.rollypay.io/pay/abcdefghi",
    "https://pay.rollypay.io.evil.example/pay/abcdefghi",
    "https://pay.rollypay.io@evil.example/pay/abcdefghi",
    "https://pay.rollypay.io/pay/abcdefghi?redirect=evil",
    "https://pay.rollypay.io/pay/../abc",
    "javascript:alert(1)",
])
def test_payment_url_allowlist_rejects_untrusted_redirects(url):
    with pytest.raises(ValueError):
        safe_pay_url(url)


def test_payment_url_allowlist_accepts_provider_path():
    assert safe_pay_url("https://pay.rollypay.io/pay/tok_123456") == (
        "https://pay.rollypay.io/pay/tok_123456"
    )


def test_webhook_signature_tamper_and_timestamp_replay_protection():
    raw = b'{"event_type":"payment.paid","test":true}'
    now = int(time.time())
    ts = str(now)
    signature = hmac.new(b"unit-test-secret-key", ts.encode() + b"." + raw,
                         hashlib.sha256).hexdigest()
    assert verify_signature(raw, ts, signature, "unit-test-secret-key", now=now)
    assert not verify_signature(raw + b" ", ts, signature, "unit-test-secret-key", now=now)
    assert not verify_signature(raw, ts, signature, "unit-test-secret-key", now=now + 301)
    assert not verify_signature(raw, ts, "0" * 64, "unit-test-secret-key", now=now)


def test_webhook_fails_without_secret_or_authorized_test_order(monkeypatch):
    monkeypatch.delenv("ROLLYPAY_SIGNING_SECRET", raising=False)
    assert client.post("/api/shop/webhooks/rollypay", content=b"{}").status_code == 503
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", "valid-sandbox-signing-secret")
    raw = b'{"event_type":"payment.paid","test":true}'
    r = client.post("/api/shop/webhooks/rollypay", content=raw,
                    headers={"X-Signature": "bad", "X-Timestamp": str(int(time.time()))})
    assert r.status_code == 403


def test_provider_sandbox_create_and_signed_status():
    payloads = []

    def mock_response(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "rollypay.io"
        assert request.headers.get("X-API-Key") == "unit-test-key"
        assert request.headers.get("X-Nonce")
        payload = json.loads(request.content)
        payloads.append(payload)
        assert payload["test"] is True
        assert payload["payment_currency"] == "RUB"
        assert payload["amount"] == "99.00"
        return httpx.Response(200, json={
            "order_id": payload["order_id"],
            "payment_id": "pay_test_1234567890",
            "amount": "99.00", "payment_currency": "RUB",
            "test": True, "status": "created",
            "pay_url": "https://pay.rollypay.io/pay/tok_123456",
        })
    provider = BillingSandbox("provider", "unit-test-key", httpx.MockTransport(mock_response))
    order = asyncio.run(provider.create("30"))
    assert order["mode"] == "provider"
    assert order["pay_url"].startswith("https://pay.rollypay.io/")
    assert len(payloads) == 1
    event = {
        "event_type": "payment.paid", "status": "paid", "test": True,
        "order_id": order["order_id"], "payment_id": "pay_test_1234567890",
        "amount": "99.00", "currency": "RUB",
    }
    assert provider.process_webhook(event)["status"] == "paid"
    assert provider.process_webhook(event)["status"] == "paid"
    assert provider.read(order["order_id"])["vpn_delivered"] is False
    with pytest.raises(HTTPException):
        provider.process_webhook({**event, "amount": "1.00"})
    refunded = {**event, "event_type": "payment.refunded", "status": "refunded"}
    assert provider.process_webhook(refunded)["status"] == "refunded"
    with pytest.raises(HTTPException):
        provider.process_webhook(event)


def test_provider_rejects_unsafe_return_link_and_does_not_save_order():
    def malicious(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(200, json={
            "order_id": payload["order_id"], "payment_id": "pay_test_1234567890",
            "amount": "99.00", "payment_currency": "RUB", "status": "created",
            "pay_url": "https://phishing.example/pay/123456",
        })
    provider = BillingSandbox("provider", "unit-test-key", httpx.MockTransport(malicious))
    with pytest.raises(ProviderError) as err:
        asyncio.run(provider.create("30"))
    assert str(err.value) == "PROVIDER_PAYMENT_LINK_INVALID"
    assert not provider.orders
