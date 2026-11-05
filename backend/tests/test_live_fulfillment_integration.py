"""Offline RollyPay proof -> once-only H1 create/extend integration tests.

The webhook is synthetic, the ledger and HTTPS H1 API are mocked. These tests
never create RollyPay invoices, touch a real VPN node, or enable public checkout.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest

from vainah.live_fulfillment import FulfillmentError, fulfill_paid_order_once
from vainah.live_ledger import PendingLiveOrder
from vainah.production_contracts import (
    LiveContractError,
    LiveOrderContract,
    h1_provision_intent,
    verify_live_paid_event,
)

SIGNING = "test-h1-signing-only-" + "s" * 40
WEBHOOK_KEY = "synthetic-signed-event-" + "z" * 40
ORDER_ID = "vainah_live_" + "1" * 32
OWNER = "v1_" + "a" * 64
PAYMENT = "pay_mockpaid12345"
EMAIL = "subscriber@example.com"


class FakePaidLedger:
    def __init__(self, paid=True, plan_id="30"):
        self.paid = paid
        self.plan_id = plan_id
        self.claimed = False
        self.delivered = []
        self.manual = []

    def claim_delivery_once(self, order_id):
        if not self.paid or self.claimed or order_id != ORDER_ID:
            return None
        self.claimed = True
        return PendingLiveOrder(
            order_id=order_id, owner_ref=OWNER, plan_id=self.plan_id,
            amount_rub="99.00", payment_id=PAYMENT,
            payment_state="paid", delivery_state="claimed",
        )

    def claimed_verified_email(self, *, order_id, owner_ref):
        assert order_id == ORDER_ID and owner_ref == OWNER
        return EMAIL

    def mark_delivered(self, *, order_id, subscription_url, panel_confirmed):
        assert panel_confirmed is True
        self.delivered.append((order_id, subscription_url))
        return True

    def mark_uncertain(self, order_id):
        self.manual.append(order_id)
        return True


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING)
    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "fake-test-h1-bearer")
    monkeypatch.delenv("PANEL_TLS_CA_PEM", raising=False)


def _signed_paid_event():
    event = {
        "event_type": "payment.paid", "status": "paid",
        "order_id": ORDER_ID, "payment_id": PAYMENT,
        "amount": "99.00", "currency": "RUB",
    }
    raw = json.dumps(event, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        WEBHOOK_KEY.encode(), timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    contract = LiveOrderContract(ORDER_ID, "30", OWNER, PAYMENT)
    assert verify_live_paid_event(
        raw, timestamp=timestamp, signature=signature,
        signing_secret=WEBHOOK_KEY, order=contract,
    )
    return raw, timestamp, signature, contract


def test_valid_signed_paid_event_issues_exactly_once(configured):
    _signed_paid_event()
    ledger = FakePaidLedger()
    expected = h1_provision_intent(
        email=EMAIL, plan_id="30", signing_key=SIGNING,
    ).client_name
    expiry = int(time.time()) + 30 * 86400
    requests = []
    writes = []

    def provider(request):
        requests.append(request.method)
        assert request.url.host == "vpn-panel.example.com"
        assert request.headers.get("Authorization") == "Bearer fake-test-h1-bearer"
        if request.method == "GET":
            assert request.url.path == "/api/info"
            assert request.url.params.get("name") == expected
            if writes:
                return httpx.Response(200, json={
                    "ok": True, "client": {
                        "name": expected, "expires_at": expiry,
                        "device_limit": 3,
                        "subscription_url": "https://sub.example/secret-paid-link",
                    },
                })
            return httpx.Response(404, json={"error": "user_not_found"})
        assert request.method == "POST"
        assert request.url.path == "/api/create"
        assert json.loads(request.content) == {
            "name": expected, "days": 30, "device_limit": 3,
        }
        writes.append("create")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(provider)
    result = asyncio.run(fulfill_paid_order_once(
        ledger=ledger, order_id=ORDER_ID,
        verified_merchant_approved=True, write_contract_approved=True,
        transport=transport,
    ))
    assert result == {
        "status": "delivered", "vpn_delivered": True,
        "operation": "create", "expires_at": expiry,
    }
    assert writes == ["create"]
    assert requests == ["GET", "GET", "POST", "GET"]
    assert ledger.delivered == [(ORDER_ID, "https://sub.example/secret-paid-link")]
    assert ledger.manual == []
    assert "secret-paid-link" not in str(result)

    second = asyncio.run(fulfill_paid_order_once(
        ledger=ledger, order_id=ORDER_ID,
        verified_merchant_approved=True, write_contract_approved=True,
        transport=transport,
    ))
    assert second == {"status": "not_claimable", "vpn_delivered": False}
    assert writes == ["create"]
    assert requests == ["GET", "GET", "POST", "GET"]


def test_signed_event_mismatch_never_enters_paid_claim(configured):
    raw, timestamp, _signature, contract = _signed_paid_event()
    ledger = FakePaidLedger()
    with pytest.raises(LiveContractError, match="SIGNATURE"):
        verify_live_paid_event(
            raw + b" ", timestamp=timestamp, signature="0" * 64,
            signing_secret=WEBHOOK_KEY, order=contract,
        )
    assert ledger.claimed is False


def test_unpaid_and_unapproved_orders_never_contact_h1(configured):
    no_calls = httpx.MockTransport(
        lambda _request: pytest.fail("No network before verified paid claim")
    )
    unpaid = FakePaidLedger(paid=False)
    assert asyncio.run(fulfill_paid_order_once(
        ledger=unpaid, order_id=ORDER_ID,
        verified_merchant_approved=True, write_contract_approved=True,
        transport=no_calls,
    )) == {"status": "not_claimable", "vpn_delivered": False}
    assert not unpaid.claimed

    ledger = FakePaidLedger()
    for approved in (
        {"verified_merchant_approved": False, "write_contract_approved": True},
        {"verified_merchant_approved": True, "write_contract_approved": False},
    ):
        with pytest.raises(FulfillmentError, match="DISABLED"):
            asyncio.run(fulfill_paid_order_once(
                ledger=ledger, order_id=ORDER_ID,
                transport=no_calls, **approved,
            ))
    assert ledger.claimed is False


def test_h1_write_timeout_fails_closed_without_retry(configured):
    ledger = FakePaidLedger()
    requests = []

    def provider(request):
        requests.append(request.method)
        if request.method == "GET":
            return httpx.Response(404, json={"error": "user_not_found"})
        raise httpx.ReadTimeout("simulated node committed then lost response")

    with pytest.raises(FulfillmentError, match="MANUAL_REVIEW"):
        asyncio.run(fulfill_paid_order_once(
            ledger=ledger, order_id=ORDER_ID,
            verified_merchant_approved=True, write_contract_approved=True,
            transport=httpx.MockTransport(provider),
        ))
    assert requests == ["GET", "GET", "POST"]
    assert ledger.manual == [ORDER_ID]
    assert ledger.delivered == []
    assert asyncio.run(fulfill_paid_order_once(
        ledger=ledger, order_id=ORDER_ID,
        verified_merchant_approved=True, write_contract_approved=True,
        transport=httpx.MockTransport(provider),
    ))["status"] == "not_claimable"
    assert requests == ["GET", "GET", "POST"]


def test_existing_h1_client_is_extended_once(configured):
    ledger = FakePaidLedger()
    expected = h1_provision_intent(
        email=EMAIL, plan_id="30", signing_key=SIGNING,
    ).client_name
    now = int(time.time())
    old_expiry = now + 86400
    new_expiry = old_expiry + 30 * 86400
    writes = []

    def provider(request):
        assert request.url.host == "vpn-panel.example.com"
        if request.method == "PATCH":
            assert request.url.path == "/api/edit"
            assert json.loads(request.content) == {
                "name": expected, "days": 30, "device_limit": 3,
            }
            writes.append("extend")
            return httpx.Response(200, json={"ok": True})
        assert request.method == "GET"
        assert request.url.params.get("name") == expected
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": expected, "expires_at": (
                    new_expiry if writes else old_expiry
                ),
                "device_limit": 3,
                "subscription_url": "https://sub.example/private-extended",
            },
        })

    result = asyncio.run(fulfill_paid_order_once(
        ledger=ledger, order_id=ORDER_ID,
        verified_merchant_approved=True, write_contract_approved=True,
        transport=httpx.MockTransport(provider),
    ))
    assert result["operation"] == "extend"
    assert result["vpn_delivered"] is True
    assert writes == ["extend"]
    assert ledger.manual == []
