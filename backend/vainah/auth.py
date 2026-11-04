"""Networkless Clerk session JWT verification for protected preview endpoints.

Requires the public PEM verification key, exact Clerk issuer, and known
frontend origins. No Clerk secret key is used and no token is logged.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
from fastapi import APIRouter, Header, HTTPException
from jwt import InvalidTokenError


@dataclass(frozen=True)
class ClerkAuthSettings:
    issuer: str
    public_key: str
    parties: frozenset[str]


def auth_settings() -> ClerkAuthSettings | None:
    issuer = os.environ.get("VAINAH_CLERK_ISSUER", "").strip().rstrip("/")
    key = (
        os.environ.get("VAINAH_CLERK_JWT_PUBLIC_KEY", "").strip()
        or os.environ.get("CLERK_JWT_KEY", "").strip()
    ).replace("\\n", "\n")
    raw_parties = os.environ.get("VAINAH_CLERK_AUTHORIZED_PARTIES", "")
    parties = frozenset(item.strip().rstrip("/") for item in raw_parties.split(",")
                        if item.strip())
    if not (issuer and key and parties):
        return None
    parsed = urlsplit(issuer)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path):
        return None
    for origin in parties:
        part = urlsplit(origin)
        if (part.scheme not in {"https", "http"} or not part.hostname
                or part.username or part.password or part.query or part.fragment
                or part.path or (part.scheme == "http"
                                  and part.hostname not in {"127.0.0.1", "localhost"})):
            return None
    if "-----BEGIN PUBLIC KEY-----" not in key:
        return None
    return ClerkAuthSettings(issuer=issuer, public_key=key, parties=parties)


def auth_public_config() -> dict:
    return {
        "provider": "clerk",
        "jwt_verification_ready": auth_settings() is not None,
        "login_ui_ready": False,
        "account_orders_ready": False,
        "message": "Серверная проверка Clerk JWT настроена."
        if auth_settings() else "Для Clerk JWT нужны публичный ключ, issuer и разрешённые адреса.",
    }


def verify_clerk_bearer(authorization: str | None) -> dict:
    settings = auth_settings()
    if settings is None:
        raise HTTPException(503, "CLERK_VERIFICATION_NOT_CONFIGURED")
    if not authorization or not re.fullmatch(r"Bearer [A-Za-z0-9_\-.]+", authorization):
        raise HTTPException(401, "AUTH_BEARER_REQUIRED")
    token = authorization[7:]
    if len(token) > 8192:
        raise HTTPException(401, "AUTH_INVALID")
    try:
        data = jwt.decode(
            token,
            settings.public_key,
            algorithms=["RS256"],
            issuer=settings.issuer,
            options={
                "verify_aud": False,
                "require": ["iss", "sub", "sid", "exp", "iat", "nbf"],
            },
            leeway=5,
        )
    except (InvalidTokenError, ValueError, TypeError):
        raise HTTPException(401, "AUTH_INVALID") from None
    if not isinstance(data, dict):
        raise HTTPException(401, "AUTH_INVALID")
    if (data.get("azp") not in settings.parties
            or not isinstance(data.get("sub"), str)
            or not re.fullmatch(r"user_[A-Za-z0-9]+", data["sub"])
            or not isinstance(data.get("sid"), str)
            or not re.fullmatch(r"sess_[A-Za-z0-9]+", data["sid"])
            or data.get("sts") == "pending"):
        raise HTTPException(401, "AUTH_INVALID")
    return {"provider": "clerk", "user_id": data["sub"],
            "authenticated": True, "orders_connected": False,
            "vpn_delivered": False}


router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get("/config")
def public_auth_config() -> dict:
    return auth_public_config()


@router.get("/me")
def account_me(authorization: str | None = Header(default=None)) -> dict:
    # Never echo raw JWT, session ID or untrusted token claims.
    return verify_clerk_bearer(authorization)
