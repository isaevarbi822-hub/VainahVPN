"""Modern Telegram OpenID Connect login with state + PKCE + RS256 validation.

This is independent of the deprecated iframe widget. Client credentials are
entered only in Render and never returned to the browser or saved in cookies.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .email_auth import EMAIL_SESSION_COOKIE
from .google_auth import _origin
from .telegram_auth import (
    BOT_USERNAME_RE,
    SESSION_COOKIE,
    SESSION_TTL,
    USER_ID_RE,
    make_session,
)

AUTH_ENDPOINT = "https://oauth.telegram.org/auth"
TOKEN_ENDPOINT = "https://oauth.telegram.org/token"
JWKS_ENDPOINT = "https://oauth.telegram.org/.well-known/jwks.json"
FLOW_COOKIE = "__Host-vainah_telegram_oidc_flow"
FLOW_LIFETIME = 600
router = APIRouter(prefix="/api/telegram-oidc", tags=["Telegram OpenID Connect"])


def _config() -> tuple[str, str, str] | None:
    client_id = os.environ.get("TELEGRAM_OIDC_CLIENT_ID", "").strip()
    client_secret = os.environ.get("TELEGRAM_OIDC_CLIENT_SECRET", "")
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    origin = _origin()
    if (not USER_ID_RE.fullmatch(client_id)
            or not 16 <= len(client_secret) <= 1024
            or len(secret) < 32 or not origin):
        return None
    return client_id, client_secret, origin


def _sign(value: str) -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    return hmac.new(
        secret.encode(),
        ("telegram-oidc-flow-v1\n" + value).encode(), hashlib.sha256,
    ).hexdigest()


def _make_flow(state: str, verifier: str, nonce: str) -> str:
    raw = json.dumps({
        "state": state, "verifier": verifier, "nonce": nonce,
        "expires": int(time.time()) + FLOW_LIFETIME,
    }, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()
    return encoded + "." + _sign(encoded)


def _read_flow(raw: str | None) -> dict | None:
    if not isinstance(raw, str) or len(raw) > 1024:
        return None
    try:
        data, signature = raw.rsplit(".", 1)
        if not hmac.compare_digest(signature, _sign(data)):
            return None
        decoded = json.loads(base64.urlsafe_b64decode(
            data + "=" * (-len(data) % 4),
        ))
        now = int(time.time())
        if (not isinstance(decoded, dict)
                or type(decoded.get("expires")) is not int
                or not now < decoded["expires"] <= now + FLOW_LIFETIME):
            return None
        if not all(
            isinstance(decoded.get(k), str) and 32 <= len(decoded[k]) <= 128
            for k in ("state", "verifier", "nonce")
        ):
            return None
        return decoded
    except (ValueError, TypeError, UnicodeDecodeError, KeyError):
        return None


def _failure(reason: str) -> RedirectResponse:
    result = RedirectResponse(
        "/account.html?login=telegram&telegram_error=" + reason,
        status_code=303,
    )
    result.delete_cookie(FLOW_COOKIE, httponly=True, secure=True, samesite="lax")
    result.headers["Cache-Control"] = "no-store"
    return result


@router.get("/config")
def config() -> dict:
    available = _config() is not None
    return {
        "available": available,
        "method": "openid_connect",
        "message": (
            "Новый Telegram OIDC доступен."
            if available else
            "Для нового входа нужны TELEGRAM_OIDC_CLIENT_ID и "
            "TELEGRAM_OIDC_CLIENT_SECRET из BotFather в Render."
        ),
    }


@router.get("/start")
def start() -> RedirectResponse:
    settings = _config()
    if settings is None:
        return _failure("not_configured")
    client_id, _client_secret, origin = settings
    state, nonce, verifier = (
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(48),
    )
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    params = {
        "client_id": client_id,
        "redirect_uri": origin + "/api/telegram-oidc/callback",
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "nonce": nonce,
    }
    response = RedirectResponse(
        AUTH_ENDPOINT + "?" + urlencode(params), status_code=302,
    )
    response.set_cookie(
        FLOW_COOKIE, _make_flow(state, verifier, nonce),
        max_age=FLOW_LIFETIME, httponly=True, secure=True,
        samesite="lax", path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def _verified_user(id_token: str, client_id: str, nonce: str) -> dict:
    if not isinstance(id_token, str) or not 20 < len(id_token) < 16000:
        raise ValueError("INVALID_ID_TOKEN")
    header = jwt.get_unverified_header(id_token)
    if header.get("alg") != "RS256":
        raise ValueError("ALGORITHM_NOT_ALLOWED")
    kid = header.get("kid")
    if not isinstance(kid, str) or not 1 <= len(kid) <= 128:
        raise ValueError("INVALID_KID")
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        response = await client.get(JWKS_ENDPOINT)
        response.raise_for_status()
        body = response.json()
    keys = body.get("keys") if isinstance(body, dict) else None
    if not isinstance(keys, list) or len(keys) > 50:
        raise ValueError("JWKS_INVALID")
    jwk = next(
        (key for key in keys if isinstance(key, dict) and key.get("kid") == kid
         and key.get("kty") == "RSA" and key.get("use", "sig") == "sig"),
        None,
    )
    if jwk is None:
        raise ValueError("KEY_NOT_FOUND")
    public_key = jwt.PyJWK.from_dict(jwk, algorithm="RS256").key
    claims = jwt.decode(
        id_token, key=public_key, algorithms=["RS256"],
        audience=client_id, issuer="https://oauth.telegram.org",
        options={"require": ["iss", "aud", "sub", "exp", "iat"]},
        leeway=30,
    )
    # Telegram docs include a stable Bot API id in the signed profile claim.
    telegram_id = str(claims.get("id", ""))
    if not USER_ID_RE.fullmatch(telegram_id):
        raise ValueError("TELEGRAM_PROFILE_ID_MISSING")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise ValueError("SUBJECT_MISSING")
    if claims.get("nonce") is not None and not hmac.compare_digest(
        str(claims["nonce"]), nonce,
    ):
        raise ValueError("NONCE_MISMATCH")
    username = claims.get("preferred_username", "")
    if not isinstance(username, str) or username and not BOT_USERNAME_RE.fullmatch(username):
        username = ""
    name = claims.get("given_name") or claims.get("name") or "Telegram"
    if not isinstance(name, str):
        name = "Telegram"
    return {
        "telegram_id": telegram_id,
        "username": username[:32],
        "first_name": name[:80],
    }


@router.get("/callback")
async def callback(
    request: Request, code: str = "", state: str = "", error: str = "",
) -> RedirectResponse:
    settings = _config()
    flow = _read_flow(request.cookies.get(FLOW_COOKIE))
    if settings is None:
        return _failure("not_configured")
    if flow is None or not state or not hmac.compare_digest(flow["state"], state):
        return _failure("invalid_state")
    if error:
        return _failure("cancelled")
    if not 1 <= len(code) <= 2048:
        return _failure("missing_code")
    client_id, client_secret, origin = settings
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                auth=(client_id, client_secret),
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "redirect_uri": origin + "/api/telegram-oidc/callback",
                    "code_verifier": flow["verifier"],
                },
            )
            response.raise_for_status()
            body = response.json()
        user = await _verified_user(body.get("id_token"), client_id, flow["nonce"])
    except (httpx.HTTPError, jwt.PyJWTError, ValueError, TypeError,
            AttributeError, KeyError):
        return _failure("verification_failed")
    result = RedirectResponse("/account.html?login=telegram&telegram=success", status_code=303)
    result.delete_cookie(FLOW_COOKIE, httponly=True, secure=True, samesite="lax")
    result.delete_cookie(EMAIL_SESSION_COOKIE, httponly=True, secure=True, samesite="lax")
    result.set_cookie(
        SESSION_COOKIE, make_session(user, os.environ["SESSION_SIGNING_KEY"]),
        httponly=True, secure=True, samesite="lax", path="/",
        max_age=SESSION_TTL,
    )
    result.headers["Cache-Control"] = "no-store"
    return result
