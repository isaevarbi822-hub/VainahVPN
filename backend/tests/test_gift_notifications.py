"""Gift alerts contain no code, email or payment link; stay owner scoped."""
from __future__ import annotations

from fastapi.testclient import TestClient

from vainah import account_feed, email_auth, live_checkout, live_ledger
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "test-gift-alert-secret-key-long-enough-0123456789abcdef"


def _customer(email: str) -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set(email_auth.EMAIL_SESSION_COOKIE, email_auth._sign_session(email))
    return client


def test_signed_gift_alerts_without_secrets(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setattr(live_checkout, "live_account_ready", lambda: True)
    captured = []

    class GiftLedger:
        def __init__(self, _url):
            pass

        def owner_gift_notification_states(self, owner_ref):
            captured.append(owner_ref)
            return [
                ("vainah_live_" + "a" * 32, "ready_to_share"),
                ("vainah_live_" + "b" * 32, "pending_delivery"),
                ("vainah_live_" + "c" * 32, "needs_support"),
                ("vainah_live_" + "d" * 32, "none"),
            ]

    monkeypatch.setattr(live_ledger, "PostgresLiveOrderLedger", GiftLedger)
    monkeypatch.setattr(account_feed, "database_url", lambda: "postgresql://test/readonly")
    monkeypatch.setattr(account_feed, "_read_ids", lambda _owner, _ids: set())

    async def overview(_request):
        return {"orders": [], "subscription": None, "h1cloud": {}}

    monkeypatch.setattr(account_feed, "customer_overview", overview)
    marked = []
    monkeypatch.setattr(account_feed, "_mark", lambda owner, item: marked.append((owner, item)))

    with _customer("owner@example.com") as client:
        response = client.get("/api/account/notifications")
        assert response.status_code == 200
        data = response.json()
        assert data["unread_count"] == 3
        assert {item["type"] for item in data["items"]} == {
            "gift_ready_to_share", "gift_pending_delivery", "gift_needs_support",
        }
        assert all(len(item["id"]) == 64 for item in data["items"])
        assert all(item["href"] in {"/gifts.html", "/support-center.html"} for item in data["items"])
        assert "VG" + "A" * 32 not in response.text
        assert "owner@example.com" not in response.text
        assert "vainah_live_" not in response.text

        target = data["items"][0]["id"]
        assert client.post(
            "/api/account/notifications/read",
            json={"notification_id": target},
        ).status_code == 403
        assert client.post(
            "/api/account/notifications/read",
            headers={"Origin": ORIGIN}, json={"notification_id": "f" * 64},
        ).status_code == 404
        ok = client.post(
            "/api/account/notifications/read",
            headers={"Origin": ORIGIN}, json={"notification_id": target},
        )
        assert ok.status_code == 200

    assert len(captured) >= 1
    assert captured[0].startswith("v1_")
    assert len(marked) == 1


def test_gift_alert_failure_does_not_break_h1_alerts(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setattr(live_checkout, "live_account_ready", lambda: True)

    class BrokenLedger:
        def __init__(self, _url):
            pass

        def owner_gift_notification_states(self, _owner_ref):
            raise live_ledger.LiveLedgerError("LIVE_LEDGER_UNAVAILABLE")

    monkeypatch.setattr(live_ledger, "PostgresLiveOrderLedger", BrokenLedger)
    monkeypatch.setattr(account_feed, "database_url", lambda: "postgresql://test/unavailable")
    result = account_feed._account_alerts(
        "a" * 64, "owner@example.com",
        {"orders": [], "subscription": None, "h1cloud": {}},
    )
    assert result == []


def test_notification_page_supports_only_allowlisted_gift_link():
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "storefront" / "vainah-benefits.js"
    content = path.read_text(encoding="utf-8")
    assert "account|support-center|gifts" in content
    assert "innerHTML" not in content
