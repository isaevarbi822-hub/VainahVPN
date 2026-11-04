"""H1Cloud live write adapter tests: mock transport only, no real panel writes."""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import httpx
import pytest

from vainah.h1_live_provision import LiveH1CloudNode, LiveH1Error
from vainah.live_ledger import PendingLiveOrder
from vainah.production_contracts import h1_provision_intent

BASE = "https://vpn-panel.example.com"
TOKEN = "test-bearer-000000000000000000"
SIGNING = "test-h1-key-" + "s" * 40


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("PANEL_BASE_URL", BASE + "/api")
    monkeypatch.setenv("PANEL_API_TOKEN", TOKEN)


def context(plan_id="30"):
    intent = h1_provision_intent(
        email="subscriber@example.com",
        plan_id=plan_id,
        signing_key=SIGNING,
    )
    claim = PendingLiveOrder(
        order_id="vainah_live_" + uuid4().hex,
        owner_ref="v1_" + "a" * 64,
        plan_id=plan_id,
        amount_rub="99.00",
        payment_id="pay_mockpayment12345",
        payment_state="paid",
        delivery_state="claimed",
    )
    return claim, intent


def test_h1_writes_disabled_without_explicit_contract_approval():
    claim, intent = context()
    network = []

    def transport(request):
        network.append(request)
        return httpx.Response(500)

    with pytest.raises(LiveH1Error, match="DISABLED"):
        asyncio.run(LiveH1CloudNode(
            transport=httpx.MockTransport(transport)
        ).provision_once(claim=claim, intent=intent, operation="create"))
    assert network == []


def test_h1_create_one_write_with_verified_postcheck():
    claim, intent = context()
    network = []
    now = int(time.time())

    def transport(request):
        assert request.headers.get("Authorization") == "Bearer " + TOKEN
        network.append(request.method)
        assert request.url.host == "vpn-panel.example.com"
        if request.method == "GET":
            assert request.url.path == "/api/info"
            assert request.url.params["name"] == intent.client_name
        if request.method == "GET" and len(network) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            assert request.url.path == "/api/create"
            body = json.loads(request.content)
            assert body == intent.create_payload()
            assert body["device_limit"] == 3
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": intent.client_name,
                "expires_at": now + 30 * 86400,
                "device_limit": 3,
                "subscription_url": "https://sub.example.com/private-123",
            },
        })

    proof = asyncio.run(LiveH1CloudNode(
        transport=httpx.MockTransport(transport), write_contract_approved=True,
    ).provision_once(claim=claim, intent=intent, operation="create"))
    assert network == ["GET", "POST", "GET"]
    assert proof.name == intent.client_name
    assert proof.subscription_url == "https://sub.example.com/private-123"


def test_h1_extend_updates_family_device_limit():
    claim, intent = context("365-family")
    now = int(time.time())
    network = []

    def transport(request):
        network.append(request.method)
        if request.method == "GET":
            assert request.url.path == "/api/info"
            assert request.url.params["name"] == intent.client_name
        if request.method == "PATCH":
            assert request.url.path == "/api/edit"
            body = json.loads(request.content)
            assert body["days"] == 365
            assert body["device_limit"] == 6
            return httpx.Response(200, json={"ok": True})
        if len(network) == 1:
            return httpx.Response(200, json={
                "ok": True,
                "client": {"name": intent.client_name,
                           "expires_at": now + 1000},
            })
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": intent.client_name,
                "expires_at": now + 365 * 86400,
                "device_limit": 6,
                "subscription_url": "https://sub.example.com/family-abc",
            },
        })

    proof = asyncio.run(LiveH1CloudNode(
        transport=httpx.MockTransport(transport),
        write_contract_approved=True,
    ).provision_once(claim=claim, intent=intent, operation="extend"))
    assert network == ["GET", "PATCH", "GET"]
    assert proof.expires_at > now + 1000


def test_h1_write_timeout_is_uncertain_and_never_retried():
    claim, intent = context()
    requests = []

    def transport(request):
        requests.append(request.method)
        if request.method == "GET":
            return httpx.Response(404, json={"error": "user_not_found"})
        raise httpx.ReadTimeout("simulated lost response")

    with pytest.raises(LiveH1Error, match="UNCERTAIN"):
        asyncio.run(LiveH1CloudNode(
            transport=httpx.MockTransport(transport),
            write_contract_approved=True,
        ).provision_once(claim=claim, intent=intent, operation="create"))
    assert requests == ["GET", "POST"]


def test_h1_wrong_customer_and_no_device_limit_are_not_delivered():
    claim, intent = context()
    seen = []

    def transport(request):
        seen.append(request.method)
        if len(seen) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={
            "ok": True,
            "client": {
                "name": intent.client_name, "expires_at": int(time.time()) + 500000,
                "subscription_url": "https://sub.example.com/key",
            },
        })

    with pytest.raises(LiveH1Error, match="DEVICE_LIMIT_UNVERIFIED"):
        asyncio.run(LiveH1CloudNode(
            transport=httpx.MockTransport(transport),
            write_contract_approved=True,
        ).provision_once(claim=claim, intent=intent, operation="create"))
    assert seen == ["GET", "POST", "GET"]


def test_h1_requires_paid_claim_for_matching_plan():
    claim, intent = context("30")
    wrong_claim = PendingLiveOrder(
        order_id=claim.order_id, owner_ref=claim.owner_ref,
        plan_id="365-family", amount_rub=claim.amount_rub,
        payment_id=claim.payment_id,
        payment_state="paid", delivery_state="claimed",
    )
    with pytest.raises(LiveH1Error, match="INTENT_INVALID"):
        asyncio.run(LiveH1CloudNode(
            write_contract_approved=True,
        ).provision_once(claim=wrong_claim, intent=intent, operation="create"))
