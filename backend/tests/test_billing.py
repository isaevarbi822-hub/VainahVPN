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
            "test": True, "environment": "sandbox", "status": "created",
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
            "test": True, "environment": "sandbox",
            "pay_url": "https://phishing.example/pay/123456",
        })
    provider = BillingSandbox("provider", "unit-test-key", httpx.MockTransport(malicious))
    with pytest.raises(ProviderError) as err:
        asyncio.run(provider.create("30"))
    assert str(err.value) == "PROVIDER_PAYMENT_LINK_INVALID"
    assert not provider.orders


def test_provider_status_refresh_returns_real_sandbox_status_only():
    payment_id = "pay_test_1234567890"
    def provider_response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            created = json.loads(request.content)
            return httpx.Response(200, json={
                "order_id": created["order_id"], "payment_id": payment_id,
                "amount": "99.00", "payment_currency": "RUB",
                "test": True, "environment": "sandbox", "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/tok_123456",
            })
        assert request.method == "GET"
        assert request.url.path.endswith("/" + payment_id)
        assert request.headers.get("X-Nonce")
        return httpx.Response(200, json={
            "order_id": order_id, "payment_id": payment_id,
            "amount": "99.00", "payment_currency": "RUB",
            "test": True, "environment": "sandbox", "status": "paid",
        })

    service = BillingSandbox("provider", "test-key",
                             httpx.MockTransport(provider_response))
    created = asyncio.run(service.create("30"))
    order_id = created["order_id"]
    updated = asyncio.run(service.refresh(order_id))
    assert updated["status"] == "paid"
    assert updated["test_only"] is True
    assert updated["vpn_delivered"] is False


def test_provider_rejects_ambiguous_non_sandbox_payment_at_creation():
    def provider_response(request: httpx.Request) -> httpx.Response:
        created = json.loads(request.content)
        return httpx.Response(200, json={
            "order_id": created["order_id"],
            "payment_id": "pay_test_1234567890", "amount": "99.00",
            "payment_currency": "RUB", "status": "created",
            "pay_url": "https://pay.rollypay.io/pay/tok_123456",
        })
    service = BillingSandbox("provider", "test-key",
                             httpx.MockTransport(provider_response))
    with pytest.raises(ProviderError, match="PROVIDER_SANDBOX_NOT_CONFIRMED"):
        asyncio.run(service.create("30"))
    assert service.orders == {}


def test_provider_rejects_status_from_non_sandbox_payment():
    payment_id = "pay_test_1234567890"
    def response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            created = json.loads(request.content)
            return httpx.Response(200, json={
                "order_id": created["order_id"], "payment_id": payment_id,
                "amount": "99.00", "payment_currency": "RUB",
                "test": True, "environment": "sandbox",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/tok_123456",
            })
        return httpx.Response(200, json={
            "order_id": order_id, "payment_id": payment_id,
            "amount": "99.00", "payment_currency": "RUB",
            "test": False, "environment": "production", "status": "paid",
        })
    service = BillingSandbox("provider", "test-key", httpx.MockTransport(response))
    created = asyncio.run(service.create("30"))
    order_id = created["order_id"]
    with pytest.raises(ProviderError, match="PROVIDER_SANDBOX_NOT_CONFIRMED"):
        asyncio.run(service.refresh(order_id))
    assert service.read(order_id)["status"] == "created"


def test_provider_diagnostics_is_read_only_and_never_exposes_records():
    seen = []
    def response(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        assert request.method == "GET"
        assert request.url.path == "/api/v1/payments"
        assert request.url.params["environment"] == "sandbox"
        assert request.headers["X-API-Key"] == "unit-test-key"
        return httpx.Response(200, json={"items": [
            {"payment_id": "secret-payment", "customer_email": "private@example.com"}
        ], "total": 1})

    provider = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(response)
    )
    result = asyncio.run(provider.provider_diagnostics())
    assert result["connected"] is True
    assert result["new_payment_created"] is False
    assert "private@example.com" not in str(result)
    assert len(seen) == 1


def test_provider_diagnostics_reports_only_http_code():
    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={
            "error": "private text that must never escape"
        })
    provider = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(rejected)
    )
    with pytest.raises(ProviderError, match="PROVIDER_HTTP_503"):
        asyncio.run(provider.provider_diagnostics())


@pytest.mark.parametrize(("payment_id", "status", "expected"), [
    (None, "created", "PROVIDER_PAYMENT_ID_MISSING"),
    ("", "created", "PROVIDER_PAYMENT_ID_MISSING"),
    ("bad/id", "created", "PROVIDER_PAYMENT_ID_FORMAT"),
    ("pay_test_1234567890", "unexpected", "PROVIDER_PAYMENT_STATUS_INVALID"),
])
def test_provider_creation_errors_identify_which_field_failed(
    payment_id, status, expected,
):
    def response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "order_id": body["order_id"],
            "amount": "99.00",
            "payment_currency": "RUB",
            "test": True,
            "environment": "sandbox",
            "payment_id": payment_id,
            "status": status,
            "pay_url": "https://pay.rollypay.io/pay/tok_123456",
        })
    service = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(response)
    )
    with pytest.raises(ProviderError, match=expected):
        asyncio.run(service.create("30"))
    assert service.orders == {}


