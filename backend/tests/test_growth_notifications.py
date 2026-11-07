"""Privacy and integrity contract for Vainah growth and customer alerts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from vainah import account_feed, email_auth, growth
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "test_growth_signing_key_long_enough_456789abcdef"
SITE = Path(__file__).resolve().parents[2] / "storefront"


def customer(email=None):
    client = TestClient(app, base_url=ORIGIN)
    if email:
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE, email_auth._sign_session(email))
    return client


def test_anonymous_users_cannot_access_growth_or_alerts(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    with customer() as guest:
        assert guest.get("/api/account/growth").status_code == 401
        assert guest.get("/api/account/notifications").status_code == 401
        assert guest.post("/api/account/growth/gifts/drafts",
                          headers={"Origin": ORIGIN},
                          json={"plan_id": "30"}).status_code == 401


def test_referral_code_is_stable_secret_derived_and_unrelated_to_email(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    left = growth._code("alice@example.com")
    right = growth._code("bob@example.com")
    assert left == growth._code("alice@example.com")
    assert left != right
    assert growth.CODE_PATTERN.fullmatch(left)
    assert "alice" not in left and "example" not in left
    assert growth._owner("alice@example.com") != growth._owner("bob@example.com")
    assert len(growth._owner("alice@example.com")) == 64


def test_referral_requires_origin_valid_code_and_verified_owner(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    calls = []
    monkeypatch.setattr(growth, "_claim", lambda email, code: calls.append((email, code)))
    code = growth._code("inviter@example.com")
    with customer("invitee@example.com") as client:
        url = "/api/account/growth/referrals/claim"
        assert client.post(url, json={"code": code}).status_code == 403
        assert client.post(url, headers={"Origin": ORIGIN},
                           json={"code": "bad"}).status_code == 422
        result = client.post(url, headers={"Origin": ORIGIN},
                             json={"code": code})
        assert result.status_code == 201
        assert result.json() == {"linked": True, "reward_issued": False}
    assert calls == [("invitee@example.com", code)]


def test_gift_draft_does_not_charge_or_issuance(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    calls = []
    def fake_save(email, plan):
        calls.append((email, plan))
        return {"status": "draft_unpaid", "checkout_available": False,
                "redeemable": False}
    monkeypatch.setattr(growth, "_save_draft", fake_save)
    with customer("alice@example.com") as client:
        result = client.post("/api/account/growth/gifts/drafts",
                             headers={"Origin": ORIGIN},
                             json={"plan_id": "365"})
        assert result.status_code == 201
        assert result.json()["redeemable"] is False
    assert calls == [("alice@example.com", "365")]


def test_notifications_only_from_confirmed_data(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    owner = growth._owner("alice@example.com")
    expires = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    data = {
        "orders": [{"paid": True, "delivered": True}],
        "subscription": {
            "paid": True, "status": "delivered",
            "expires_at": expires,
            "traffic": {"used_bytes": 900, "limit_bytes": 1000},
            "order_id": "real-order-private-key",
            "subscription_url": "vless://never-show",
        },
        "h1cloud": {"status": "active"},
    }
    items = account_feed._notifications(owner, data)
    assert len(items) == 2
    assert {x["type"] for x in items} == {"traffic", "expiry"}
    assert all(len(item["id"]) == 64 for item in items)
    assert "vless://" not in str(items)
    assert "real-order-private-key" not in str(items)
    empty = account_feed._notifications(owner, {
        "orders": [{"paid": False}], "subscription": None,
        "h1cloud": {"status": "unavailable"},
    })
    assert empty == []


def test_mark_read_only_accepts_current_owner_alerts(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    async def overview(_request):
        return {
            "orders": [{"paid": True, "delivered": True}],
            "subscription": None, "h1cloud": {"status": "unavailable"},
        }
    monkeypatch.setattr(account_feed, "customer_overview", overview)
    marked = []
    monkeypatch.setattr(account_feed, "_mark",
                        lambda owner, identifier: marked.append((owner, identifier)))
    with customer("alice@example.com") as client:
        other_id = "f" * 64
        assert client.post("/api/account/notifications/read",
                           headers={"Origin": ORIGIN},
                           json={"notification_id": other_id}).status_code == 404
        assert client.post("/api/account/notifications/read",
                           json={"notification_id": other_id}).status_code == 403
        correct = account_feed._notifications(
            growth._owner("alice@example.com"), awaitable_data()
        )[0]["id"]
        result = client.post("/api/account/notifications/read",
                             headers={"Origin": ORIGIN},
                             json={"notification_id": correct})
        assert result.status_code == 200
    assert len(marked) == 1 and marked[0][1] == correct


def awaitable_data():
    return {
        "orders": [{"paid": True, "delivered": True}],
        "subscription": None, "h1cloud": {"status": "unavailable"},
    }


def test_frontend_has_no_hidden_payment_or_key_storage():
    for filename in ("referrals", "rewards", "gifts", "notifications"):
        page = (SITE / (filename + ".html")).read_text(encoding="utf-8")
        assert "vainah-benefits.js" in page
        assert 'name="viewport"' in page
        assert 'noindex' in page
    js = (SITE / "vainah-benefits.js").read_text(encoding="utf-8")
    assert "localStorage" not in js
    assert "sessionStorage" not in js
    assert "innerHTML" not in js
    assert "textContent" in js
    assert "redeemable_points" in js
    assert "/api/account/notifications/read" in js
