"""Customer-named device entries never claim to be actual VPN sessions."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import device_registry, email_auth
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "device-registry-unit-test-signing-secret-123456789"
SITE = Path(__file__).resolve().parents[2] / "storefront"


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)

    def identity(request, *, include_email=True):
        email = email_auth.current_email(request)
        if email is None:
            raise HTTPException(401, "ACCOUNT_LOGIN_REQUIRED")
        return None, email, "email"

    monkeypatch.setattr(device_registry, "portal_identity", identity)


def _client(email: str | None):
    client = TestClient(app, base_url=ORIGIN)
    if email:
        client.cookies.set(
            email_auth.EMAIL_SESSION_COOKIE,
            email_auth._sign_session(email),
        )
    return client


def test_devices_require_signed_login_on_all_endpoints(auth):
    with _client(None) as client:
        assert client.get("/api/account/devices").status_code == 401
        assert client.post("/api/account/devices", headers={"Origin": ORIGIN},
                           json={"name": "Samsung", "platform": "android"}).status_code == 401
        assert client.delete(
            "/api/account/devices/" + "Z" * 24,
            headers={"Origin": ORIGIN},
        ).status_code == 401


def test_device_records_are_private_and_delete_is_not_disconnect(auth, monkeypatch):
    stored = {}

    def add(owner, name, platform):
        key="a" * 24 if not stored else "b" * 24
        stored.setdefault(owner, []).append({
            "id": key, "name": name, "platform": platform,
            "created_at": datetime.now(UTC).isoformat(),
        })
        return {"id": key, "name": name, "platform": platform}

    def fetch(owner):
        return list(stored.get(owner, []))

    def remove(owner, identifier):
        before=stored.get(owner, [])
        remain=[r for r in before if r["id"] != identifier]
        stored[owner]=remain
        return len(remain) < len(before)

    monkeypatch.setattr(device_registry, "_create", add)
    monkeypatch.setattr(device_registry, "_read", fetch)
    monkeypatch.setattr(device_registry, "_remove", remove)
    with _client("alice@example.com") as alice:
        assert alice.post(
            "/api/account/devices",
            json={"name": "Samsung", "platform": "android"},
        ).status_code == 403  # Cross-origin protection
        created=alice.post(
            "/api/account/devices", headers={"Origin": ORIGIN},
            json={"name": "  Мой Samsung  ", "platform": "android"},
        )
        assert created.status_code == 201
        identifier=created.json()["id"]
        assert created.json()["name"] == "Мой Samsung"
        result=alice.get("/api/account/devices")
        assert result.status_code == 200
        assert result.json()["source"] == "customer_managed_labels"
        assert result.json()["live_sessions_available"] is False
        assert result.json()["record_limit"] == 12
        assert len(result.json()["items"]) == 1
        assert "example.com" not in result.text
    with _client("bob@example.com") as bob:
        assert bob.get("/api/account/devices").json()["items"] == []
        assert bob.delete(
            "/api/account/devices/" + identifier,
            headers={"Origin": ORIGIN},
        ).status_code == 404
    with _client("alice@example.com") as alice:
        deleted=alice.delete(
            "/api/account/devices/" + identifier,
            headers={"Origin": ORIGIN},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"removed": True, "vpn_disconnected": False}
        assert alice.get("/api/account/devices").json()["items"] == []


def test_device_inputs_never_accept_secrets_or_unbounded_values(auth, monkeypatch):
    monkeypatch.setattr(
        device_registry, "_create",
        lambda *_args: {"id": "abc" * 8},
    )
    with _client("alice@example.com") as client:
        for bad in (
            {"name": "vless://example", "platform": "android"},
            {"name": "https://example.com", "platform": "android"},
            {"name": "contains\nnewline", "platform": "android"},
            {"name": "x" * 41, "platform": "android"},
            {"name": " ", "platform": "android"},
            {"name": "Laptop", "platform": "imaginary"},
        ):
            result=client.post(
                "/api/account/devices",
                headers={"Origin": ORIGIN},
                json=bad,
            )
            assert result.status_code == 422, bad
        assert client.post(
            "/api/account/devices", headers={"Origin": ORIGIN},
            json={"name": "PC", "platform": "windows", "owner_hash": "attacker"},
        ).status_code == 422


def test_database_enforces_registration_cap_with_lock(auth, monkeypatch):
    queries=[]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params=()):
            queries.append((query, params))

        def fetchone(self):
            return (12,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(device_registry.psycopg, "connect",
                        lambda *_args, **_kwargs: Connection())
    with pytest.raises(HTTPException) as error:
        device_registry._create("a" * 64, "Laptop", "windows")
    assert error.value.status_code == 409
    assert any("pg_advisory_xact_lock" in query for query, _ in queries)
    assert not any("INSERT INTO vainah_device_labels" in query for query, _ in queries)


def test_registry_frontend_has_strict_security_and_truthful_description():
    with TestClient(app) as client:
        page=client.get("/my-devices.html")
        assert page.status_code == 200
        assert "noindex" in page.headers["x-robots-tag"]
        assert "no-store" in page.headers["cache-control"]
        assert "unsafe-inline" not in page.headers["content-security-policy"]
        assert 'id="vd-form"' in page.text
        assert "не отключает VPN" in page.text
    script=(SITE / "my-devices.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "/api/account/devices" in script
    assert "vpn_disconnected!==false" in script
    assert re.search(r"window\.confirm\(", script)


def test_rename_device_is_owner_scoped_and_does_not_touch_vpn(auth, monkeypatch):
    saved = {}
    def rename(owner, device_id, name):
        if (owner, device_id) not in saved:
            return False
        saved[(owner, device_id)] = name
        return True
    monkeypatch.setattr(device_registry, "_rename", rename)
    identifier = "d" * 24
    with _client("alice@example.com") as alice:
        # Use a test-only map without exposing hashed ids.
        captured = []
        original_rename = device_registry._rename
        def set_owner_and_rename(owner, device_id, name):
            captured.append(owner)
            if not saved and not captured[:-1]:
                saved[(owner, device_id)] = "Old name"
            return original_rename(owner, device_id, name)
        monkeypatch.setattr(device_registry, "_rename", set_owner_and_rename)
        assert alice.patch("/api/account/devices/" + identifier,
                           json={"name": "Desktop"}).status_code == 403
        response = alice.patch("/api/account/devices/" + identifier,
                               headers={"Origin": ORIGIN},
                               json={"name": "Desktop"})
        assert response.status_code == 200
        assert response.json() == {
            "renamed": True, "name": "Desktop", "vpn_disconnected": False
        }
        assert saved[(captured[-1], identifier)] == "Desktop"
        for invalid in ("vless://secret", "https://secret.test", "   ", "A" * 41):
            assert alice.patch("/api/account/devices/" + identifier,
                               headers={"Origin": ORIGIN},
                               json={"name": invalid}).status_code == 422
    with _client("bob@example.com") as bob:
        response = bob.patch("/api/account/devices/" + identifier,
                             headers={"Origin": ORIGIN},
                             json={"name": "Intruder"})
        assert response.status_code == 404
    source = (SITE / "my-devices.js").read_text(encoding="utf-8")
    assert "method:'PATCH'" in source
    assert "vpn_disconnected!==false" in source
    assert "innerHTML" not in source
