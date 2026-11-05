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
    # RollyPay may send both events for the same completed refund.
    refund_completed = {**refunded, "event_type": "refund_request.completed"}
    assert provider.process_webhook(refund_completed)["status"] == "refunded"
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


def test_provider_diagnostics_is_read_only_and_never_exposes_balance():
    seen = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        assert request.method == "GET"
        assert request.url.path == "/api/v1/balance"
        assert not request.url.params
        assert request.headers["X-API-Key"] == "unit-test-key"
        assert request.headers["X-Nonce"]
        return httpx.Response(200, json={
            "available_usdt": "12345.67", "hold_usdt": "50.00",
            "terminal_id": "merchant-private-value",
        })

    provider = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(response)
    )
    result = asyncio.run(provider.provider_diagnostics())
    assert result["connected"] is True
    assert result["request"] == "GET /api/v1/balance"
    assert result["new_payment_created"] is False
    assert "12345.67" not in str(result)
    assert "merchant-private-value" not in str(result)
    assert len(seen) == 1


def test_provider_diagnostics_rejects_unexpected_balance_schema():
    provider = BillingSandbox(
        "provider", "unit-test-key",
        httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "ok"})),
    )
    with pytest.raises(ProviderError, match="PROVIDER_RESPONSE_INVALID"):
        asyncio.run(provider.provider_diagnostics())


@pytest.mark.parametrize(("reason", "expected"), [
    ("terminal not found", "PROVIDER_TERMINAL_NOT_FOUND"),
    ("terminal_id required", "PROVIDER_TERMINAL_ID_REQUIRED"),
    ("other private vendor text", "PROVIDER_HTTP_400"),
])
def test_read_only_probe_classifies_only_known_400_reasons(reason, expected):
    def response(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(400, json={"error": reason, "private": "account_number"})

    provider = BillingSandbox("provider", "unit-test-key",
                              httpx.MockTransport(response))
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.provider_diagnostics())
    assert exc.value.code == expected
    assert "other private vendor text" not in str(exc.value)
    assert "account_number" not in str(exc.value)


def test_diagnostics_can_send_configured_terminal_uuid_without_creating_payment():
    terminal_id = "d290f1ee-6c54-4b01-90e6-d701748f0851"
    seen = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/v1/balance"
        assert request.url.params["terminal_id"] == terminal_id
        assert request.headers["X-Nonce"]
        return httpx.Response(200, json={
            "available_usdt": "0.00", "hold_usdt": "0.00",
            "terminal_id": terminal_id,
        })

    provider = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(response),
        terminal_id=terminal_id,
    )
    result = asyncio.run(provider.provider_diagnostics())
    assert result["connected"] is True
    assert terminal_id not in str(result)
    assert len(seen) == 1


def test_invalid_terminal_id_is_blocked_before_any_network_request():
    seen = []
    def response(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    provider = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(response),
        terminal_id="not-a-valid-uuid",
    )
    with pytest.raises(ProviderError, match="PROVIDER_TERMINAL_ID_INVALID"):
        asyncio.run(provider.provider_diagnostics())
    assert seen == []



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


def test_webhook_readiness_requires_operator_token():
    response = client.get("/api/shop/sandbox/webhook-readiness")
    assert response.status_code == 401


def test_webhook_readiness_reports_configuration_not_delivery(monkeypatch):
    from vainah.billing import sandbox
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", "t" * 32)
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", "s" * 32)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    response = client.get(
        "/api/shop/sandbox/webhook-readiness",
        headers={"X-Sandbox-Token": "t" * 32},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["checks"]["signing_secret_configured"] is True
    assert result["checks"]["sandbox_enabled"] is True
    assert result["checks"]["provider_test_enabled"] is (sandbox.mode == "provider" and
        __import__("os").environ.get("VAINAH_SHOP_PROVIDER_TEST_ENABLED") == "enabled")
    assert result["callback_delivery_verified"] is False
    assert result["production_checkout_enabled"] is False
    assert result["h1cloud_auto_provisioning_enabled"] is False
    assert "ROLLYPAY_SIGNING_SECRET" not in str(result)
    assert "s" * 32 not in str(result)


