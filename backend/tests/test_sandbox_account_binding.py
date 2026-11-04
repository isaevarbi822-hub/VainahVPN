"""Authenticated ownership for operator sandbox orders, no live money/VPN."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vainah import billing, email_auth
from vainah.main import app

TOKEN = "test-operator-claim-bound-" + "a" * 32
KEY = "test-session-only-" + "b" * 48


def session_cookie(email: str) -> str:
    return f"{email_auth.EMAIL_SESSION_COOKIE}={email_auth._sign_session(email)}"


@pytest.fixture
def environment(monkeypatch, tmp_path):
    path = str(tmp_path / "sandbox-orders.sqlite3")
    monkeypatch.setenv("SESSION_SIGNING_KEY", KEY)
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", TOKEN)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    monkeypatch.setattr(billing, "sandbox", billing.BillingSandbox("mock", ledger_path=path))
    with TestClient(app) as client:
        yield client, path


def test_verified_email_binds_new_order_and_allows_only_owner_to_view(environment, monkeypatch):
    client, dbpath = environment
    alice = {"Cookie": session_cookie("alice@example.com")}
    bob = {"Cookie": session_cookie("bob@example.com")}
    created = client.post(
        "/api/shop/sandbox/start",
        headers={**alice, "X-Sandbox-Token": TOKEN},
        json={"plan": "365-family"},
    )
    assert created.status_code == 200, created.text
    order = created.json()
    assert order["owner_bound"] is True
    assert order["test_only"] is True and order["vpn_delivered"] is False
    assert "alice@example.com" not in str(order)

    # A browser session cannot create new test orders without operator token.
    assert client.post(
        "/api/shop/sandbox/start", headers=alice, json={"plan": "30"},
    ).status_code == 401

    mine = client.get("/api/shop/my-test-orders", headers=alice)
    assert mine.status_code == 200
    assert [x["order_id"] for x in mine.json()["items"]] == [order["order_id"]]
    assert mine.json()["items"][0]["pay_url"] is None
    assert client.get("/api/shop/my-test-orders", headers=bob).json()["items"] == []
    assert client.get("/api/shop/my-test-orders").status_code == 401

    path = f'/api/shop/my-test-orders/{order["order_id"]}/activation-preview'
    assert client.get(path, headers=bob).status_code == 404
    assert client.get(path).status_code == 401
    own = client.get(path, headers=alice)
    assert own.status_code == 200
    assert own.json()["fulfillment"]["customer_identity_bound"] is True
    assert own.json()["fulfillment"]["status"] == "blocked"
    assert own.json()["fulfillment"]["h1cloud_write_performed"] is False

    # A signed email session never leaks into the durable order ledger.
    ledger_bytes = Path(dbpath).read_bytes()
    assert b"alice@example.com" not in ledger_bytes
    assert KEY.encode() not in ledger_bytes

    # After restart, authenticated ownership is retained.
    monkeypatch.setattr(
        billing, "sandbox", billing.BillingSandbox("mock", ledger_path=dbpath),
    )
    assert [x["order_id"] for x in client.get(
        "/api/shop/my-test-orders", headers=alice,
    ).json()["items"]] == [order["order_id"]]
    assert client.get(path, headers=bob).status_code == 404


def test_old_anonymous_orders_never_become_ownable_by_guessing_id(environment):
    client, _ = environment
    unbound = client.post(
        "/api/shop/sandbox/start",
        headers={"X-Sandbox-Token": TOKEN},
        json={"plan": "30"},
    )
    assert unbound.status_code == 200
    order = unbound.json()
    assert order["owner_bound"] is False
    alice = {"Cookie": session_cookie("alice@example.com")}
    assert client.get("/api/shop/my-test-orders", headers=alice).json()["items"] == []
    assert client.get(
        f'/api/shop/my-test-orders/{order["order_id"]}/activation-preview',
        headers=alice,
    ).status_code == 404
    # Fake, unsigned session cookies are not trusted.
    invalid = {"Cookie": f"{email_auth.EMAIL_SESSION_COOKIE}=fake"}
    assert client.get("/api/shop/my-test-orders", headers=invalid).status_code == 401


def test_owner_ref_is_stable_and_domain_separated(environment, monkeypatch):
    client, _ = environment
    alice = {"Cookie": session_cookie("alice@example.com")}
    first = client.post(
        "/api/shop/sandbox/start",
        headers={**alice, "X-Sandbox-Token": TOKEN},
        json={"plan": "30"},
    ).json()
    second = client.post(
        "/api/shop/sandbox/start",
        headers={**alice, "X-Sandbox-Token": TOKEN},
        json={"plan": "60"},
    ).json()
    assert first["owner_bound"] is True and second["owner_bound"] is True
    refs = {o.owner_ref for o in billing.sandbox.orders.values()}
    assert len(refs) == 1
    assert next(iter(refs)).startswith("v1_")
    assert len(next(iter(refs))) == 67
    assert "alice@example.com" not in next(iter(refs))
    # Telegram-only and email identities cannot silently merge.
    monkeypatch.setattr("vainah.telegram_auth.current_user",
                        lambda _request: {"telegram_id": "123456789"})
    telegram = client.post(
        "/api/shop/sandbox/start",
        headers={"X-Sandbox-Token": TOKEN},
        json={"plan": "30"},
    ).json()
    assert telegram["owner_bound"] is True
    refs = {o.owner_ref for o in billing.sandbox.orders.values()}
    assert len(refs) == 2
    assert all(r is not None and len(r) == 67 for r in refs)
