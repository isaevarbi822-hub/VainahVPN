"""Subscription display regression: paid, linked email and manual grants."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from vainah import customer_portal as portal
from vainah import manual_grants
from vainah.main import app


def _order(plan="30-family"):
    return {
        "order_id": "v_ord_1234567890abcdef",
        "plan_id": plan,
        "paid": True,
        "delivered": True,
        "status": "delivered",
        "created_at": "2026-11-18T12:00:00Z",
    }


@pytest.fixture
def email_client(monkeypatch):
    monkeypatch.setattr(
        portal, "portal_identity",
        lambda _request, include_email=True: (None, "owner@example.com", "email"),
    )
    monkeypatch.setattr(portal, "live_paid_email_orders", lambda _email: [])
    async def no_profile(_email):
        return {"status": "not_found", "message": "No profile"}
    async def no_grant(_email, *, include_secret=False):
        return {"available": False}
    monkeypatch.setattr(portal, "h1_email_customer_state", no_profile)
    monkeypatch.setattr(manual_grants, "manual_grant_summary_for_email", no_grant)
    with TestClient(app) as client:
        yield client


def test_manual_grant_populates_primary_subscription_without_payment(email_client, monkeypatch):
    async def grant(email, *, include_secret=False):
        assert email == "owner@example.com"
        assert include_secret is False
        return {
            "available": True, "days": 30, "devices": 2,
            "gifted": True, "paid": False, "expires_at": "2026-12-18T00:00:00Z",
            "traffic": {"used_bytes": 300, "limit_bytes": 1000},
        }
    monkeypatch.setattr(manual_grants, "manual_grant_summary_for_email", grant)
    response = email_client.get("/api/account/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["orders"] == []
    assert data["subscription"]["status"] == "issued"
    assert data["subscription"]["gifted"] is True
    assert data["subscription"]["paid"] is False
    assert data["subscription"]["device_limit"] == 2
    assert data["subscription"]["traffic"]["limit_bytes"] == 1000
    assert "subscription_url" not in str(data)


def test_paid_order_shows_plan_and_devices_even_when_h1_is_unavailable(
    email_client, monkeypatch,
):
    monkeypatch.setattr(portal, "live_paid_email_orders", lambda _email: [_order()])
    response = email_client.get("/api/account/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["subscription"]["paid"] is True
    assert data["subscription"]["status"] == "verification_pending"
    assert data["subscription"]["device_limit"] == 6
    assert data["subscription"]["plan_title"] == "Семейный месяц"
    assert data["subscription"]["expires_at"] is None
    assert data["orders"][0]["delivered"] is True


def test_paid_verified_subscription_precedes_manual_gift(email_client, monkeypatch):
    monkeypatch.setattr(portal, "live_paid_email_orders", lambda _email: [_order()])
    async def active(_email):
        return {
            "status": "active", "message": "Active",
            "expires_at": "2026-12-18T00:00:00Z",
            "traffic": {"used_bytes": 100},
        }
    async def grant(_email, *, include_secret=False):
        return {"available": True, "days": 7, "devices": 1,
                "expires_at": "2026-11-25T00:00:00Z"}
    monkeypatch.setattr(portal, "h1_email_customer_state", active)
    monkeypatch.setattr(manual_grants, "manual_grant_summary_for_email", grant)
    data = email_client.get("/api/account/overview").json()
    assert data["subscription"]["status"] == "delivered"
    assert data["subscription"]["paid"] is True
    assert data["subscription"]["device_limit"] == 6
    assert data["manual_grant"]["available"] is True


def test_paid_history_survives_manual_provider_outage(email_client, monkeypatch):
    monkeypatch.setattr(portal, "live_paid_email_orders", lambda _email: [_order()])
    async def outage(_email, *, include_secret=False):
        from fastapi import HTTPException
        raise HTTPException(503, "MANUAL_GRANT_ACCESS_UNAVAILABLE")
    monkeypatch.setattr(manual_grants, "manual_grant_summary_for_email", outage)
    data = email_client.get("/api/account/overview").json()
    assert len(data["orders"]) == 1
    assert data["manual_grant"]["status"] == "unavailable"
    assert data["subscription"]["status"] == "verification_pending"


def test_email_identity_is_prioritized_over_unrelated_telegram_cookie(monkeypatch):
    monkeypatch.setattr(portal, "current_email", lambda _request: "owner@example.com")
    monkeypatch.setattr(portal, "current_user", lambda _request: {
        "telegram_id": "999999999",
    })
    monkeypatch.setattr(portal, "telegram_id_for_verified_email",
                        lambda _email: "111111111")
    identity = portal.portal_identity(object())
    assert identity == ("111111111", "owner@example.com", "email")


def test_signed_email_can_see_both_paid_and_legacy_history(email_client, monkeypatch):
    monkeypatch.setattr(
        portal, "portal_identity",
        lambda _request, include_email=True: ("111111111", "owner@example.com", "email"),
    )
    monkeypatch.setattr(portal, "live_paid_email_orders", lambda _email: [_order("30")])
    monkeypatch.setattr(portal, "customer_receipts", lambda _telegram: [
        {"order_id": "legacy123456789", "plan_id": "365",
         "paid": True, "delivered": True, "status": "delivered",
         "created_at": "2026-11-01T00:00:00Z"}
    ])
    async def email_state(_email):
        return {"status": "active", "message": "Active",
                "expires_at": "2026-12-18T00:00:00Z"}
    monkeypatch.setattr(portal, "h1_email_customer_state", email_state)
    data = email_client.get("/api/account/overview").json()
    assert len(data["orders"]) == 2
    assert data["subscription"]["plan_title"] == "1 месяц"
    assert data["subscription"]["paid"] is True
