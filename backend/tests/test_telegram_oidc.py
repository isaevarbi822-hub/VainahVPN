"""Telegram modern OIDC: flow checks, PKCE and signed Telegram user sessions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from vainah import telegram_oidc
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
CLIENT_ID = "123456789"
CLIENT_SECRET = "fake-secret-for-local-tests-only"
SIGNING_SECRET = "only-in-tests-session-key-very-long"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_SECRET)
    monkeypatch.setenv("TELEGRAM_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("TELEGRAM_OIDC_CLIENT_SECRET", CLIENT_SECRET)


def test_telegram_oidc_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TELEGRAM_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_OIDC_CLIENT_SECRET", raising=False)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/telegram-oidc/config").json()["available"] is False
        begin = client.get("/api/telegram-oidc/start", follow_redirects=False)
        assert begin.status_code == 303
        assert "telegram_error=not_configured" in begin.headers["location"]


def test_telegram_oidc_start_pkce_and_allowed_redirect(configured):
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/telegram-oidc/config").json()["available"] is True
        begin = client.get("/api/telegram-oidc/start", follow_redirects=False)
        assert begin.status_code == 302
        url = urlsplit(begin.headers["location"])
        assert url.scheme == "https" and url.netloc == "oauth.telegram.org"
        values = parse_qs(url.query)
        assert values["client_id"] == [CLIENT_ID]
        assert values["scope"] == ["openid profile"]
        assert values["redirect_uri"] == [ORIGIN + "/api/telegram-oidc/callback"]
        assert values["code_challenge_method"] == ["S256"]
        flow = telegram_oidc._read_flow(begin.cookies[telegram_oidc.FLOW_COOKIE])
        assert flow["state"] == values["state"][0]
        assert flow["nonce"] == values["nonce"][0]
        digest = base64.urlsafe_b64encode(
            hashlib.sha256(flow["verifier"].encode()).digest()
        ).rstrip(b"=").decode()
        assert digest == values["code_challenge"][0]
        assert "HttpOnly" in begin.headers["set-cookie"]
        assert "Secure" in begin.headers["set-cookie"]
        assert "no-store" in begin.headers["cache-control"]
        assert CLIENT_SECRET not in begin.headers["location"]


def test_telegram_oidc_rejects_bad_state_without_exchanging_tokens(configured, monkeypatch):
    touched = []

    class Unexpected:
        def __init__(self, *args, **kwargs):
            touched.append("unexpected")

    monkeypatch.setattr(telegram_oidc.httpx, "AsyncClient", Unexpected)
    with TestClient(app, base_url=ORIGIN) as client:
        begin = client.get("/api/telegram-oidc/start", follow_redirects=False)
        flow = telegram_oidc._read_flow(begin.cookies[telegram_oidc.FLOW_COOKIE])
        reply = client.get(
            "/api/telegram-oidc/callback",
            params={"state": flow["state"] + "x", "code": "fake"},
            follow_redirects=False,
        )
        assert reply.status_code == 303
        assert "invalid_state" in reply.headers["location"]
        assert not touched
        assert client.get("/api/telegram/account").json()["authenticated"] is False


def test_telegram_oidc_success_reuses_signed_telegram_identity(configured, monkeypatch):
    requests = []

    class TokenResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id_token": "test-only-signed-identity"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, auth, data):
            requests.append((url, auth, data))
            return TokenResponse()

    seen = []

    async def verify(token, client_id, nonce):
        seen.append((token, client_id, nonce))
        return {
            "telegram_id": "987654321", "username": "testuser",
            "first_name": "Tester",
        }

    monkeypatch.setattr(telegram_oidc.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(telegram_oidc, "_verified_user", verify)
    with TestClient(app, base_url=ORIGIN) as client:
        begin = client.get("/api/telegram-oidc/start", follow_redirects=False)
        flow = telegram_oidc._read_flow(begin.cookies[telegram_oidc.FLOW_COOKIE])
        cb = client.get(
            "/api/telegram-oidc/callback",
            params={"state": flow["state"], "code": "test-one-use-code"},
            follow_redirects=False,
        )
        assert cb.status_code == 303
        assert cb.headers["location"] == (
            "/account.html?login=telegram&telegram=success"
        )
        assert "HttpOnly" in cb.headers["set-cookie"]
        assert requests[0][0] == telegram_oidc.TOKEN_ENDPOINT
        assert requests[0][1] == (CLIENT_ID, CLIENT_SECRET)
        assert requests[0][2]["code_verifier"] == flow["verifier"]
        assert requests[0][2]["redirect_uri"] == ORIGIN + "/api/telegram-oidc/callback"
        assert seen[0] == (
            "test-only-signed-identity", CLIENT_ID, flow["nonce"],
        )
        account = client.get("/api/telegram/account").json()
        assert account["authenticated"] is True
        assert account["user"]["telegram_id"] == "987654321"
        assert client.get("/api/email-auth/account").json()["authenticated"] is False


def test_telegram_oidc_verifies_rs256_id_token_identity(configured, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()

    def b64(num):
        raw = num.to_bytes((num.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwks = {"keys": [{
        "kid": "telegram-key-1", "kty": "RSA", "use": "sig",
        "n": b64(public.n), "e": b64(public.e),
    }]}

    class KeysResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return jwks

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            assert url == telegram_oidc.JWKS_ENDPOINT
            return KeysResponse()

    monkeypatch.setattr(telegram_oidc.httpx, "AsyncClient", FakeClient)
    now = int(time.time())
    good = {
        "iss": "https://oauth.telegram.org", "aud": CLIENT_ID,
        "sub": "pairwise-telegram-123", "id": 987654321,
        "preferred_username": "testuser", "given_name": "Test",
        "iat": now - 15, "exp": now + 300, "nonce": "expected-nonce",
    }

    def signed(**changes):
        return jwt.encode({**good, **changes}, private, algorithm="RS256",
                          headers={"kid": "telegram-key-1"})

    assert asyncio.run(telegram_oidc._verified_user(
        signed(), CLIENT_ID, "expected-nonce"
    )) == {
        "telegram_id": "987654321", "username": "testuser", "first_name": "Test",
    }
    for changes, expected_nonce in (
        ({"iss": "https://evil.example"}, "expected-nonce"),
        ({"aud": "wrong-client"}, "expected-nonce"),
        ({"exp": now - 100}, "expected-nonce"),
        ({"id": "not-a-number"}, "expected-nonce"),
        ({}, "incorrect-nonce"),
    ):
        with pytest.raises((jwt.PyJWTError, ValueError)):
            asyncio.run(telegram_oidc._verified_user(
                signed(**changes), CLIENT_ID, expected_nonce,
            ))
