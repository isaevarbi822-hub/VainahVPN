"""Fail-closed contracts for every additional paid tariff (no live charges)."""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import httpx
import pytest

from vainah.billing import CATALOG, get_plan, price_rub
from vainah.expanded_tariffs import EXTRA_CATALOG, EXTRA_PLAN_IDS
from vainah.gift_cards import ALLOWED_GIFT_PLANS
from vainah.h1_live_provision import LiveH1CloudNode, LiveH1Error
from vainah.live_ledger import PendingLiveOrder
from vainah.production_contracts import (
    LiveContractError,
    LiveOrderContract,
    create_hosted_live_invoice,
    h1_provision_intent,
    validate_invoice,
)
from vainah.tariff_catalog import public_tariff_catalog

SIGNING = "superplus50-test-" + "s" * 50
KEY = "superplus50-test-" + "k" * 50


def test_full_fifty_plan_catalog_is_a_single_authoritative_source():
    assert len(EXTRA_CATALOG) == 29
    assert len(CATALOG) == 50
    assert len({p["id"] for p in CATALOG}) == 50
    assert len({(p["days"], p["devices"]) for p in CATALOG}) == 50
    assert EXTRA_PLAN_IDS.isdisjoint(ALLOWED_GIFT_PLANS)
    data = public_tariff_catalog()
    assert len(data["plans"]) == data["total"] == 51
    assert data["existing_paid_count"] == 50
    assert data["trial_count"] == 1
    for plan in CATALOG:
        assert plan["kopeks"] > 0 and plan["kopeks"] % 100 == 0
        assert 2 <= plan["days"] <= 730
        assert plan["devices"] in (3, 6)
        exposed = next(p for p in data["plans"] if p["id"] == plan["id"])
        assert exposed["price_rub"] == price_rub(plan)
        assert exposed["checkout_path"] == "/checkout.html?plan=" + plan["id"]
        assert exposed["checkout_supported"] is True


@pytest.mark.parametrize("plan_id", sorted(EXTRA_PLAN_IDS))
def test_each_new_rollypay_invoice_uses_exact_server_price(plan_id):
    plan = get_plan(plan_id)
    assert plan is not None
    order = LiveOrderContract(
        "vainah_live_" + uuid4().hex, plan_id,
        "v1_" + "a" * 64, "pay_" + uuid4().hex,
    )
    called = []

    def provider(request):
        called.append(request)
        body = json.loads(request.content)
        assert request.method == "POST"
        assert request.url.host == "rollypay.io"
        assert request.headers["X-API-Key"] == KEY
        assert body["order_id"] == order.order_id
        assert body["amount"] == price_rub(plan)
        assert body["payment_currency"] == "RUB"
        return httpx.Response(200, json={
            "order_id": order.order_id,
            "payment_id": order.payment_id,
            "amount": price_rub(plan),
            "payment_currency": "RUB",
            "status": "created",
            "pay_url": "https://pay.rollypay.io/pay/ultra_test_payment",
        })

    result = asyncio.run(create_hosted_live_invoice(
        order_id=order.order_id, plan_id=plan_id, api_key=KEY,
        order_durably_reserved=True, verified_merchant_approved=True,
        verified_h1_fulfillment=True,
        transport=httpx.MockTransport(provider),
    ))
    assert len(called) == 1
    assert result.amount_rub == price_rub(plan)
    with pytest.raises(LiveContractError, match="MISMATCH"):
        validate_invoice({
            "order_id": order.order_id,
            "payment_id": order.payment_id,
            "amount": f"{(plan['kopeks'] - 100) / 100:.2f}",
            "payment_currency": "RUB", "status": "created",
            "pay_url": "https://pay.rollypay.io/pay/ultra_test_payment",
        }, order_id=order.order_id, plan_id=plan_id)


@pytest.mark.parametrize("plan_id", sorted(EXTRA_PLAN_IDS))
@pytest.mark.parametrize("operation", ("create", "extend"))
def test_each_new_h1_write_and_verification_is_exact(monkeypatch, plan_id, operation):
    monkeypatch.setenv("PANEL_BASE_URL", "https://panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-panel-" + "t" * 40)
    plan = get_plan(plan_id)
    assert plan is not None
    intent = h1_provision_intent(
        email="customer@example.com", plan_id=plan_id, signing_key=SIGNING,
    )
    assert intent.create_payload()["days"] == plan["days"]
    assert intent.create_payload()["device_limit"] == plan["devices"]
    assert intent.extend_payload()["days"] == plan["days"]
    claim = PendingLiveOrder(
        order_id="vainah_live_" + uuid4().hex,
        owner_ref="v1_" + "b" * 64,
        plan_id=plan_id, amount_rub=price_rub(plan),
        payment_id="pay_mockpayment12345",
        payment_state="paid", delivery_state="claimed",
    )
    now = int(time.time())
    old_expiry = now + 1000 if operation == "extend" else 0
    seen = []

    def provider(request):
        seen.append(request.method)
        if len(seen) == 1:
            assert request.method == "GET"
            if operation == "create":
                return httpx.Response(404, json={"error": "not_found"})
            return httpx.Response(200, json={"ok": True, "client": {
                "name": intent.client_name, "expires_at": old_expiry,
            }})
        if len(seen) == 2:
            assert request.method == ("POST" if operation == "create" else "PATCH")
            assert json.loads(request.content) == (
                intent.create_payload() if operation == "create"
                else intent.extend_payload()
            )
            return httpx.Response(200, json={"ok": True})
        assert request.method == "GET"
        return httpx.Response(200, json={"ok": True, "client": {
            "name": intent.client_name,
            "expires_at": max(now, old_expiry) + intent.days * 86400 + 600,
            "device_limit": intent.devices,
            "subscription_url": "https://sub.example.com/private_key",
        }})

    proof = asyncio.run(LiveH1CloudNode(
        transport=httpx.MockTransport(provider),
        write_contract_approved=True,
    ).provision_once(claim=claim, intent=intent, operation=operation))
    assert seen == ["GET", "POST" if operation == "create" else "PATCH", "GET"]
    assert proof.expires_at >= max(now, old_expiry) + intent.days * 86400


@pytest.mark.parametrize("plan_id", sorted(EXTRA_PLAN_IDS))
def test_no_new_h1_account_without_verified_payment(plan_id):
    plan = get_plan(plan_id)
    intent = h1_provision_intent(
        email="customer@example.com", plan_id=plan_id, signing_key=SIGNING,
    )
    claim = PendingLiveOrder(
        order_id="vainah_live_" + uuid4().hex,
        owner_ref="v1_" + "b" * 64,
        plan_id=plan_id, amount_rub=price_rub(plan),
        payment_id="pay_mockpayment12345",
        payment_state="created", delivery_state="claimed",
    )
    requests = []
    def provider(request):
        requests.append(request)
        return httpx.Response(500)

    with pytest.raises(LiveH1Error, match="DISABLED"):
        asyncio.run(LiveH1CloudNode(
            transport=httpx.MockTransport(provider),
            write_contract_approved=True,
        ).provision_once(claim=claim, intent=intent, operation="create"))
    assert not requests
