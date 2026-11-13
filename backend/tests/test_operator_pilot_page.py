"""The operator pilot UI is first-party and cannot silently create a charge."""
from fastapi.testclient import TestClient

from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"


def test_operator_pilot_page_has_strict_csp_and_no_caching():
    with TestClient(app, base_url=ORIGIN) as client:
        page = client.get("/operator-pilot.html")
        assert page.status_code == 200
        assert page.headers["cache-control"].startswith("no-store")
        assert page.headers["x-robots-tag"].startswith("noindex")
        assert page.headers["referrer-policy"] == "no-referrer"
        csp = page.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "script-src 'self'" in csp
        assert "connect-src 'self'" in csp
        assert "'unsafe-inline'" not in csp
        assert "https://telegram.org" not in csp
        assert "/operator-pilot.js" in page.text
        assert "/operator-pilot.css" in page.text
        assert "<script>" not in page.text
        assert "<style>" not in page.text
        assert "id=\"create-button\"" in page.text
        assert 'class="button primary" disabled' in page.text


def test_operator_pilot_script_is_private_flow_no_storage_or_auto_checkout():
    with TestClient(app, base_url=ORIGIN) as client:
        script = client.get("/operator-pilot.js")
        assert script.status_code == 200
        assert script.headers["cache-control"].startswith("no-store")
        assert "'unsafe-inline'" not in script.headers["content-security-policy"]
        text = script.text
        assert 'addEventListener("click", createInvoice)' in text
        assert 'addEventListener("click", checkStatus)' in text
        assert "window.confirm(" in text
        assert "localStorage" not in text
        assert "sessionStorage" not in text
        assert "console.log" not in text
        assert 'method: "POST"' in text
        assert '"Idempotency-Key": crypto.randomUUID()' in text
        assert 'target.hostname !== "pay.rollypay.io"' in text


def test_operator_pilot_public_page_does_not_unlock_public_live_checkout():
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/operator-pilot.html")
        response = client.post(
            "/api/shop/checkout",
            headers={"Origin": ORIGIN},
            json={"plan": "30"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "LIVE_CHECKOUT_NOT_READY"
