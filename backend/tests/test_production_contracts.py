"""Production-contract tests. All HTTP traffic is mocked; no money is taken."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from vainah.main import app
from vainah.production_contracts import (
    LiveContractError,
    LiveOrderContract,
    create_hosted_live_invoice,
    h1_provision_intent,
    production_readiness,
    validate_invoice,
    verify_live_paid_event,
    verify_live_reversal_event,
)

KEY = "test-api-key-" + "k" * 35
SIGNING = "test-signing-key-" + "s" * 40
OWNER = "v1_" + "a" * 64


def new_order(plan_id: str = "30") -> LiveOrderContract:
    return LiveOrderContract("vainah_live_" + uuid4().hex, plan_id, OWNER, "pay_" + uuid4().hex)


def invoice(order: LiveOrderContract) -> dict:
    return {
        "order_id": order.order_id,
        "payment_id": order.payment_id,
        "amount": order.amount_rub,
        "payment_currency": "RUB",
        "status": "created",
        "pay_url": "https://pay.rollypay.io/pay/tok_" + uuid4().hex,
    }


def signed_event(order: LiveOrderContract, changes=None):
    payload = {
        "event_type": "payment.paid",
        "order_id": order.order_id,
        "payment_id": order.payment_id,
        "status": "paid",
        "amount": order.amount_rub,
        "currency": "RUB",
    }
    payload.update(changes or {})
    raw = json.dumps(payload).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SIGNING.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return raw, timestamp, signature


def test_live_gateway_cannot_charge_without_all_merchant_and_delivery_preconditions():
    order = new_order()
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(LiveContractError, match="PREREQUISITES_MISSING"):
        asyncio.run(create_hosted_live_invoice(
            order_id=order.order_id, plan_id=order.plan_id, api_key=KEY,
            transport=httpx.MockTransport(provider),
        ))
    assert calls == []


def test_live_gateway_uses_catalog_amount_and_hosted_payment_page():
    order = new_order("365-family")
    observed = []

    def provider(request):
        payload = json.loads(request.content)
        observed.append(payload)
        assert request.method == "POST"
        assert request.url.host == "rollypay.io"
        assert request.headers["X-API-Key"] == KEY
        assert request.headers.get("X-Nonce")
        assert payload["amount"] == "1000.00"
        assert payload["payment_currency"] == "RUB"
        assert "test" not in payload
        return httpx.Response(200, json=invoice(order))

    result = asyncio.run(create_hosted_live_invoice(
        order_id=order.order_id, plan_id=order.plan_id, api_key=KEY,
        order_durably_reserved=True,
        verified_merchant_approved=True,
        verified_h1_fulfillment=True,
        transport=httpx.MockTransport(provider),
    ))
    assert result.order_id == order.order_id
    assert result.amount_rub == "1000.00"
    assert result.pay_url.startswith("https://pay.rollypay.io/pay/")
    assert len(observed) == 1


@pytest.mark.parametrize("changes", [
    {"amount": "1.00"},
    {"payment_currency": "EUR"},
    {"test": True},
    {"test": "true"},
    {"environment": "sandbox"},
    {"order_id": "wrong"},
    {"pay_url": "https://evil.example/pay/token"},
])
def test_live_invoice_rejects_incorrect_response(changes):
    order = new_order()
    response = invoice(order)
    response.update(changes)
    with pytest.raises(LiveContractError):
        validate_invoice(response, order_id=order.order_id, plan_id=order.plan_id)


def test_signed_live_paid_event_requires_exact_saved_order():
    order = new_order("90")
    raw, timestamp, signature = signed_event(order)
    assert verify_live_paid_event(
        raw, timestamp=timestamp, signature=signature,
        signing_secret=SIGNING, order=order,
    )


@pytest.mark.parametrize("changes", [
    {"amount": "1.00"},
    {"currency": "EUR"},
    {"payment_id": "pay_different"},
    {"order_id": "vainah_live_wrong"},
    {"event_type": "payment.refunded", "status": "refunded"},
    {"status": "created"},
    {"test": True},
    {"test": "true"},
    {"environment": "sandbox"},
])
def test_live_paid_event_rejects_wrong_order_and_sandbox(changes):
    order = new_order()
    raw, timestamp, signature = signed_event(order, changes)
    with pytest.raises(LiveContractError):
        verify_live_paid_event(
            raw, timestamp=timestamp, signature=signature,
            signing_secret=SIGNING, order=order,
        )


def test_live_paid_event_fails_closed_on_modified_or_expired_signature():
    order = new_order()
    raw, timestamp, signature = signed_event(order)
    with pytest.raises(LiveContractError, match="SIGNATURE"):
        verify_live_paid_event(
            raw + b" ", timestamp=timestamp, signature=signature,
            signing_secret=SIGNING, order=order,
        )
    with pytest.raises(LiveContractError, match="SIGNATURE"):
        verify_live_paid_event(
            raw, timestamp=timestamp, signature=signature,
            signing_secret=SIGNING, order=order,
            now=int(timestamp) + 310,
        )


@pytest.mark.parametrize("changes", [
    {"test": 0}, {"test": None}, {"environment": []},
    {"environment": {"mode": "production"}}, {"environment": " Sandbox "},
    {"currency": "USD", "payment_currency": "RUB"},
    {"amount": "9.9e1"}, {"status": []},
])
def test_live_contracts_reject_contradictory_or_malformed_fields(changes):
    order = new_order()
    with pytest.raises(LiveContractError):
        validate_invoice(invoice(order) | changes, order_id=order.order_id, plan_id=order.plan_id)
    raw, timestamp, signature = signed_event(order, changes)
    with pytest.raises(LiveContractError):
        verify_live_paid_event(
            raw, timestamp=timestamp, signature=signature,
            signing_secret=SIGNING, order=order,
        )
    raw, timestamp, signature = signed_event(order, {
        "event_type": "payment.refunded", "status": "refunded", **changes,
    })
    with pytest.raises(LiveContractError):
        verify_live_reversal_event(
            raw, timestamp=timestamp, signature=signature,
            signing_secret=SIGNING, order=order,
        )


def test_live_reversal_rejects_unhashable_event_without_typeerror():
    order = new_order()
    raw, timestamp, signature = signed_event(order, {"event_type": []})
    with pytest.raises(LiveContractError, match="MISMATCH"):
        verify_live_reversal_event(
            raw, timestamp=timestamp, signature=signature,
            signing_secret=SIGNING, order=order,
        )


def test_deep_live_json_fails_with_sanitized_contract_error():
    order = new_order()
    raw = b"[" * 10000 + b"0" + b"]" * 10000
    timestamp = str(int(time.time()))
    signature = hmac.new(SIGNING.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    for verifier in (verify_live_paid_event, verify_live_reversal_event):
        with pytest.raises(LiveContractError, match="LIVE_WEBHOOK_JSON_INVALID"):
            verifier(raw, timestamp=timestamp, signature=signature, signing_secret=SIGNING, order=order)

    with pytest.raises(LiveContractError, match="LIVE_PAYMENT_RESPONSE_INVALID"):
        asyncio.run(create_hosted_live_invoice(
            order_id=order.order_id, plan_id=order.plan_id, api_key=KEY,
            order_durably_reserved=True, verified_merchant_approved=True,
            verified_h1_fulfillment=True,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw)),
        ))


def test_h1_provisioning_intent_is_stable_private_and_plan_bound():
    first = h1_provision_intent(
        email="Owner@example.com", plan_id="30", signing_key=SIGNING,
    )
    other_plan = h1_provision_intent(
        email="owner@example.com", plan_id="365-family", signing_key=SIGNING,
    )
    different = h1_provision_intent(
        email="other@example.com", plan_id="30", signing_key=SIGNING,
    )
    assert first.client_name == other_plan.client_name
    assert first.client_name != different.client_name
    assert "owner" not in first.client_name
    assert first.create_payload() == {
        "name": first.client_name, "days": 30, "device_limit": 3,
    }
    assert other_plan.create_payload()["device_limit"] == 6
    assert other_plan.extend_payload()["days"] == 365


def test_production_readiness_never_claims_live_checkout(monkeypatch):
    for name in ("ROLLYPAY_API_KEY", "ROLLYPAY_SIGNING_SECRET",
                 "PANEL_BASE_URL", "PANEL_API_TOKEN"):
        monkeypatch.setenv(name, "present-secret-only-not-confirmed")
    result = production_readiness()
    assert result["real_checkout_enabled"] is False
    assert result["real_money_can_be_charged"] is False
    assert result["auto_vpn_delivery_enabled"] is False
    assert result["checks"]["live_order_ledger_implemented"] is True
    assert result["checks"]["h1cloud_write_contract_verified"] is False
    with TestClient(app) as client:
        response = client.post("/api/shop/checkout", json={"plan": "30"})
        assert response.status_code == 503


def test_operator_readiness_reports_unset_approvals_without_secrets(monkeypatch):
    from vainah import live_checkout

    for name in (
        "VAINAH_MERCHANT_APPROVED",
        "VAINAH_H1_WRITE_CONTRACT_APPROVED",
        "VAINAH_LIVE_FULFILLMENT_APPROVED",
        "VAINAH_LIVE_PAID_E2E_VERIFIED",
        "VAINAH_LIVE_CUSTOMER_ACCESS_ENABLED",
        "VAINAH_LIVE_CHECKOUT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    report = production_readiness()
    assert report["real_checkout_enabled"] is False
    assert report["real_money_can_be_charged"] is False
    assert report["auto_vpn_delivery_enabled"] is False
    assert live_checkout.live_ready() is False
    assert len(report["operator_approval_flags"]) == 6
    assert len(report["missing_operator_approval_flags"]) == 6
    assert all(not flag for flag in report["operator_approval_flags"].values())
    assert report["operator_approval_flags_are_attestations_only"] is True
    assert "SESSION_SIGNING_KEY" not in str(report)

    monkeypatch.setenv("VAINAH_MERCHANT_APPROVED", "approved")
    report = production_readiness()
    assert report["operator_approval_flags"]["merchant_approved_flag"] is True
    assert "merchant_approved_flag" not in report["missing_operator_approval_flags"]
    assert report["real_checkout_enabled"] is False
    assert report["checks"]["merchant_authorized_to_take_payments"] is False


def test_readiness_mirrors_actual_runtime_checkout_gate(monkeypatch):
    from vainah import live_checkout

    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    report = production_readiness()
    assert report["real_checkout_enabled"] is True
    assert report["real_money_can_be_charged"] is True
    assert report["auto_vpn_delivery_enabled"] is True
    # A configured gate is not independently verified by this report.
    assert report["operator_approval_flags_are_attestations_only"] is True


def test_operator_readiness_is_private_and_never_enables_charge(monkeypatch):
    token = "test-operator-readiness-" + "u" * 40
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", token)
    with TestClient(app) as client:
        assert client.get("/api/shop/operator/production-readiness").status_code == 401
        resp = client.get(
            "/api/shop/operator/production-readiness",
            headers={"X-Sandbox-Token": token},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["real_checkout_enabled"] is False
    assert data["auto_vpn_delivery_enabled"] is False
    assert "checks" in data
    assert token not in str(data)


def test_operator_h1_readiness_tracks_verified_https_only(monkeypatch):
    from vainah import h1_panel

    token = "operator-test-token-" + "x" * 32
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", token)
    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-panel-token")
    seen = []

    async def fake_inspect():
        seen.append("read_only")
        return {
            "ok": True, "panel": "reachable",
            "authentication": "accepted", "vpn_delivered": False,
        }

    monkeypatch.setattr(h1_panel, "inspect_h1_panel", fake_inspect)
    with TestClient(app) as client:
        no_token = client.get("/api/shop/operator/production-readiness")
        assert no_token.status_code == 401
        assert seen == []

        verified = client.get(
            "/api/shop/operator/production-readiness",
            headers={"X-Sandbox-Token": token},
        )
    assert verified.status_code == 200
    body = verified.json()
    assert seen == ["read_only"]
    assert body["checks"]["h1cloud_tls_reachable_and_authorized"] is True
    assert body["checks"]["h1cloud_write_contract_verified"] is False
    assert body["real_checkout_enabled"] is False
    assert body["real_money_can_be_charged"] is False
    assert body["auto_vpn_delivery_enabled"] is False
    assert token not in str(body)


def test_operator_readiness_bad_h1_response_does_not_enable_payments(monkeypatch):
    from vainah import h1_panel

    token = "operator-test-token-" + "x" * 32
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", token)
    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-panel-token")

    async def fake_inspect():
        return {"ok": False, "authentication": "rejected"}

    monkeypatch.setattr(h1_panel, "inspect_h1_panel", fake_inspect)
    with TestClient(app) as client:
        response = client.get(
            "/api/shop/operator/production-readiness",
            headers={"X-Sandbox-Token": token},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["h1cloud_tls_reachable_and_authorized"] is False
    assert body["real_checkout_enabled"] is False
    assert body["auto_vpn_delivery_enabled"] is False
