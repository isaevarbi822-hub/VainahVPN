"""Tickets are owner-scoped, operator-gated, rate limited and safe to display."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import email_auth, support_tickets
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SIGNING = "test-only-signing-key-for-support-tickets-1234567890"
OPERATOR = "test-only-operator-key-with-at-least-forty-characters"
SITE = Path(__file__).resolve().parents[2] / "storefront"


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING)
    monkeypatch.setenv("VAINAH_SUPPORT_OPERATOR_KEY", OPERATOR)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_OIDC_CLIENT_SECRET", raising=False)


def _client(email: str | None = None):
    client = TestClient(app, base_url=ORIGIN)
    if email:
        client.cookies.set(
            email_auth.EMAIL_SESSION_COOKIE,
            email_auth._sign_session(email),
        )
    return client


def test_ticket_config_requires_operator_setup(environment, monkeypatch):
    with _client() as client:
        assert client.get("/api/support/config").json()["available"] is True
    monkeypatch.delenv("VAINAH_SUPPORT_OPERATOR_KEY")
    with _client() as client:
        assert client.get("/api/support/config").json()["available"] is False
        assert client.get("/api/support/tickets").status_code == 401
        assert client.post(
            "/api/support/tickets", headers={"Origin": ORIGIN},
            json={"category": "account", "message": "Проблема со входом на сайте."},
        ).status_code == 401


def test_customer_tickets_are_isolated_and_require_valid_origin(environment, monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(
        support_tickets, "_create",
        lambda owner, category, message, encrypted=None: (
            seen.append((owner, category, message, encrypted))
            or {"id": "localTEST1234567890", "status": "open"}
        ),
    )
    monkeypatch.setattr(
        support_tickets, "_owned",
        lambda owner: [{"id": "localTEST1234567890", "owner": owner}],
    )
    with _client("alice@example.com") as alice:
        assert alice.post(
            "/api/support/tickets",
            json={"category": "account", "message": "Помогите с подключением аккаунта."},
        ).status_code == 403
        assert alice.post(
            "/api/support/tickets",
            headers={"Origin": ORIGIN},
            json={"category": "account", "message": "vless://key-not-allowed"},
        ).status_code == 422
        assert alice.post(
            "/api/support/tickets",
            headers={"Origin": ORIGIN},
            json={"category": "account", "message": "https://example.com/link"},
        ).status_code == 422
        result = alice.post(
            "/api/support/tickets", headers={"Origin": ORIGIN},
            json={"category": "account", "message": "Не пришёл одноразовый код входа."},
        )
        assert result.status_code == 201
        assert result.json()["status"] == "open"
        assert alice.get("/api/support/tickets").status_code == 200
        first_owner = seen[0][0]
        assert len(first_owner) == 64
        assert "alice@" not in first_owner
    with _client("bob@example.com") as bob:
        result = bob.get("/api/support/tickets")
        assert result.status_code == 200
        assert result.json()["items"][0]["owner"] != first_owner


def test_operator_can_view_and_reply_but_not_without_key(environment, monkeypatch):
    updated = []
    monkeypatch.setattr(support_tickets, "_operator_list",
                        lambda: [{"id": "localTEST1234567890"}])
    monkeypatch.setattr(support_tickets, "_operator_reply",
                        lambda *args: updated.append(args))
    with _client() as client:
        assert client.get("/api/support/operator/tickets").status_code == 403
        headers={"X-Vainah-Support-Key": OPERATOR}
        assert client.get(
            "/api/support/operator/tickets", headers=headers
        ).json()["items"][0]["id"] == "localTEST1234567890"
        path="/api/support/operator/tickets/localTEST1234567890/reply"
        assert client.post(path, headers=headers,
            json={"reply": "Уточните версию приложения."}
        ).status_code == 403
        assert client.post(path, headers={**headers, "Origin": ORIGIN},
            json={"reply": "https://example.com/private"}
        ).status_code == 422
        reply=client.post(path, headers={**headers, "Origin": ORIGIN},
            json={"reply": "Проверьте обновление приложения.", "status": "answered"}
        )
        assert reply.status_code == 200
        assert updated == [(
            "localTEST1234567890", "Проверьте обновление приложения.", "answered",
        )]


def test_ticket_limit_is_enforced_in_database_transaction(environment, monkeypatch):
    queries = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=()):
            queries.append((sql, params))

        def fetchone(self):
            return (3,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        support_tickets.psycopg, "connect",
        lambda *_args, **_kwargs: Connection(),
    )
    with pytest.raises(HTTPException) as exc:
        support_tickets._create("a" * 64, "account", "No login code.")
    assert exc.value.status_code == 429
    assert any("pg_advisory_xact_lock" in sql for sql, _ in queries)
    assert any("count(*)" in sql for sql, _ in queries)
    assert not any("INSERT INTO vainah_support_tickets" in sql for sql, _ in queries)


def test_support_frontend_does_not_store_secrets_or_use_html_injection():
    page=(SITE / "support-center.html").read_text(encoding="utf-8")
    script=(SITE / "support-center.js").read_text(encoding="utf-8")
    operator=(SITE / "support-operator.js").read_text(encoding="utf-8")
    assert 'src="support-center.js"' in page
    assert 'id="vs-form"' in page
    assert "textContent" in script and "textContent" in operator
    assert "innerHTML" not in script + operator
    assert "localStorage" not in script + operator
    assert "sessionStorage" not in script + operator
    assert "X-Vainah-Support-Key" in operator
    with _client() as client:
        admin=client.get("/support-operator.html")
        assert admin.status_code == 200
        assert "noindex" in admin.headers["x-robots-tag"]
        assert "no-store" in admin.headers["cache-control"]
        assert "unsafe-inline" not in admin.headers["content-security-policy"]
