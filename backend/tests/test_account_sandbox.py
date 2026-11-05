"""Sandbox delivery appears in the account without becoming a real purchase."""
from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vainah import billing, email_auth
from vainah import sandbox_auto_h1 as auto
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
KEY = "test-account-sandbox-only-" + "x" * 40
ORDER = "vainah_test_" + "a" * 32


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", KEY)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    owner = "v1_" + hmac.new(
        KEY.encode(), b"sandbox-owner-v1:email:owner@example.com",
        hashlib.sha256,
    ).hexdigest()
    orders = [{
        "order_id": ORDER, "plan": "30", "mode": "provider",
        "status": "paid", "webhook_received": True,
        "paid_webhook_received": True,
    }]
    monkeypatch.setattr(billing, "sandbox", SimpleNamespace(
        owned_test_orders=lambda principal, **_kwargs: orders if principal == owner else [],
    ))
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    reads = []

    def read(order_id, *, owner_ref):
        assert order_id == ORDER and owner_ref == owner
        reads.append(order_id)
        return {
            "status": "issued", "vpn_delivered": True,
            "subscription_url": "https://sub.example/PRIVATE_TEST_SECRET",
        }

    monkeypatch.setattr(auto, "read_delivery", read)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(
            email_auth.EMAIL_SESSION_COOKIE,
            email_auth._sign_session("owner@example.com"),
        )
        yield client, orders, reads


def test_issued_sandbox_subscription_is_visible_only_to_its_owner(account):
    client, _, reads = account
    result = client.get("/api/account/test-subscriptions")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["sandbox_only"] is True
    item = result.json()["items"][0]
    assert item["order_id"] == ORDER
    assert item["delivery_state"] == "issued"
    assert item["vpn_delivered"] is True
    assert item["device_limit"] == 3
    assert item["test_payment"] is True
    assert "PRIVATE_TEST_SECRET" not in result.text
    assert "subscription_url" not in result.text
    assert reads == [ORDER]

    client.cookies.set(
        email_auth.EMAIL_SESSION_COOKIE,
        email_auth._sign_session("other@example.com"),
    )
    assert client.get("/api/account/test-subscriptions").json()["items"] == []
    client.cookies.clear()
    anonymous = client.get("/api/account/test-subscriptions")
    assert anonymous.status_code == 401
    assert anonymous.headers["cache-control"] == "no-store"
    assert reads == [ORDER]


@pytest.mark.parametrize("update", [
    {"status": "created"}, {"status": "processing"},
    {"status": "refunded"}, {"mode": "mock"},
    {"webhook_received": False}, {"paid_webhook_received": False},
])
def test_unconfirmed_or_nonprovider_order_cannot_appear_delivered(account, update):
    client, orders, reads = account
    orders[0].update(update)
    assert client.get("/api/account/test-subscriptions").json()["items"] == []
    assert reads == []


def test_sandbox_delivery_database_error_is_redacted(account, monkeypatch):
    client, _, _ = account

    def unavailable(*_args, **_kwargs):
        raise auto.SandboxAutoH1Error("database SECRET unavailable")

    monkeypatch.setattr(auto, "read_delivery", unavailable)
    result = client.get("/api/account/test-subscriptions")
    assert result.status_code == 503
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["detail"] == "SANDBOX_VPN_ACCESS_UNAVAILABLE"
    assert "SECRET" not in result.text


def test_disabled_auto_delivery_does_not_query_database(account, monkeypatch):
    client, _, reads = account
    monkeypatch.setattr(auto, "auto_enabled", lambda: False)
    assert client.get("/api/account/test-subscriptions").json()["items"] == []
    assert reads == []