def test_signed_provider_webhook_receipt_survives_restart(tmp_path):
    db_path = str(tmp_path / "signed-webhook.sqlite3")
    def provider_response(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(200, json={
            "order_id": payload["order_id"],
            "payment_id": "pay_test_signed_123456",
            "amount": "99.00", "payment_currency": "RUB",
            "test": True, "environment": "sandbox", "status": "created",
            "pay_url": "https://pay.rollypay.io/pay/tok_signed_123456",
        })
    first = BillingSandbox("provider", "test-key",
                           httpx.MockTransport(provider_response),
                           ledger_path=db_path)
    order = asyncio.run(first.create("30"))
    assert order["webhook_received"] is False
    event = {
        "event_type": "payment.paid", "status": "paid", "test": True,
        "order_id": order["order_id"], "payment_id": "pay_test_signed_123456",
        "amount": "99.00", "currency": "RUB",
    }
    assert first.process_webhook(event)["vpn_delivered"] is False
    assert first.read(order["order_id"])["webhook_received"] is True
    assert first.process_webhook(event)["status"] == "paid"
    restarted = BillingSandbox("provider", "test-key", ledger_path=db_path)
    assert restarted.read(order["order_id"])["webhook_received"] is True
    assert restarted.read(order["order_id"])["vpn_delivered"] is False


def test_fake_webhook_never_marks_receipt(tmp_path):
    svc = BillingSandbox("mock", ledger_path=str(tmp_path / "fake.sqlite3"))
    order = asyncio.run(svc.create("30"))
    with pytest.raises(HTTPException):
        svc.process_webhook({
            "event_type": "payment.paid", "status": "paid", "test": True,
            "order_id": order["order_id"], "payment_id": "fake_123456",
            "amount": "99.00", "currency": "RUB",
        })
    assert svc.read(order["order_id"])["webhook_received"] is False


def test_provider_status_without_optional_sandbox_markers_requires_provenance():
    """RollyPay's documented GET example omits test/environment fields.

    The creation POST must still confirm both; polling never opens the
    signed-webhook-only VPN fulfillment gate.
    """
    payment_id = "pay_test_0123456789abcdef"
    original_order = {}

    def response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            original_order["id"] = payload["order_id"]
            assert payload["test"] is True
            return httpx.Response(201, json={
                "order_id": payload["order_id"],
                "payment_id": payment_id,
                "amount": "99.00",
                "payment_currency": "RUB",
                "test": True,
                "environment": "sandbox",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/tok_123456",
            })
        assert request.method == "GET"
        assert request.url.path.endswith("/" + payment_id)
        return httpx.Response(200, json={
            "order_id": original_order["id"],
            "payment_id": payment_id,
            "amount": "99.00",
            "payment_currency": "RUB",
            "status": "paid",
        })

    provider = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(response),
    )
    created = asyncio.run(provider.create("30"))
    assert created["status"] == "created"
    polled = asyncio.run(provider.refresh(created["order_id"]))
    assert polled["status"] == "paid"
    assert polled["webhook_received"] is False
    preview = provider.activation_preview(created["order_id"])
    assert preview["fulfillment"]["status"] == "blocked"
    assert preview["fulfillment"]["reason"] == "SIGNED_WEBHOOK_REQUIRED"
    assert preview["vpn_delivered"] is False


