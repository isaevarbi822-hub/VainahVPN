"""Verify Clerk JWTs offline; never use unsigned identity claims."""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from vainah.main import app

client = TestClient(app)
ISSUER = "https://preview-example.clerk.accounts.dev"
ORIGIN = "https://vainahvpn-python-preview.onrender.com"


@pytest.fixture
def clerk_keys(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setenv("VAINAH_CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("VAINAH_CLERK_JWT_PUBLIC_KEY", public)
    monkeypatch.setenv("VAINAH_CLERK_AUTHORIZED_PARTIES", ORIGIN)
    return private


def token_for(private, **overrides):
    timestamp = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "user_ABC123",
        "sid": "sess_ABC123",
        "azp": ORIGIN,
        "iat": timestamp - 10,
        "nbf": timestamp - 10,
        "exp": timestamp + 120,
    }
    claims.update(overrides)
    return jwt.encode(claims, private, algorithm="RS256")


def test_auth_public_config_no_secrets(monkeypatch):
    monkeypatch.delenv("VAINAH_CLERK_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("CLERK_JWT_KEY", raising=False)
    config = client.get("/api/auth/config")
    assert config.status_code == 200
    assert config.json()["jwt_verification_ready"] is False
    assert config.json()["login_ui_ready"] is False
    assert client.get("/api/auth/me").status_code == 503


def test_valid_session_access_is_verified_but_no_vpn_is_delivered(clerk_keys):
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer " + token_for(clerk_keys)}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["user_id"] == "user_ABC123"
    assert result["provider"] == "clerk"
    assert result["orders_connected"] is False
    assert result["vpn_delivered"] is False
    assert "sid" not in result
    assert client.get("/api/auth/config").json()["jwt_verification_ready"] is True


@pytest.mark.parametrize("override", [
    {"iss": "https://attacker.example"},
    {"azp": "https://untrusted.example"},
    {"azp": None},
    {"exp": 1},
    {"nbf": 4102444800},
    {"sub": "attacker"},
    {"sid": "untrusted"},
    {"sts": "pending"},
])
def test_rejects_invalid_signed_clerk_sessions(clerk_keys, override):
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer " + token_for(clerk_keys, **override)},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "AUTH_INVALID"


def test_rejects_forged_malformed_and_missing_bearer(clerk_keys):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get(
        "/api/auth/me", headers={"Authorization": "Bearer fake.fake.fake"}
    ).status_code == 401
    assert client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer " + jwt.encode(
            {"iss": ISSUER, "sub": "user_FAKED", "exp": int(time.time()) + 100},
            "attacker-secret",
            algorithm="HS256",
        )},
    ).status_code == 401
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer " + token_for(other_key)},
    ).status_code == 401


def test_rejects_missing_required_claims(clerk_keys):
    timestamp = int(time.time())
    value = jwt.encode({
        "iss": ISSUER,
        "sub": "user_ABC123",
        "azp": ORIGIN,
        "iat": timestamp - 1,
        "nbf": timestamp - 1,
        "exp": timestamp + 120,
    }, clerk_keys, algorithm="RS256")
    assert client.get(
        "/api/auth/me", headers={"Authorization": "Bearer " + value}
    ).status_code == 401
