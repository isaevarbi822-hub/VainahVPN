"""Google OpenID Connect login using server-side authorization code + PKCE.

Only verified Google ID tokens create Vainah email sessions. Google access and
refresh tokens are never stored. Callback never accepts a client-supplied email.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .email_auth import (
    EMAIL_SESSION_COOKIE,
    SESSION_SECONDS,
    _sign_session,
    normalize_email,
)
from .telegram_auth import SESSION_COOKIE

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
STATE_COOKIE = "__Host-vainah_google_flow"
STATE_SECONDS = 600
MAX_ID_TOKEN_LENGTH = 16000

router = APIRouter(prefix="/api/google", tags=["Google Login"])


def _origin() -> str:
    origin = os.environ.get(
        "PUBLIC_SITE_ORIGIN", "https://vainahvpn-python-preview.onrender.com"
    ).rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        return ""
    return origin


def _config() -> tuple[str, str, str] | None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    origin = _origin()
    if (not client_id.endswith(".apps.googleusercontent.com")
            or len(client_id) > 256 or not client_secret
            or len(client_secret) > 1024 or len(secret) < 32 or not origin):
        return None
    return client_id, client_secret, origin


def _digest(value: str) -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    return hmac.new(secret.encode(), ("google-oauth-v1\n" + value).encode(),
                    hashlib.sha256).hexdigest()


def _pack_flow(state: str, nonce: str, verifier: str) -> str:
    payload = json.dumps({
        "state": state, "nonce": nonce, "verifier": verifier,
        "exp": int(time.time()) + STATE_SECONDS,
    }, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    return encoded + "." + _digest(encoded)


def _unpack_flow(value: str | None) -> dict | None:
    if not isinstance(value, str) or len(value) > 1024:
        return None
    try:
        payload, signature = value.rsplit(".", 1)
        if not hmac.compare_digest(_digest(payload), signature):
            return None
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        obj = json.loads(raw)
        if not isinstance(obj, dict) or type(obj.get("exp")) is not int:
            return None
        if not int(time.time()) < obj["exp"] <= int(time.time()) + STATE_SECONDS:
            return None
        for key in ("state", "nonce", "verifier"):
            text = obj.get(key)
            if not isinstance(text, str) or not 32 <= len(text) <= 128:
                return None
        return obj
    except (ValueError, TypeError, UnicodeDecodeError, KeyError):
        return None


def _end(message: str) -> RedirectResponse:
    response = RedirectResponse(
        url="/account.html?login=google&google_error=" + message,
        status_code=303,
    )
    response.delete_cookie(STATE_COOKIE, secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/config")
def config() -> dict:
    return {
        "available": _config() is not None,
        "method": "openid_connect",
        "message": ("Google Login настроен." if _config()
                    else "Для Google Login нужны GOOGLE_CLIENT_ID и "
                         "GOOGLE_CLIENT_SECRET в Render и Redirect URI в Google Cloud."),
    }


@router.get("/start")
def start() -> RedirectResponse:
    settings = _config()
    if settings is None:
        return _end("not_configured")
    client_id, _client_secret, origin = settings
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    parameters = {
        "client_id": client_id,
        "redirect_uri": origin + "/api/google/callback",
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    response = RedirectResponse(
        AUTH_ENDPOINT + "?" + urlencode(parameters), status_code=302
    )
    response.set_cookie(
        STATE_COOKIE, _pack_flow(state, nonce, verifier),
        max_age=STATE_SECONDS, secure=True, httponly=True,
        samesite="lax", path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def _verified_email(id_token: str, client_id: str, nonce: str) -> str:
    if not isinstance(id_token, str) or not 20 < len(id_token) < MAX_ID_TOKEN_LENGTH:
        raise ValueError("ID_TOKEN_INVALID")
    header = jwt.get_unverified_header(id_token)
    if header.get("alg") != "RS256":
        raise ValueError("ID_TOKEN_ALGORITHM")
    kid = header.get("kid")
    if not isinstance(kid, str) or not 1 <= len(kid) <= 128:
        raise ValueError("ID_TOKEN_KID")
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        response = await client.get(JWKS_ENDPOINT)
        response.raise_for_status()
        keys = response.json().get("keys", [])
    if not isinstance(keys, list) or len(keys) > 50:
        raise ValueError("JWKS_INVALID")
    key = next(
        (k for k in keys if isinstance(k, dict) and k.get("kid") == kid
         and k.get("kty") == "RSA" and k.get("use", "sig") == "sig"),
        None,
    )
    if key is None:
        raise ValueError("JWKS_KEY_NOT_FOUND")
    public_key = jwt.PyJWK.from_dict(key, algorithm="RS256").key
    claims = jwt.decode(
        id_token, key=public_key, algorithms=["RS256"],
        audience=client_id,
        issuer=["accounts.google.com", "https://accounts.google.com"],
        options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        leeway=30,
    )
    if (claims.get("azp") not in (None, client_id)
            or not hmac.compare_digest(str(claims.get("nonce", "")), nonce)
            or claims.get("email_verified") is not True
            or not isinstance(claims.get("sub"), str)
            or not 1 <= len(claims["sub"]) <= 255
            or not isinstance(claims.get("email"), str)):
        raise ValueError("GOOGLE_IDENTITY_UNVERIFIED")
    return normalize_email(claims["email"])


@router.get("/callback")
async def callback(
    request: Request, code: str = "", state: str = "", error: str = "",
) -> RedirectResponse:
    settings = _config()
    flow = _unpack_flow(request.cookies.get(STATE_COOKIE))
    if settings is None:
        return _end("not_configured")
    if (flow is None or not state or not hmac.compare_digest(state, flow["state"])):
        return _end("invalid_state")
    if error:
        return _end("cancelled")
    if not isinstance(code, str) or not 1 <= len(code) <= 2048:
        return _end("missing_code")
    client_id, client_secret, origin = settings
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": origin + "/api/google/callback",
                    "grant_type": "authorization_code",
                    "code_verifier": flow["verifier"],
                },
            )
            response.raise_for_status()
            body = response.json()
        email = await _verified_email(body.get("id_token"), client_id, flow["nonce"])
    except (httpx.HTTPError, HTTPException, ValueError, TypeError,
            AttributeError, KeyError, jwt.PyJWTError):
        return _end("verification_failed")
    result = RedirectResponse("/account.html?login=google&google=success", status_code=303)
    result.delete_cookie(STATE_COOKIE, secure=True, httponly=True, samesite="lax")
    result.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax")
    result.set_cookie(
        EMAIL_SESSION_COOKIE, _sign_session(email),
        max_age=SESSION_SECONDS, secure=True, httponly=True,
        samesite="lax", path="/",
    )
    result.headers["Cache-Control"] = "no-store"
    return result