@pytest.mark.parametrize("overrides", [
    {"test": False},
    {"environment": "production"},
    {"test": None},
    {"environment": None},
    {"payment_id": "pay_different_0123456789"},
    {"order_id": "vainah_test_" + "f" * 32},
    {"amount": "1.00"},
    {"payment_currency": "EUR"},
])
def test_sandbox_poll_never_accepts_conflicting_markers_or_identity(overrides):
    order_ref = {}
    payment_id = "pay_test_1234567890"

    def provider_response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            created = json.loads(request.content)
            order_ref["id"] = created["order_id"]
            return httpx.Response(200, json={
                "order_id": created["order_id"],
                "payment_id": payment_id,
                "amount": "99.00",
                "payment_currency": "RUB",
                "test": True,
                "environment": "sandbox",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/tok_123456",
            })
        return httpx.Response(200, json={
            "order_id": order_ref["id"],
            "payment_id": payment_id,
            "amount": "99.00",
            "payment_currency": "RUB",
            "status": "paid",
            **overrides,
        })

    provider = BillingSandbox(
        "provider", "unit-test-key",
        httpx.MockTransport(provider_response),
    )
    created = asyncio.run(provider.create("30"))
    with pytest.raises(ProviderError) as err:
        asyncio.run(provider.refresh(created["order_id"]))
    if "test" in overrides or "environment" in overrides:
        expected = "PROVIDER_SANDBOX_NOT_CONFIRMED"
    elif "order_id" in overrides:
        expected = "PROVIDER_ORDER_MISMATCH"
    elif "payment_id" in overrides:
        expected = "PROVIDER_PAYMENT_MISMATCH"
    elif "amount" in overrides:
        expected = "PROVIDER_AMOUNT_MISMATCH"
    else:
        expected = "PROVIDER_CURRENCY_MISMATCH"
    assert err.value.code == expected
    assert provider.read(created["order_id"])["status"] == "created"


@pytest.mark.parametrize(("amount","accepted"), [
    ("99.00", True), ("99", True), ("99.0", True),
    (99, True), (99.0, True), ("099.00", True),
    ("99.01", False), ("98.99", False), ("99.001", False),
    (True, False), (None, False), ("9.9e1", False),
    ("-99.00", False), ("99,00", False), ("", False),
])
def test_rollypay_rub_amount_exact_numeric_match(amount, accepted):
    from vainah.billing import _matches_exact_rub_amount

    assert _matches_exact_rub_amount(amount, "99.00") is accepted


@pytest.mark.parametrize(("fields","accepted"), [
    ({"payment_currency": "RUB"}, True),
    ({"currency": "RUB"}, True),
    ({"currency": "RUB", "payment_currency": "RUB"}, True),
    ({}, False), ({"payment_currency": "EUR"}, False),
    ({"currency": "EUR"}, False),
    ({"currency": "RUB", "payment_currency": "EUR"}, False),
])
def test_rollypay_currency_alias_requires_explicit_rub(fields, accepted):
    from vainah.billing import _matches_rub_currency

    assert _matches_rub_currency(fields) is accepted


@pytest.mark.parametrize(("amount","currency_field"), [
    ("99", "payment_currency"),
    (99, "currency"),
    ("99.0", "currency"),
])
def test_provider_paid_status_accepts_equivalent_amount_and_currency_alias(
    amount, currency_field,
):
    """Only an original sandbox-created order can be read this way."""
    order = {}
    payment_id = "pay_test_aabbccddee112233"

    def response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            order["id"] = body["order_id"]
            return httpx.Response(200, json={
                "order_id": body["order_id"],
                "payment_id": payment_id,
                "amount": "99.00", "payment_currency": "RUB",
                "test": True, "environment": "sandbox",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/tok_123456",
            })
        return httpx.Response(200, json={
            "order_id": order["id"],
            "payment_id": payment_id,
            "amount": amount,
            currency_field: "RUB",
            "status": "paid",
        })

    provider = BillingSandbox(
        "provider", "unit-test-key", httpx.MockTransport(response),
    )
    created = asyncio.run(provider.create("30"))
    checked = asyncio.run(provider.refresh(created["order_id"]))
    assert checked["status"] == "paid"
    assert checked["webhook_received"] is False
    preview = provider.activation_preview(created["order_id"])
    assert preview["fulfillment"]["reason"] == "SIGNED_WEBHOOK_REQUIRED"
    assert preview["vpn_delivered"] is False
