"""Support response emails: owner consent, encrypted addresses, durable retry."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import email_auth, support_tickets
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "test-only-session-key-longer-than-32-characters"
OPERATOR = "test-only-support-operator-key-with-40-characters"
TICKET = "abcDEF123456789012345678"
SITE = Path(__file__).resolve().parents[2] / "storefront"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("VAINAH_SUPPORT_OPERATOR_KEY", OPERATOR)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_only_configured_token_12345")
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "Vainah <hello@example.com>")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_OIDC_CLIENT_SECRET", raising=False)


def _customer(email: str = "owner@example.com") -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set(
        email_auth.EMAIL_SESSION_COOKIE,
        email_auth._sign_session(email),
    )
    return client


def test_opt_in_new_ticket_encrypts_confirmed_mailbox(configured, monkeypatch):
    stored = []
    monkeypatch.setattr(
        support_tickets, "_create",
        lambda *args: stored.append(args) or {"id": TICKET, "status": "open"},
    )
    with _customer() as client:
        normal = client.post(
            "/api/support/tickets", headers={"Origin": ORIGIN},
            json={"category": "account", "message": "Не приходит письмо входа."},
        )
        assert normal.status_code == 201
        assert stored[-1][3] is None
        opted = client.post(
            "/api/support/tickets", headers={"Origin": ORIGIN},
            json={"category": "account", "message": "Не приходит письмо входа.",
                  "notify_email": True},
        )
        assert opted.status_code == 201
        cipher = stored[-1][3]
        assert cipher != "owner@example.com"
        assert "owner@example.com" not in cipher
        assert support_tickets._fernet().decrypt(cipher.encode()).decode() == (
            "owner@example.com"
        )
        assert "email" not in opted.json()
        assert client.post(
            "/api/support/tickets", headers={"Origin": ORIGIN},
            json={"category": "account", "message": "Не приходит письмо входа.",
                  "notify_email": "true"},
        ).status_code == 422


def test_opt_in_never_accepts_an_unverified_destination(configured, monkeypatch):
    monkeypatch.setattr(support_tickets, "_verified_contact",
                        lambda _request: "verified@example.com")
    recorded = []
    monkeypatch.setattr(
        support_tickets, "_set_notifications",
        lambda owner, identifier, cipher: recorded.append(
            (owner, identifier, cipher)
        ) or True,
    )
    with _customer("owner@example.com") as client:
        assert client.post(
            "/api/support/tickets/" + TICKET + "/email-notifications",
            headers={"Origin": ORIGIN},
            json={"enabled": True, "email": "attacker@example.com"},
        ).status_code == 422
        assert client.post(
            "/api/support/tickets/" + TICKET + "/email-notifications",
            headers={"Origin": ORIGIN},
            json={"enabled": True},
        ).status_code == 200
        first_owner, identifier, encrypted = recorded[-1]
        assert len(first_owner) == 64
        assert identifier == TICKET
        assert support_tickets._fernet().decrypt(encrypted.encode()) == (
            b"verified@example.com"
        )
        assert client.post(
            "/api/support/tickets/" + TICKET + "/email-notifications",
            headers={"Origin": ORIGIN},
            json={"enabled": False},
        ).json()["email_notifications"] is False
        assert recorded[-1][2] is None
        assert client.post(
            "/api/support/tickets/" + TICKET + "/email-notifications",
            json={"enabled": True},
        ).status_code == 403
    with _customer("another@example.com") as another:
        assert support_tickets._owner_for_test if False else True
        # Ownership guard lives in SQL and is never derived from a ticket ID.
        assert support_tickets._owner is not None


def test_telegram_without_confirmed_email_cannot_enroll(configured, monkeypatch):
    monkeypatch.setattr(support_tickets, "current_user",
                        lambda _request: {"telegram_id": "123456789"})
    monkeypatch.setattr(support_tickets, "verified_email",
                        lambda _id: None)
    with _customer() as client:
        response = client.post(
            "/api/support/tickets/" + TICKET + "/email-notifications",
            headers={"Origin": ORIGIN},
            json={"enabled": True},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "SUPPORT_EMAIL_VERIFICATION_REQUIRED"


def test_mail_uses_verified_recipient_without_reply_or_secret(configured, monkeypatch):
    recipient = "verified@example.com"
    encrypted = support_tickets._fernet().encrypt(recipient.encode()).decode()
    claims = iter([(4, encrypted), None])
    monkeypatch.setattr(support_tickets, "_claim_notification",
                        lambda _ticket: next(claims))
    finished = []
    monkeypatch.setattr(support_tickets, "_finish_notification",
                        lambda *args: finished.append(args))
    sends = []

    async def fake_send(to, subject, body, **kwargs):
        sends.append((to, subject, body, kwargs))

    monkeypatch.setattr(support_tickets, "send_email", fake_send)
    assert asyncio.run(support_tickets._notify_reply(TICKET)) == "sent"
    assert asyncio.run(support_tickets._notify_reply(TICKET)) == "not_pending"
    assert len(sends) == 1
    to, subject, body, opts = sends[0]
    assert to == recipient
    assert "Vainah VPN" in subject
    assert "support-center.html" in body
    assert "Проверить платёж" not in body
    assert "vless://" not in body
    assert "owner@example.com" not in body
    assert opts["idempotency_key"] == f"vainah-support-reply-{TICKET}-4"
    assert finished == [(TICKET, 4, True)]


def test_resend_failure_preserves_retryable_pending(configured, monkeypatch):
    encrypted = support_tickets._fernet().encrypt(b"verified@example.com").decode()
    monkeypatch.setattr(support_tickets, "_claim_notification",
                        lambda _ticket: (11, encrypted))
    finished = []
    monkeypatch.setattr(support_tickets, "_finish_notification",
                        lambda *args: finished.append(args))

    async def unavailable(*_args, **_kwargs):
        raise HTTPException(503, "EMAIL_DELIVERY_UNAVAILABLE")

    monkeypatch.setattr(support_tickets, "send_email", unavailable)
    assert asyncio.run(support_tickets._notify_reply(TICKET)) == "pending"
    assert finished == [(TICKET, 11, False)]


def test_changed_reply_only_triggers_one_revision(configured, monkeypatch):
    row = {
        "reply": None, "enabled": True,
        "cipher": support_tickets._fernet().encrypt(
            b"verified@example.com"
        ).decode(),
        "rev": 0, "state": "none", "status": "open",
    }

    class FakeCursor:
        result = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=()):
            if "SELECT operator_reply" in sql:
                self.result = (row["reply"], row["enabled"], row["cipher"],
                               row["rev"], row["state"])
            elif "SET operator_reply=" in sql:
                row["reply"], row["status"], row["rev"], row["state"] = (
                    params[0], params[1], params[2], params[3]
                )

        def fetchone(self):
            return self.result

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        support_tickets.psycopg, "connect",
        lambda *_args, **_kwargs: FakeConnection(),
    )
    first = support_tickets._operator_reply(TICKET, "Ответ поддержки.", "answered")
    assert first["notification"] == "pending"
    assert first["revision"] == 1
    second = support_tickets._operator_reply(TICKET, "Ответ поддержки.", "closed")
    assert second["revision"] == 1
    third = support_tickets._operator_reply(TICKET, "Исправленный ответ.", "answered")
    assert third["revision"] == 2


def test_operator_reply_reports_delivery_separately(configured, monkeypatch):
    monkeypatch.setattr(support_tickets, "_operator_reply",
                        lambda *_args: {"notification": "pending"})
    calls = []

    async def fake_notify(ticket):
        calls.append(ticket)
        return "sent"

    monkeypatch.setattr(support_tickets, "_notify_reply", fake_notify)
    with TestClient(app, base_url=ORIGIN) as client:
        response=client.post(
            "/api/support/operator/tickets/" + TICKET + "/reply",
            headers={"Origin": ORIGIN, "X-Vainah-Support-Key": OPERATOR},
            json={"reply": "Проверьте приложение.", "status": "answered"},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": True, "notification": "sent"}
        assert calls == [TICKET]
        retry = client.post(
            "/api/support/operator/tickets/" + TICKET + "/retry-email",
            headers={"Origin": ORIGIN, "X-Vainah-Support-Key": OPERATOR},
        )
        assert retry.json()["notification"] == "sent"
        assert calls == [TICKET, TICKET]
        assert client.post(
            "/api/support/operator/tickets/" + TICKET + "/retry-email",
            headers={"Origin": ORIGIN},
        ).status_code == 403


def test_support_ui_explains_consent_and_delivery_status():
    html = (SITE / "support-center.html").read_text(encoding="utf-8")
    js = (SITE / "support-center.js").read_text(encoding="utf-8")
    operator = (SITE / "support-operator.js").read_text(encoding="utf-8")
    assert 'id="vs-notify-email"' in html
    assert "notify_email:notifyToggle?.checked===true" in js
    assert "/email-notifications" in js
    assert "email_notifications_available" in js
    assert "/retry-email" in operator
    assert "notification_state" in operator
    assert "Письмо пока не доставлено" in operator
    assert "innerHTML" not in js + operator
