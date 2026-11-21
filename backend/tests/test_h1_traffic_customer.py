"""Traffic counters must be provider-verified, private and never fabricated."""
from __future__ import annotations

import asyncio

from vainah import customer_portal
from vainah.h1_panel import parse_client_status, verified_traffic_usage


def test_traffic_quota_and_usage_are_strict_integer_bytes():
    record = {
        "expires_at": 2000000000, "status": "active",
        "traffic_used_bytes": 1024**3, "traffic_limit_bytes": 10 * 1024**3,
        "subscription_url": "https://secret.example/private",
        "uuid": "secret-uuid",
    }
    state = parse_client_status(record, now=1700000000)
    assert state["traffic"] == {
        "used_bytes": 1024**3, "limit_bytes": 10 * 1024**3,
    }
    assert "secret" not in str(state)
    assert "subscription_url" not in str(state)


def test_missing_or_ambiguous_usage_is_not_zero():
    assert verified_traffic_usage({}) == {
        "used_bytes": None, "limit_bytes": None,
    }
    assert verified_traffic_usage({
        "traffic_used_bytes": "100", "traffic_limit_bytes": 0,
    }) == {"used_bytes": None, "limit_bytes": None}
    assert verified_traffic_usage({
        "traffic_used_bytes": True, "traffic_limit_bytes": -1,
    }) == {"used_bytes": None, "limit_bytes": None}
    assert verified_traffic_usage({
        "traffic_used_bytes": 512,
        "traffic_limit_bytes": 10 * 1024**3,
        "devices": ["SECRET_DEVICE"],
    }) == {"used_bytes": 512, "limit_bytes": 10 * 1024**3}


def test_email_profile_traffic_is_read_only_and_no_access_without_purchase(monkeypatch):
    secret = "traffic-test-secret-" + "x" * 40
    monkeypatch.setenv("SESSION_SIGNING_KEY", secret)

    async def fake_provider(_name):
        return {
            "panel_ready": True, "found": True, "active": True,
            "expires_at": "2030-01-01T00:00:00+00:00",
            "traffic": {"used_bytes": 1024, "limit_bytes": 4096},
            "subscription_url": "https://secret.example/NEVER_LEAK",
        }

    monkeypatch.setattr(
        customer_portal, "read_h1_issued_client_status", fake_provider,
    )
    state = asyncio.run(customer_portal.h1_email_customer_state("owner@example.com"))
    assert state["traffic"] == {"used_bytes": 1024, "limit_bytes": 4096}
    assert "NEVER_LEAK" not in str(state)
