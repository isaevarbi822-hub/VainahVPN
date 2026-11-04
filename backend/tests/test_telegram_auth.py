"""Telegram Widget authentication is signature-verified, not a username field."""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from vainah.main import app
from vainah.telegram_auth import make_session, read_session, verify_login

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567"
SESSION_SECRET = "test-only-session-secret-that-is-very-long"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("SESSION_SIGNING_KEY", SESSION_SECRET)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "VainahVPNbot")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)


def login_data(**changes):
    now = int(time.time())
    data = {
        "id": 123456789,
        "first_name": "Test user",
        "username": "test_user",
        "auth_date": now,
    }
    data.update(changes)
    checked = "\n".join(
        str(key) + "=" + str(data[key]) for key in sorted(data)
    )
    data["hash"] = hmac.new(
        hashlib.sha256(BOT_TOKEN.encode()).digest(),
        checked.encode(), hashlib.sha256,
    ).hexdigest()
    return data


def test_widget_signature_not_just_telegram_id(env):
    good = verify_login(login_data(), BOT_TOKEN)
    assert good["telegram_id"] == "123456789"
    bad = login_data()
    bad["id"] = 999999999
    assert verify_login(bad, BOT_TOKEN) is None
    assert verify_login(login_data(auth_date=int(time.time()) - 3600), BOT_TOKEN) is None
    assert verify_login(login_data(first_name="Fake", hash="nothash"), BOT_TOKEN) is None
    invalid = login_data()
    invalid["random_extra"] = "data"
    assert verify_login(invalid, BOT_TOKEN) is None


def test_secure_cookie_account_login_logout(env):
    with TestClient(app, base_url=ORIGIN) as client:
        cfg = client.get("/api/telegram/config")
        assert cfg.status_code == 200
        assert cfg.json()["available"] is True
        assert cfg.json()["bot_username"] == "VainahVPNbot"
        assert "123456789:" not in str(cfg.json())
        assert client.get("/api/telegram/account").json()["authenticated"] is False

        denied = client.post(
            "/api/telegram/account", json={"action": "login", "data": login_data()}
        )
        assert denied.status_code == 403

        logged = client.post(
            "/api/telegram/account",
            headers={"Origin": ORIGIN},
            json={"action": "login", "data": login_data()},
        )
        assert logged.status_code == 200
        assert logged.json()["user"]["telegram_id"] == "123456789"
        cookie = logged.headers.get("set-cookie", "")
        assert "Secure" in cookie and "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "__Host-vainah_session=" in cookie
        assert client.get("/api/telegram/account").json()["authenticated"] is True

        assert client.post("/api/telegram/account",
                           headers={"Origin": "https://evil.example"},
                           json={"action": "logout"}).status_code == 403
        logged_out = client.post(
            "/api/telegram/account", headers={"Origin": ORIGIN},
            json={"action": "logout"},
        )
        assert logged_out.status_code == 200
        assert client.get("/api/telegram/account").json()["authenticated"] is False


def test_signed_session_cannot_be_modified(env):
    session = make_session({
        "telegram_id": "123456789", "username": "real", "first_name": "Tester",
    }, SESSION_SECRET, now=1700000000)
    assert read_session(session, SESSION_SECRET, now=1700000001)["username"] == "real"
    assert read_session(session + "x", SESSION_SECRET, now=1700000001) is None
    assert read_session(session, "different-secret", now=1700000001) is None
    assert read_session(session, SESSION_SECRET, now=1700000000 + 13 * 3600) is None


def test_login_unavailable_when_token_unconfigured(monkeypatch, env):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/telegram/config").json()["available"] is False
        response = client.post("/api/telegram/account", headers={"Origin": ORIGIN},
                               json={"action": "login", "data": login_data()})
        assert response.status_code == 503
