"""Offline contracts for all ten newly activated tariffs: no real payments or writes."""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import httpx
import pytest

from vainah.billing import CATALOG, get_plan, price_rub
from vainah.h1_live_provision import LiveH1CloudNode
from vainah.live_ledger import PendingLiveOrder
from vainah.production_contracts import (
    LiveContractError,
    LiveOrderContract,
    create_hosted_live_invoice,
    h1_provision_intent,
    validate_invoice,
)
from vainah.tariff_catalog import ADDED_PLAN_IDS, public_tariff_catalog

SIGNING = "test-offline-signing-" + "s" * 40
KEY = "test-offline-key-" + "k" * 40
EXPECTED = {
    "mini-3d": (3, 3, 29),
    "sprint-5d": (5, 3, 45),
    "start-plus-21d": (21, 3, 119),
    "balance-75d": (75, 3, 289),
    "comfort-150d": (150, 3, 469),
    "max-270d": (270, 3, 749),
    "legend-730d": (730, 3, 1790),
    "family-plus-90d": (90, 6, 599),
    "family-pro-180d": (180, 6, 979),
    "family-max-730d": (730, 6, 2690),
}


def test_exact_catalog_and_no_gift_side_effects():
    from vainah.gift_cards import ALLOWED_GIFT_PLANS

    assert set(EXPECTED) == ADDED_PLAN_IDS
    assert ADDED_PLAN_IDS.isdisjoint(ALLOWED_GIFT_PLANS)
    catalog = {p["id"]: p for p in CATALOG}
    exposed = {p["id"]: p for p in public_tariff_catalog()["plans"]}
    assert len(catalog) == 75
    for plan_id, (days, devices, rub) in EXPECTED.items():
        assert (catalog[plan_id]["days"], catalog[plan_id]["devices"],
                catalog[plan_id]["kopeks"]) == (days, devices, rub * 100)
        assert exposed[plan_id]["price_rub"] == f"{rub:.2f}"
        assert exposed[plan_id]["category"] == (
            "family" if devices == 6 else "personal"
        )
        assert exposed[plan_id]["checkout_supported"] is True
        assert exposed[plan_id]["checkout_path"] == (
            "/checkout.html?plan=" + plan_id
        )


@pytest.mark.parametrize("plan_id", EXPECTED)
def test_rollypay_requires_exact_server_price_for_each_new_plan(plan_id):
    plan = get_plan(plan_id)
    assert plan is not None
    order = LiveOrderContract(
        "vainah_live_" + uuid4().hex, plan_id,
        "v1_" + "a" * 64, "pay_" + uuid4().hex,
    )
    requests = []

    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.method == "POST"
        assert request.url.host == "rollypay.io"
        assert request.headers["X-API-Key"] == KEY
        assert body["amount"] == price_rub(plan)
        assert body["payment_currency"] == "RUB"
        assert body["order_id"] == order.order_id
        return httpx.Response(200, json={
            "order_id": order.order_id, "payment_id": order.payment_id,
            "amount": price_rub(plan), "payment_currency": "RUB",
            "status": "created",
            "pay_url": "https://pay.rollypay.io/pay/safe_mock_invoice",
        })

    invoice = asyncio.run(create_hosted_live_invoice(
        order_id=order.order_id, plan_id=plan_id, api_key=KEY,
        order_durably_reserved=True, verified_merchant_approved=True,
        verified_h1_fulfillment=True,
        transport=httpx.MockTransport(provider),
    ))
    assert invoice.amount_rub == price_rub(plan)
    assert len(requests) == 1
    with pytest.raises(LiveContractError, match="MISMATCH"):
        validate_invoice({
            "order_id": order.order_id, "payment_id": order.payment_id,
            "amount": f"{(plan['kopeks'] - 100) / 100:.2f}",
            "payment_currency": "RUB", "status": "created",
            "pay_url": "https://pay.rollypay.io/pay/safe_mock_invoice",
        }, order_id=order.order_id, plan_id=plan_id)


@pytest.mark.parametrize("plan_id", EXPECTED)
@pytest.mark.parametrize("operation", ("create", "extend"))
def test_h1cloud_exact_days_devices_and_postcheck_for_new_plans(
    monkeypatch, plan_id, operation,
):
    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-panel-key-" + "p" * 32)
    days, devices, rub = EXPECTED[plan_id]
    intent = h1_provision_intent(
        email="subscriber@example.com", plan_id=plan_id, signing_key=SIGNING,
    )
    assert intent.create_payload()["days"] == days
    assert intent.create_payload()["device_limit"] == devices
    assert intent.extend_payload()["days"] == days
    assert intent.extend_payload()["device_limit"] == devices

    claim = PendingLiveOrder(
        order_id="vainah_live_" + uuid4().hex,
        owner_ref="v1_" + "b" * 64,
        plan_id=plan_id, amount_rub=f"{rub:.2f}",
        payment_id="pay_mockpayment12345",
        payment_state="paid", delivery_state="claimed",
    )
    now = int(time.time())
    old_expiry = now + 1000 if operation == "extend" else 0
    methods = []

    def provider(request):
        methods.append(request.method)
        assert request.url.host == "vpn-panel.example.com"
        assert request.headers["Authorization"].startswith("Bearer ")
        if len(methods) == 1:
            assert request.method == "GET"
            if operation == "create":
                return httpx.Response(404, json={"error": "user_not_found"})
            return httpx.Response(200, json={"ok": True, "client": {
                "name": intent.client_name, "expires_at": old_expiry,
            }})
        if len(methods) == 2:
            expected_method = "POST" if operation == "create" else "PATCH"
            assert request.method == expected_method
            assert json.loads(request.content) == (
                intent.create_payload() if operation == "create"
                else intent.extend_payload()
            )
            return httpx.Response(200, json={"ok": True})
        assert request.method == "GET"
        return httpx.Response(200, json={"ok": True, "client": {
            "name": intent.client_name,
            "expires_at": max(now, old_expiry) + days * 86400 + 600,
            "device_limit": devices,
            "subscription_url": "https://sub.example.com/private_test_url",
        }})

    proof = asyncio.run(LiveH1CloudNode(
        transport=httpx.MockTransport(provider),
        write_contract_approved=True,
    ).provision_once(claim=claim, intent=intent, operation=operation))
    assert methods == ["GET", "POST" if operation == "create" else "PATCH", "GET"]
    assert proof.name == intent.client_name
    assert proof.expires_at >= max(now, old_expiry) + days * 86400


@pytest.mark.parametrize("plan_id", EXPECTED)
def test_h1_writes_stay_locked_without_paid_claim(plan_id):
    intent = h1_provision_intent(
        email="subscriber@example.com", plan_id=plan_id, signing_key=SIGNING,
    )
    claim = PendingLiveOrder(
        order_id="vainah_live_" + uuid4().hex,
        owner_ref="v1_" + "b" * 64,
        plan_id=plan_id, amount_rub=f"{EXPECTED[plan_id][2]:.2f}",
        payment_id="pay_mockpayment12345",
        payment_state="created", delivery_state="claimed",
    )
    seen = []

    def provider(request):
        seen.append(request)
        return httpx.Response(500)

    from vainah.h1_live_provision import LiveH1Error

    with pytest.raises(LiveH1Error, match="DISABLED"):
        asyncio.run(LiveH1CloudNode(
            transport=httpx.MockTransport(provider),
            write_contract_approved=True,
        ).provision_once(claim=claim, intent=intent, operation="create"))
    assert not seen
