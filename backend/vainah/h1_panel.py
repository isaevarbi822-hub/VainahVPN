"""Read-only H1Cloud panel adapter ported from Vainah VPN's prior integration.

Panel contract: GET /api/clients/{name}, Bearer PANEL_API_TOKEN.
The API response may contain VLESS secrets. Return only safe status fields;
never write, create clients, or disclose links/UUIDs/device identifiers.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Header

from .billing import _require_operator

PROBE_TELEGRAM_ID = "999999999999999999"
MAX_BODY_BYTES = 100_000


class H1PanelError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _network_error_code(error: httpx.RequestError) -> str:
    """Classify transport failures without exposing hostnames or tokens."""
    if isinstance(error, httpx.ConnectTimeout):
        return "PANEL_CONNECT_TIMEOUT"
    if isinstance(error, httpx.TimeoutException):
        return "PANEL_RESPONSE_TIMEOUT"
    if isinstance(error, httpx.RemoteProtocolError):
        return "PANEL_PROTOCOL_ERROR"
    if isinstance(error, httpx.ConnectError):
        # httpx/httpcore may wrap DNS or TLS errors in multiple causes.
        current: BaseException | None = error
        for _ in range(6):
            if current is None:
                break
            if isinstance(current, socket.gaierror):
                return "PANEL_DNS_FAILED"
            if isinstance(current, ssl.SSLError):
                return "PANEL_TLS_FAILED"
            current = current.__cause__ or current.__context__
        return "PANEL_CONNECT_FAILED"
    return "PANEL_UNREACHABLE"


@dataclass(frozen=True)
class H1PanelSettings:
    origin: str
    token: str
    prefix: str


def panel_settings() -> H1PanelSettings | None:
    raw_url = os.environ.get("PANEL_BASE_URL", "").strip()
    token = os.environ.get("PANEL_API_TOKEN", "").strip()
    if not raw_url or not token:
        return None
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname
        port = parsed.port
        if (parsed.scheme != "https" or not host or parsed.username or
                parsed.password or parsed.query or parsed.fragment or
                parsed.path not in {"", "/", "/api", "/api/"} or
                port not in {None, 443} or
                host.lower() in {"localhost"} or
                host.lower().endswith((".localhost", ".local", ".internal")) or
                not re.fullmatch(r"[A-Za-z0-9.-]{4,253}", host)):
            raise ValueError("bad url")
        # IP literals are not valid panel origins; block local network SSRF.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP host forbidden")
    except ValueError:
        raise H1PanelError("PANEL_URL_INVALID") from None
    prefix = os.environ.get("PANEL_CLIENT_PREFIX", "tg").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,24}", prefix):
        raise H1PanelError("PANEL_PREFIX_INVALID")
    return H1PanelSettings(
        origin=f"https://{host.lower()}", token=token, prefix=prefix
    )


def public_h1_status() -> dict:
    try:
        settings = panel_settings()
    except H1PanelError:
        return {"status": "error",
                "message": "Параметры панели H1Cloud требуют исправления."}
    if settings is None:
        return {"status": "not_connected",
                "message": "Панель H1Cloud не настроена для Python API."}
    return {"status": "configured",
            "message": "Настройки панели найдены. Проверка связи ещё не выполнена."}


async def read_h1_status(telegram_id: str, *,
                         transport: httpx.AsyncBaseTransport | None = None,
                         now: float | None = None) -> dict:
    if not re.fullmatch(r"[1-9][0-9]{0,17}", telegram_id):
        raise H1PanelError("TELEGRAM_ID_INVALID")
    settings = panel_settings()
    if settings is None:
        return {"panel_ready": False, "found": False,
                "active": False, "expires_at": None}
    name = settings.prefix + telegram_id
    try:
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False, trust_env=False,
            transport=transport
        ) as client:
            response = await client.get(
                f"{settings.origin}/api/clients/{name}",
                headers={"Authorization": f"Bearer {settings.token}",
                         "Accept": "application/json"},
            )
    except httpx.RequestError as exc:
        raise H1PanelError(_network_error_code(exc)) from None
    if response.status_code in (401, 403):
        raise H1PanelError("PANEL_UNAUTHORIZED")
    if response.status_code == 429:
        raise H1PanelError("PANEL_RATE_LIMITED")
    if 500 <= response.status_code <= 599:
        raise H1PanelError("PANEL_SERVER_ERROR")
    if (response.status_code not in (200, 404)
            or len(response.content) > MAX_BODY_BYTES):
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    try:
        payload = response.json()
    except ValueError:
        raise H1PanelError("PANEL_INVALID_RESPONSE") from None
    if not isinstance(payload, dict):
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    if response.status_code == 404 and payload.get("error") == "user_not_found":
        return {"panel_ready": True, "found": False,
                "active": False, "expires_at": None}
    if response.status_code != 200 or payload.get("ok") is not True:
        raise H1PanelError("PANEL_API_ERROR")
    record = payload.get("client")
    if not isinstance(record, dict) or record.get("name") != name:
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    try:
        expiry = int(record["expires_at"])
    except (TypeError, ValueError, KeyError, OverflowError):
        raise H1PanelError("PANEL_INVALID_RESPONSE") from None
    if expiry < 0 or expiry > 4102444800:
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    banned = record.get("banned") is True or record.get("status") in {
        "banned", "disabled",
    }
    return {
        "panel_ready": True,
        "found": True,
        "active": not banned and expiry > (time.time() if now is None else now),
        "banned": banned,
        "expires_at": datetime.fromtimestamp(
            expiry, UTC
        ).isoformat() if expiry else None,
    }


async def inspect_h1_panel(*,
                           transport: httpx.AsyncBaseTransport | None = None) -> dict:
    try:
        status = await read_h1_status(PROBE_TELEGRAM_ID, transport=transport)
    except H1PanelError as error:
        if error.code == "PANEL_UNAUTHORIZED":
            return {"ok": False, "panel": "reachable",
                    "authentication": "rejected"}
        if error.code in {"PANEL_URL_INVALID", "PANEL_PREFIX_INVALID"}:
            return {"ok": False, "panel": "invalid_configuration"}
        return {"ok": False, "panel": "unavailable",
                "reason": {
                    "PANEL_UNREACHABLE": "connection_failed",
                    "PANEL_CONNECT_FAILED": "connect_failed",
                    "PANEL_DNS_FAILED": "dns_failed",
                    "PANEL_TLS_FAILED": "tls_failed",
                    "PANEL_CONNECT_TIMEOUT": "connect_timeout",
                    "PANEL_RESPONSE_TIMEOUT": "response_timeout",
                    "PANEL_PROTOCOL_ERROR": "protocol_error",
                    "PANEL_RATE_LIMITED": "rate_limited",
                    "PANEL_SERVER_ERROR": "server_error",
                    "PANEL_INVALID_RESPONSE": "invalid_response",
                    "PANEL_API_ERROR": "api_error",
                }.get(error.code, "unknown_error")}
    if not status["panel_ready"]:
        return {"ok": False, "panel": "not_configured"}
    return {"ok": True, "panel": "reachable", "authentication": "accepted",
            "vpn_delivered": False}


router = APIRouter(prefix="/api/site/integrations", tags=["H1Cloud"])


@router.get("/h1cloud/check")
async def h1cloud_check(x_sandbox_token: str | None = Header(default=None)) -> dict:
    _require_operator(x_sandbox_token)
    # Read-only probe, never create users and never leak subscription URLs.
    return await inspect_h1_panel()