@pytest.mark.parametrize("id_value", [
    "pay_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "2188771099347",
    "id_AB12cd34",
])
def test_provider_accepts_safe_opaque_payment_ids(id_value):
    from vainah.billing import PAYMENT_ID_RE

    assert PAYMENT_ID_RE.fullmatch(id_value)


@pytest.mark.parametrize("id_value", [
    "../pay_a1b2c3",
    "pay_abcdef?x=y",
    "pay_abcdef/anything",
    "pay_abcdef#fragment",
    "pay_%2Fabcdef",
    "pay_abcdef\\\\other",
    "a" * 129,
    "short",
])
def test_provider_rejects_unsafe_payment_ids(id_value):
    from vainah.billing import PAYMENT_ID_RE

    assert PAYMENT_ID_RE.fullmatch(id_value) is None


def test_provider_accepts_non_prefix_opaque_id_without_weakening_sandbox():
    from vainah.billing import BillingSandbox

    opaque_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def provider_response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            created = json.loads(request.content)
            return httpx.Response(200, json={
                "order_id": created["order_id"],
                "payment_id": opaque_id,
                "amount": "99.00",
                "payment_currency": "RUB",
                "test": True,
                "environment": "sandbox",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/tok_123456",
            })
        return httpx.Response(200, json={
            "order_id": order_id,
            "payment_id": opaque_id,
            "amount": "99.00",
            "payment_currency": "RUB",
            "test": True,
            "environment": "sandbox",
            "status": "paid",
        })

    service = BillingSandbox("provider", "unit-test-key",
                             httpx.MockTransport(provider_response))
    created = asyncio.run(service.create("30"))
    order_id = created["order_id"]
    assert created["mode"] == "provider"
    assert asyncio.run(service.refresh(order_id))["status"] == "paid"
    assert service.read(order_id)["vpn_delivered"] is False


def test_local_sandbox_ledger_survives_restart_and_keeps_paylinks_off_disk(tmp_path):
    db_path = str(tmp_path / "sandbox-orders.sqlite3")
    first = BillingSandbox("mock", ledger_path=db_path)
    created = asyncio.run(first.create("30"))
    assert created["status"] == "created"
    assert first.activation_preview(created["order_id"])["status"] == "blocked"

    simulated = first.simulate(created["order_id"])
    assert simulated["status"] == "paid"
    preview = first.activation_preview(created["order_id"])
    assert preview["status"] == "demo_ready"
    assert preview["duration_days"] == 30
    assert preview["device_limit"] == 3
    assert preview["h1cloud_connected"] is False
    assert preview["vpn_delivered"] is False
    assert preview["subscription_url"] is None

    after_restart = BillingSandbox("mock", ledger_path=db_path)
    restored = after_restart.read(created["order_id"])
    assert restored["status"] == "paid"
    assert restored["pay_url"] is None
    assert after_restart.list_test_orders()[0]["pay_url"] is None
    assert b"rpk_live_" not in (tmp_path / "sandbox-orders.sqlite3").read_bytes()


def test_provider_payment_status_restored_from_local_sandbox_ledger(tmp_path):
    db_path = str(tmp_path / "payment-orders.sqlite3")
    def fake_provider(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            data = json.loads(request.content)
            return httpx.Response(200, json={
                "order_id": data["order_id"],
                "payment_id": "opaque_123456",
                "amount": "1000.00",
                "payment_currency": "RUB",
                "test": True,
                "environment": "sandbox",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/abc123456",
            })
        assert request.method == "GET"
        return httpx.Response(200, json={
            "order_id": created["order_id"],
            "payment_id": "opaque_123456",
            "amount": "1000.00",
            "payment_currency": "RUB",
            "test": True,
            "environment": "sandbox",
            "status": "paid",
        })

    transport = httpx.MockTransport(fake_provider)
    first = BillingSandbox("provider", "sandbox-test-key", transport,
                           ledger_path=db_path)
    created = asyncio.run(first.create("365-family"))
    assert created["status"] == "created"
    assert created["pay_url"].startswith("https://pay.rollypay.io/")
    assert b"pay.rollypay.io" not in (
        tmp_path / "payment-orders.sqlite3"
    ).read_bytes()

    after_restart = BillingSandbox("provider", "sandbox-test-key", transport,
                                   ledger_path=db_path)
    assert after_restart.read(created["order_id"])["pay_url"] is None
    checked = asyncio.run(after_restart.refresh(created["order_id"]))
    assert checked["status"] == "paid"
    preview = after_restart.activation_preview(created["order_id"])
    assert preview["duration_days"] == 365
    assert preview["device_limit"] == 6
    assert preview["status"] == "demo_ready"
    assert preview["vpn_delivered"] is False


def test_activation_preview_protected_by_operator_token():
    r = client.get(
        "/api/shop/sandbox/vainah_test_" + "a" * 32 + "/activation-preview"
    )
    assert r.status_code == 401
    r = client.get("/api/shop/sandbox/orders")
    assert r.status_code == 401


def test_sandbox_previews_cannot_turn_canceled_payment_into_vpn():
    svc = BillingSandbox("mock")
    order = asyncio.run(svc.create("30"))
    assert svc.activation_preview(order["order_id"])["status"] == "blocked"
    assert svc.activation_preview(order["order_id"])["h1cloud_connected"] is False
    assert svc.activation_preview(order["order_id"])["vpn_delivered"] is False
