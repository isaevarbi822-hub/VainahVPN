"""QR is generated locally, only after authenticated paid-access checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import subscription_qr
from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_qr_requires_account_ownership_and_a_live_subscription(monkeypatch):
    async def denied(_request):
        raise HTTPException(401, "ACCOUNT_LOGIN_REQUIRED")

    monkeypatch.setattr(subscription_qr, "access", denied)
    with TestClient(app) as client:
        response = client.get("/api/account/qr")
        assert response.status_code == 401
        assert "no-store" in response.headers["cache-control"]
        assert "private-token" not in response.text


def test_qr_svg_private_no_cache_and_strict_csp(monkeypatch):
    async def allowed(_request):
        return {"subscription_url": "https://sub.example/test/PRIVATE_VAINAH_KEY_123"}

    monkeypatch.setattr(subscription_qr, "access", allowed)
    with TestClient(app) as client:
        response = client.get("/api/account/qr")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "no-store" in response.headers["cache-control"]
        assert "sandbox" in response.headers["content-security-policy"]
        assert "noindex" in response.headers["x-robots-tag"]
        assert "<svg" in response.text
        assert "PRIVATE_VAINAH_KEY_123" not in response.text
        assert "<script" not in response.text.lower()


def test_qr_rejects_unencodable_subscriptions_without_echo(monkeypatch):
    async def too_long(_request):
        return {"subscription_url": "https://sub.example/" + "X" * 2500}

    monkeypatch.setattr(subscription_qr, "access", too_long)
    with TestClient(app) as client:
        response = client.get("/api/account/qr")
        assert response.status_code == 422
        assert "sub.example" not in response.text


def test_qr_is_explicit_opt_in_and_revoked_on_logout():
    js = (SITE / "account-dashboard.js").read_text(encoding="utf-8")
    html = (SITE / "account.html").read_text(encoding="utf-8")
    assert 'id="account-get-qr"' in html
    assert 'id="account-qr-panel"' in html
    assert 'id="account-qr-image"' in html
    assert "function clearQR()" in js
    assert "URL.revokeObjectURL(privateQrUrl)" in js
    assert "fetch('/api/account/qr'" in js
    assert "window.addEventListener('pagehide',clearQR)" in js
    assert "function clearSubscription(){\n    clearQR();" in js
    assert "session!==sessionEpoch||revision!==refreshEpoch" in js


def test_new_qr_encoder_has_no_public_qr_service_dependencies():
    js = (SITE / "account-dashboard.js").read_text(encoding="utf-8")
    source = (Path(__file__).resolve().parents[1] / "vainah" / "subscription_qr.py"
              ).read_text(encoding="utf-8")
    assert "import qrcode" in source
    assert "qrcode.image.svg" in source
    assert "await access(request)" in source
    assert "qrserver.com" not in source + js
    assert "api.qrserver" not in source + js
