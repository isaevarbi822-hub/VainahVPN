"""Passwordless login: signed cookies, one-time codes, and privacy boundaries."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import customer_portal, email_auth
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "example-only-test-session-secret-at-least-32-bytes"
EMAIL = "example@example.com"


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("RESEND_API_KEY", "re_example_test_key_placeholder_123456")
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "Vainah <hello@verified.example>")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567"
    )


def test_email_session_signature_and_expiry(environment):
    cookie = email_auth._sign_session(EMAIL, now=1700000000)
    assert email_auth._read_session(cookie, now=1700000001) == EMAIL
    assert email_auth._read_session(cookie, now=1700000000 + 13 * 3600) is None
    assert email_auth._read_session(cookie + "a", now=1700000001) is None
    payload, signature = cookie.split(".")
    modified = ("A" if payload[0] != "A" else "B") + payload[1:]
    assert email_auth._read_session(modified + "." + signature,
                                     now=1700000001) is None


def test_email_login_unconfigured_responds_without_secrets(monkeypatch, environment):
    monkeypatch.delenv("RESEND_API_KEY")
    with TestClient(app, base_url=ORIGIN) as client:
        cfg = client.get("/api/email-auth/config")
        assert cfg.json()["available"] is False
        assert "re_" not in str(cfg.json())
        assert client.post(
            "/api/email-auth/request", headers={"Origin": ORIGIN},
            json={"email": EMAIL},
        ).status_code == 503


def test_email_otp_login_and_logout(environment, monkeypatch):
    codes = {}
    sent = []

    def start(email, _source_hash):
        codes[email] = "123456"
        return codes[email]

    def verify(email, code):
        if codes.get(email) != code:
            return False
        del codes[email]
        return True

    async def send(email, code):
        sent.append((email, code))

    monkeypatch.setattr(email_auth, "_locked_send_code", start)
    monkeypatch.setattr(email_auth, "_verify_code", verify)
    monkeypatch.setattr(email_auth, "send_verification_code", send)

    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/email-auth/config").json()["available"] is True
        assert client.get("/api/telegram/config").json()["email_login_available"] is True
        assert client.get("/api/email-auth/account").json()["authenticated"] is False
        assert client.post("/api/email-auth/request", json={"email": EMAIL}
                           ).status_code == 403
        assert client.post(
            "/api/email-auth/request",
            headers={"Origin": "https://attacker.example"},
            json={"email": EMAIL},
        ).status_code == 403
        assert client.post(
            "/api/email-auth/request",
            headers={"Origin": ORIGIN},
            json={"email": "EXAMPLE@EXAMPLE.COM"},
        ).status_code == 200
        assert sent == [(EMAIL, "123456")]
        assert client.post(
            "/api/email-auth/verify", headers={"Origin": ORIGIN},
            json={"email": EMAIL, "code": "999999"},
        ).status_code == 401
        assert client.get("/api/email-auth/account").json()["authenticated"] is False

        login = client.post(
            "/api/email-auth/verify", headers={"Origin": ORIGIN},
            json={"email": EMAIL, "code": "123456"},
        )
        assert login.status_code == 200
        assert login.json()["user"] == {
            "auth_method": "email", "email": EMAIL,
        }
        cookie = login.headers.get("set-cookie", "")
        assert "__Host-vainah_email_session=" in cookie
        assert "HttpOnly" in cookie and "Secure" in cookie
        assert "SameSite=lax" in cookie
        assert client.get("/api/email-auth/account").json() == {
            "authenticated": True,
            "user": {"auth_method": "email", "email": EMAIL},
        }
        assert client.post(
            "/api/email-auth/verify", headers={"Origin": ORIGIN},
            json={"email": EMAIL, "code": "123456"},
        ).status_code == 401
        assert client.post("/api/email-auth/logout").status_code == 403
        result = client.post(
            "/api/email-auth/logout", headers={"Origin": ORIGIN}, json={}
        )
        assert result.status_code == 200
        assert client.get("/api/email-auth/account").json()["authenticated"] is False


def test_unlinked_email_gets_empty_portal_not_other_users_keys(
    environment, monkeypatch
):
    monkeypatch.setattr(
        customer_portal, "telegram_id_for_verified_email", lambda email: None
    )
    cookie = email_auth._sign_session(EMAIL)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE, cookie)
        page = client.get("/api/account/overview")
        assert page.status_code == 200
        assert page.json()["email"] == {"verified": True, "address": EMAIL}
        assert page.json()["orders"] == []
        assert page.json()["subscription"] is None
        assert page.json()["h1cloud"]["status"] == "not_linked"
        assert client.get("/api/account/access").status_code == 404
        assert client.post(
            "/api/account/email/request",
            headers={"Origin": ORIGIN},
            json={"email": "victim@example.com"},
        ).status_code == 401


def test_prior_verified_telegram_email_can_use_same_subscription_portal(
    environment, monkeypatch
):
    looked_up = []
    monkeypatch.setattr(
        customer_portal,
        "telegram_id_for_verified_email",
        lambda email: looked_up.append(email) or "123456789",
    )
    monkeypatch.setattr(
        customer_portal, "customer_receipts",
        lambda _telegram_id: [],
    )

    async def status(telegram_id):
        assert telegram_id == "123456789"
        return {"status": "not_found", "message": "Не найден"}

    monkeypatch.setattr(customer_portal, "h1_customer_state", status)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(
            email_auth.EMAIL_SESSION_COOKIE,
            email_auth._sign_session(EMAIL),
        )
        result = client.get("/api/account/overview")
        assert result.status_code == 200
        assert looked_up == [EMAIL]
        assert result.json()["auth_method"] == "email"
        assert result.json()["orders"] == []


def test_mail_login_does_not_need_telegram_service(environment, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/telegram/config").json()["available"] is False
        assert client.get("/api/email-auth/config").json()["available"] is True


def test_email_normalization_rejects_invalid_address():
    with pytest.raises(HTTPException):
        email_auth.normalize_email("hello there")
    assert email_auth.normalize_email("TeSt@Example.COM") == "test@example.com"


@pytest.mark.parametrize("missing", [
    "DATABASE_URL", "SESSION_SIGNING_KEY", "RESEND_API_KEY", "VAINAH_EMAIL_FROM",
])
def test_email_config_reports_only_missing_setting_names(environment, monkeypatch, missing):
    monkeypatch.delenv(missing, raising=False)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/email-auth/config")
    assert response.status_code == 200
    result = response.json()
    assert result["available"] is False
    assert result["missing_settings"] == [missing]
    assert result["checks"][missing] is False
    assert set(result["checks"]) == {
        "DATABASE_URL", "SESSION_SIGNING_KEY", "RESEND_API_KEY", "VAINAH_EMAIL_FROM"
    }
    output = str(result)
    assert SECRET not in output
    assert "postgresql://fake:" not in output
    assert "re_example_test" not in output


def test_email_config_uses_safe_ascii_message_when_ready(environment):
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get("/api/email-auth/config").json()
    assert result["available"] is True
    assert result["missing_settings"] == []
    assert all(result["checks"].values())
