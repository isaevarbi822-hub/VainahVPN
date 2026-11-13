"""Google OIDC flow: disabled-by-default, signed state, PKCE, verified ID token."""

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

from vainah import google_auth
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
CLIENT_ID = "123456789-example.apps.googleusercontent.com"
CLIENT_SECRET = "test-oauth-secret-not-a-live-key"
SESSION_SECRET = "test-session-signing-secret-long-enough-for-all-tests"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("SESSION_SIGNING_KEY", SESSION_SECRET)


def test_google_config_disabled_if_credentials_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with TestClient(app, base_url=ORIGIN) as client:
        config = client.get("/api/google/config")
        assert config.status_code == 200
        assert config.json()["available"] is False
        unavailable = client.get("/api/google/start", follow_redirects=False)
        assert unavailable.status_code == 303
        assert "google_error=not_configured" in unavailable.headers["location"]
        assert google_auth.STATE_COOKIE not in unavailable.cookies


def test_google_start_is_pkce_nonce_cookie_and_origin_locked(configured):
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/google/config").json()["available"] is True
        start = client.get("/api/google/start", follow_redirects=False)
        assert start.status_code == 302
        url = urlsplit(start.headers["location"])
        assert url.scheme == "https"
        assert url.netloc == "accounts.google.com"
        values = parse_qs(url.query)
        assert values["scope"] == ["openid email"]
        assert values["response_type"] == ["code"]
        assert values["redirect_uri"] == [ORIGIN + "/api/google/callback"]
        assert values["code_challenge_method"] == ["S256"]
        cookie = start.cookies[google_auth.STATE_COOKIE]
        flow = google_auth._unpack_flow(cookie)
        assert flow["state"] == values["state"][0]
        assert flow["nonce"] == values["nonce"][0]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(flow["verifier"].encode()).digest()
        ).rstrip(b"=").decode()
        assert challenge == values["code_challenge"][0]
        assert "HttpOnly" in start.headers["set-cookie"]
        assert "Secure" in start.headers["set-cookie"]
        assert "SameSite=lax" in start.headers["set-cookie"]
        assert CLIENT_SECRET not in start.headers["location"]
        assert "no-store" in start.headers["cache-control"]


def test_google_callback_rejects_forged_state_before_network(configured, monkeypatch):
    calls = []

    class ForbiddenClient:
        def __init__(self, *args, **kwargs):
            calls.append("called")

    monkeypatch.setattr(google_auth.httpx, "AsyncClient", ForbiddenClient)
    with TestClient(app, base_url=ORIGIN) as client:
        start = client.get("/api/google/start", follow_redirects=False)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        reply = client.get(
            "/api/google/callback", params={"code": "fake", "state": state + "x"},
            follow_redirects=False,
        )
        assert reply.status_code == 303
        assert "invalid_state" in reply.headers["location"]
        assert not calls
        assert client.get("/api/email-auth/account").json()["authenticated"] is False
        assert google_auth._unpack_flow(start.cookies[google_auth.STATE_COOKIE] + "x") is None


def test_google_callback_creates_only_verified_email_session(configured, monkeypatch):
    exchanges = []

    class FakeTokenResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id_token": "verified-token-placeholder"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, data):
            exchanges.append((url, data))
            return FakeTokenResponse()

    verified = []

    async def check(token, audience, nonce):
        verified.append((token, audience, nonce))
        return "verified@example.com"

    monkeypatch.setattr(google_auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(google_auth, "_verified_email", check)
    with TestClient(app, base_url=ORIGIN) as client:
        start = client.get("/api/google/start", follow_redirects=False)
        params = parse_qs(urlsplit(start.headers["location"]).query)
        flow = google_auth._unpack_flow(start.cookies[google_auth.STATE_COOKIE])
        callback = client.get(
            "/api/google/callback",
            params={"code": "one-time-code", "state": params["state"][0]},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["location"] == (
            "/account.html?login=google&google=success"
        )
        assert "HttpOnly" in callback.headers["set-cookie"]
        assert "Secure" in callback.headers["set-cookie"]
        assert exchanges[0][0] == google_auth.TOKEN_ENDPOINT
        assert exchanges[0][1]["code_verifier"] == flow["verifier"]
        assert exchanges[0][1]["redirect_uri"] == ORIGIN + "/api/google/callback"
        assert exchanges[0][1]["client_secret"] == CLIENT_SECRET
        assert verified == [(
            "verified-token-placeholder", CLIENT_ID, flow["nonce"],
        )]
        account = client.get("/api/email-auth/account").json()
        assert account == {
            "authenticated": True,
            "user": {"auth_method": "email", "email": "verified@example.com"},
        }
        assert CLIENT_SECRET not in callback.headers["location"]


def test_id_token_cryptographically_verified_against_google_keys(configured, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    def b64(number):
        raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk = {"kty": "RSA", "use": "sig", "kid": "google-key-1",
           "alg": "RS256", "n": b64(numbers.n), "e": b64(numbers.e)}

    class JWKSResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": [jwk]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            assert url == google_auth.JWKS_ENDPOINT
            return JWKSResponse()

    monkeypatch.setattr(google_auth.httpx, "AsyncClient", FakeClient)
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com", "aud": CLIENT_ID,
        "sub": "google-user-123456", "email": "USER@EXAMPLE.COM",
        "email_verified": True, "iat": now - 10, "exp": now + 300,
        "nonce": "expected-nonce",
    }

    def signed(**changes):
        return jwt.encode(
            {**claims, **changes}, private_key,
            algorithm="RS256", headers={"kid": "google-key-1"},
        )

    assert asyncio.run(google_auth._verified_email(
        signed(), CLIENT_ID, "expected-nonce"
    )) == "user@example.com"

    for changes, nonce in (
        ({"aud": "other-client.apps.googleusercontent.com"}, "expected-nonce"),
        ({"email_verified": False}, "expected-nonce"),
        ({"iss": "https://attacker.example"}, "expected-nonce"),
        ({"exp": now - 120}, "expected-nonce"),
        ({}, "wrong-nonce"),
        ({"azp": "other-client.apps.googleusercontent.com"}, "expected-nonce"),
    ):
        with pytest.raises((jwt.PyJWTError, ValueError)):
            asyncio.run(google_auth._verified_email(
                signed(**changes), CLIENT_ID, nonce
            ))
