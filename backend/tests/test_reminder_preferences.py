"""Reminder preferences are opt-in, account scoped, and not a sending endpoint."""
from fastapi.testclient import TestClient

from vainah import email_auth, reminder_preferences
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "test-reminder-signing-key-01234567890123456789"


def test_reminders_require_verified_email_and_same_origin(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(reminder_preferences, "_read", lambda owner: False)
    monkeypatch.setattr(reminder_preferences, "_write", lambda owner, enabled: None)
    with TestClient(app, base_url=ORIGIN) as guest:
        assert guest.get("/api/account/reminder-preference").status_code == 401
        assert guest.post("/api/account/reminder-preference",
                          headers={"Origin": ORIGIN},
                          json={"enabled": True}).status_code == 401
        guest.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                          email_auth._sign_session("member@example.com"))
        assert guest.post("/api/account/reminder-preference",
                          json={"enabled": True}).status_code == 403
        result = guest.get("/api/account/reminder-preference")
        assert result.status_code == 200
        assert result.json() == {
            "enabled": False, "delivery_active": False,
            "message": "Email reminders are not yet scheduled.",
        }


def test_reminder_optin_and_optout_are_scoped(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    saved = {}
    monkeypatch.setattr(reminder_preferences, "_read",
                        lambda owner: saved.get(owner, False))
    monkeypatch.setattr(reminder_preferences, "_write",
                        lambda owner, enabled: saved.__setitem__(owner, enabled))
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                           email_auth._sign_session("alice@example.com"))
        assert client.post("/api/account/reminder-preference",
                           headers={"Origin": ORIGIN},
                           json={"enabled": True}).json()["enabled"] is True
        assert client.get("/api/account/reminder-preference").json()["enabled"] is True
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                           email_auth._sign_session("bob@example.com"))
        assert client.get("/api/account/reminder-preference").json()["enabled"] is False
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                           email_auth._sign_session("alice@example.com"))
        assert client.post("/api/account/reminder-preference",
                           headers={"Origin": ORIGIN},
                           json={"enabled": False}).json()["enabled"] is False
        assert all(len(owner) == 64 and "@" not in owner for owner in saved)


def test_reminder_settings_never_claim_email_is_active():
    from pathlib import Path
    site = Path(__file__).resolve().parents[2] / "storefront"
    page = (site / "account.html").read_text(encoding="utf-8")
    script = (site / "account-reminder-preference.js").read_text(encoding="utf-8")
    assert "account-reminder-optin" in page
    assert "account-reminder-preference.js" in page
    assert "Отправка начнётся только после настройки" in page
    assert "localStorage" not in script
    assert "innerHTML" not in script
    assert "delivery_active" in script
    assert "Автоматические email-письма ещё не запущены" in script
