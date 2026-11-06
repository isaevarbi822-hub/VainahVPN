"""Vainah Check must not invent VPN health, leak secrets, or expose customer data."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from vainah import connection_check
from vainah.main import app

BASE = "https://vainahvpn-python-preview.onrender.com"


def test_public_summary_redacts_remote_data_and_does_not_claim_vpn_health():
    result = connection_check.summarize_services(
        {"status": "ok", "message": "private-db-password"},
        {
            "h1": {"status": "ok", "message": "private H1 auth token"},
            "rollypay": {"status": "unavailable", "message": "private merchant key"},
            "webhook": {"status": "configured", "message": "private webhook secret"},
        },
    )
    assert result["scope"] == "control_plane_only"
    assert result["verified_vpn_tunnel"] is False
    assert result["server_latency_measured"] is False
    assert result["payment_completion_tested"] is False
    assert result["provider_checks_cached_up_to_seconds"] == 180
    assert result["summary"] == "partial"
    assert len(result["checks"]) == 5
    assert "private" not in str(result)
    assert result["checks"][2]["state"] == "ok"
    assert result["checks"][3]["state"] == "unknown"


def test_public_status_is_live_readonly_without_secrets(monkeypatch):
    async def database():
        return {"status": "ok", "message": "do-not-echo-secret"}
    async def provider():
        return {"h1": {"status": "error", "message": "do-not-echo-provider"},
                "rollypay": {"status": "unavailable"},
                "webhook": {"status": "configured"}}
    monkeypatch.setattr(connection_check, "database_status", database)
    monkeypatch.setattr(connection_check, "integration_status", provider)
    with TestClient(app, base_url=BASE) as client:
        response = client.get("/api/site/check/summary")
    assert response.status_code == 200
    assert response.json()["summary"] == "attention"
    assert "do-not-echo" not in response.text


def test_only_confirmed_paid_h1_profile_reports_active():
    result=connection_check.diagnose_account({
        "orders": [{"paid": True, "delivered": True}],
        "subscription": {"paid": True, "status": "delivered",
                         "expires_at": "2028-11-06T18:00:00+00:00",
                         "traffic": {"used_bytes": 9, "limit_bytes": 10},
                         "subscription_url": "https://private-secret.invalid/a"},
        "h1cloud": {"status": "active", "h1_token": "private-token"},
    })
    assert result["result"] == "paid_profile_active"
    assert result["traffic_used_percent"] == 90
    assert result["tunnel_tested"] is False
    assert "private" not in str(result)


def test_h1_unavailable_is_not_marked_expired_or_active():
    result=connection_check.diagnose_account({
        "orders": [{"paid": True, "delivered": True}],
        "subscription": None,
        "h1cloud": {"status": "unavailable"},
    })
    assert result["level"] == "unknown"
    assert "истекла" in result["next_step"]
    assert result["expires_at"] is None


def test_no_payment_does_not_infer_payment_from_h1_only():
    result=connection_check.diagnose_account({
        "orders": [], "subscription": None,
        "h1cloud": {"status": "active"},
    })
    assert result["result"] == "no_confirmed_delivery"
    assert result["profile_checked"] is True
    assert result["tunnel_tested"] is False


def test_unknown_traffic_never_becomes_zero():
    result=connection_check.diagnose_account({
        "orders": [{"paid": True, "delivered": True}],
        "subscription": {"paid": True, "status": "delivered",
                         "traffic": {"used_bytes": None, "limit_bytes": 0}},
        "h1cloud": {"status": "active"},
    })
    assert result["traffic_used_percent"] is None


def test_private_route_requires_login_and_never_returns_overview(monkeypatch):
    with TestClient(app, base_url=BASE) as guest:
        assert guest.get("/api/account/connection-check").status_code == 401
    async def verified(_request):
        return {"orders": [], "subscription": None, "h1cloud": {"status": "unavailable"},
                "email": "private@example.test", "subscription_url": "https://secret.invalid"}
    monkeypatch.setattr(connection_check, "account_overview", verified)
    with TestClient(app, base_url=BASE) as client:
        response=client.get("/api/account/connection-check")
    assert response.status_code == 200
    assert "private@example.test" not in response.text
    assert "secret.invalid" not in response.text


def test_server_picker_is_disabled_until_real_metrics_exist():
    with TestClient(app, base_url=BASE) as client:
        data = client.get("/api/site/check/server-selection").json()
    assert data["available"] is False
    assert data["recommended_server"] is None
    assert data["locations"] == []
    assert data["latency_source"] == "not_connected"


def test_new_frontend_is_safe_and_reports_render_not_vpn_latency():
    from pathlib import Path
    site = Path(__file__).resolve().parents[2] / "storefront"
    html = (site / "connection-check.html").read_text(encoding="utf-8")
    js = (site / "connection-check.js").read_text(encoding="utf-8")
    assert 'id="check-account"' in html
    assert "VPN-ключ" in html
    assert "/api/account/connection-check" in js
    assert "/api/site/check/summary" in js
    assert "/api/site/check/server-selection" in js
    assert "/api/speedtest/ping" in js
    assert "не задержка до VPN-сервера" in js
    assert "localStorage" not in js
    assert "sessionStorage" not in js
    assert "innerHTML" not in js
    assert "textContent" in js


def test_check_page_has_strict_csp_and_private_cache_policy():
    with TestClient(app, base_url=BASE) as client:
        response = client.get("/connection-check.html")
        script = client.get("/connection-check.js")
    assert response.status_code == 200
    assert script.status_code == 200
    assert "noindex" in response.headers.get("x-robots-tag", "")
    assert "unsafe-inline" not in response.headers.get("content-security-policy", "")
    assert "no-store" in response.headers.get("cache-control", "")
    assert "no-store" in script.headers.get("cache-control", "")
