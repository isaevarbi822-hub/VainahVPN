"""Signed Telegram Login Widget authentication for Vainah VPN on Render.

No Telegram ID or username supplied by the browser is trusted without
Telegram's HMAC signature. Sessions are HttpOnly, Secure and SameSite=Lax.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

SESSION_COOKIE = "__Host-vainah_session"
SESSION_TTL = 12 * 3600
LOGIN_TTL = 600
BOT_USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
BOT_TOKEN_RE = re.compile(r"[0-9]{5,15}:[A-Za-z0-9_-]{20,}")
USER_ID_RE = re.compile(r"[1-9][0-9]{0,17}")
HASH_RE = re.compile(r"[a-fA-F0-9]{64}")
ALLOWED_KEYS = frozenset({
    "id", "first_name", "last_name", "username", "photo_url",
    "auth_date", "hash", "allows_write_to_pm",
})


def _settings() -> tuple[str, str, str] | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    username = os.environ.get("TELEGRAM_BOT_USERNAME", "VainahVPNbot").removeprefix("@")
    if not (BOT_TOKEN_RE.fullmatch(token) and len(secret) >= 32
            and BOT_USERNAME_RE.fullmatch(username)):
        return None
    return token, secret, username


def _email_login_available() -> bool:
    # Late import avoids circular dependency with the shared origin checker.
    from .email_auth import ready

    return ready()


def public_config() -> dict:
    settings = _settings()
    return {
        "available": settings is not None,
        "bot_username": settings[2] if settings else None,
        "email_login_available": _email_login_available(),
        "message": (
            "Telegram Login настроен. Необходим разрешённый домен в BotFather."
            if settings else
            "Для входа нужны TELEGRAM_BOT_TOKEN и SESSION_SIGNING_KEY в Render."
        ),
    }


def verify_login(data: object, bot_token: str, *, now: int | None = None) -> dict | None:
    if not isinstance(data, dict) or set(data) - ALLOWED_KEYS:
        return None
    if not bot_token or not USER_ID_RE.fullmatch(str(data.get("id", ""))):
        return None
    date = data.get("auth_date")
    if not re.fullmatch(r"[0-9]{10}", str(date or "")):
        return None
    current = int(time.time()) if now is None else now
    timestamp = int(date)
    if timestamp > current + 60 or current - timestamp > LOGIN_TTL:
        return None
    provided_hash = data.get("hash", "")
    if not isinstance(provided_hash, str) or not HASH_RE.fullmatch(provided_hash):
        return None
    if any(
        key != "hash" and not isinstance(value, (str, int, bool))
        for key, value in data.items()
    ):
        return None
    if "first_name" not in data or not isinstance(data["first_name"], str):
        return None
    if len(data["first_name"]) > 100 or len(str(data.get("username", ""))) > 64:
        return None

    def format_value(value: object) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    checked = "\n".join(
        f"{key}={format_value(data[key])}"
        for key in sorted(data)
        if key != "hash"
    )
    try:
        checked_bytes = checked.encode("utf-8")
    except UnicodeEncodeError:
        return None
    expected = hmac.new(
        hashlib.sha256(bot_token.encode("utf-8")).digest(),
        checked_bytes,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, provided_hash.lower()):
        return None
    return {
        "telegram_id": str(data["id"]),
        "username": str(data.get("username", ""))[:32],
        "first_name": data["first_name"][:80],
    }


def _session_signature(data: str, secret: str) -> str:
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def make_session(user: dict, secret: str, *, now: int | None = None) -> str:
    timestamp = int(time.time()) if now is None else now
    data = json.dumps({
        "v": 1,
        "id": user["telegram_id"],
        "username": user.get("username", "")[:32],
        "first_name": user.get("first_name", "")[:80],
        "exp": timestamp + SESSION_TTL,
    }, separators=(",", ":"), ensure_ascii=False)
    payload = base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()
    return payload + "." + _session_signature(payload, secret)


def read_session(token: str | None, secret: str, *, now: int | None = None) -> dict | None:
    if not isinstance(token, str) or len(token) > 1500 or not secret:
        return None
    match = re.fullmatch(r"([A-Za-z0-9_-]+)\.([0-9a-f]{64})", token)
    if not match or not hmac.compare_digest(
        _session_signature(match.group(1), secret), match.group(2)
    ):
        return None
    try:
        payload = match.group(1)
        raw = base64.urlsafe_b64decode(
            payload + "=" * (-len(payload) % 4)
        )
        data = json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    timestamp = int(time.time()) if now is None else now
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    expiry = data.get("exp")
    uid = data.get("id")
    if (not USER_ID_RE.fullmatch(str(uid or ""))
            or type(expiry) is not int
            or not timestamp < expiry <= timestamp + SESSION_TTL
            or not isinstance(data.get("username"), str)
            or not isinstance(data.get("first_name"), str)):
        return None
    return {"telegram_id": uid, "username": data["username"][:32],
            "first_name": data["first_name"][:80]}


def current_user(request: Request) -> dict | None:
    settings = _settings()
    if settings is not None:
        return read_session(request.cookies.get(SESSION_COOKIE), settings[1])
    # New BotFather OIDC creates the same signed Telegram customer session,
    # but must not require a deprecated legacy bot token to read that cookie.
    # Import lazily to avoid a cycle with telegram_oidc.make_session.
    from .telegram_oidc import _config as oidc_config

    if oidc_config() is None:
        return None
    return read_session(
        request.cookies.get(SESSION_COOKIE),
        os.environ.get("SESSION_SIGNING_KEY", ""),
    )


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "TELEGRAM_LOGIN_REQUIRED")
    return user


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    allowed = os.environ.get(
        "PUBLIC_SITE_ORIGIN", "https://vainahvpn-python-preview.onrender.com"
    ).rstrip("/")
    try:
        parsed = urlsplit(origin)
    except ValueError:
        raise HTTPException(403, "INVALID_ORIGIN") from None
    if (not origin or parsed.scheme != "https" or
            origin.rstrip("/") != allowed):
        raise HTTPException(403, "INVALID_ORIGIN")


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    data: dict | None = None


router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


@router.get("/config")
def config() -> dict:
    return public_config()


@router.get("/account")
def account(request: Request) -> dict:
    user = current_user(request)
    return {"authenticated": bool(user), "user": user}


@router.post("/account")
async def account_action(request: Request, body: LoginBody, response: Response) -> dict:
    require_same_origin(request)
    if body.action == "logout":
        response.delete_cookie(
            "__Host-vainah_email_session", secure=True, httponly=True,
            samesite="lax", path="/",
        )
        response.delete_cookie(
            SESSION_COOKIE, secure=True, httponly=True, samesite="lax",
            path="/",
        )
        return {"authenticated": False, "user": None}
    if body.action != "login" or not isinstance(body.data, dict):
        raise HTTPException(400, "INVALID_ACTION")
    settings = _settings()
    if settings is None:
        raise HTTPException(503, "TELEGRAM_LOGIN_NOT_CONFIGURED")
    if len(json.dumps(body.data)) > 4096:
        raise HTTPException(413, "TELEGRAM_LOGIN_TOO_LARGE")
    user = verify_login(body.data, settings[0])
    if not user:
        raise HTTPException(403, "TELEGRAM_AUTH_INVALID")
    # A new Telegram login replaces any previous email-only session.
    response.delete_cookie(
        "__Host-vainah_email_session", secure=True, httponly=True,
        samesite="lax", path="/",
    )
    response.set_cookie(
        SESSION_COOKIE,
        make_session(user, settings[1]),
        secure=True, httponly=True, samesite="lax",
        max_age=SESSION_TTL, path="/",
    )
    return {"authenticated": True, "user": user}
