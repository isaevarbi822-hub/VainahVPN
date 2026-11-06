"""Read-only H1Cloud panel adapter ported from Vainah VPN's prior integration.

Node contract (announced by /api/health): GET /api/info?name=NAME, Bearer PANEL_API_TOKEN.
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
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .billing import _require_operator

PROBE_TELEGRAM_ID = "999999999999999999"
MAX_BODY_BYTES = 100_000
MAX_H1_EXPIRY_SECONDS = 4102444800


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
    if not re.fullmatch(r"[\x21-\x7e]+", token):
        raise H1PanelError("PANEL_TOKEN_INVALID")
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname
        port = parsed.port
        if (parsed.scheme != "https" or not host or parsed.username or
                parsed.password or parsed.query or parsed.fragment or
                parsed.path not in {"", "/", "/api", "/api/"} or
                (port is not None and port != 443
                 and not 1024 <= port <= 65535) or
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
    # H1Cloud management API may use a dedicated HTTPS port, distinct
    # from VLESS/Reality on 443. Preserve it for the actual API request.
    port_suffix = f":{port}" if port not in {None, 443} else ""
    return H1PanelSettings(
        origin=f"https://{host.lower()}{port_suffix}",
        token=token, prefix=prefix,
    )



def panel_tls_verify() -> ssl.SSLContext | bool:
    """Verify HTTPS by public roots or a deliberately configured private CA.

    Never disable certificate or hostname validation. A private H1Cloud
    management API may use a private CA: the operator can supply its CA
    certificate (public material) as PANEL_TLS_CA_PEM in Render.
    """
    pem = os.environ.get("PANEL_TLS_CA_PEM", "").strip()
    if not pem:
        return True
    if (len(pem) > 20_000 or not pem.startswith("-----BEGIN CERTIFICATE-----")
            or "-----END CERTIFICATE-----" not in pem
            or "PRIVATE KEY" in pem):
        raise H1PanelError("PANEL_CA_INVALID")
    try:
        return ssl.create_default_context(cadata=pem)
    except (ValueError, ssl.SSLError):
        raise H1PanelError("PANEL_CA_INVALID") from None



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


def client_expiry(record: dict) -> int:
    """Parse the documented Unix-second expiry without coercing malformed JSON."""
    value = record.get("expires_at")
    if type(value) is int:
        expiry = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value):
        expiry = int(value)
    else:
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    # Millisecond timestamps and unbounded dates must not appear active merely
    # because their integer value is far in the future.
    if not 0 <= expiry <= MAX_H1_EXPIRY_SECONDS:
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    return expiry


def client_disabled(record: dict) -> bool:
    banned, status = record.get("banned"), record.get("status")
    if ((banned is not None and type(banned) is not bool)
            or (status is not None and not isinstance(status, str))):
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    return banned is True or status in ("banned", "disabled")


MAX_TRAFFIC_BYTES = 2**63 - 1


def verified_traffic_usage(record: dict) -> dict:
    """Read optional provider counters; never infer traffic or device identifiers.

    A missing/invalid counter means unavailable, not zero. The traffic quota
    field is verified against H1Cloud's real 10-GiB trial post-check contract.
    """
    result = {"used_bytes": None, "limit_bytes": None}
    # Only explicit byte-valued keys; no ambiguous 'traffic' or 'usage' units.
    for field, key in (
        ("traffic_used_bytes", "used_bytes"),
        ("traffic_limit_bytes", "limit_bytes"),
    ):
        value = record.get(field)
        if type(value) is int and 0 <= value <= MAX_TRAFFIC_BYTES:
            # A zero limit is not proof of an unlimited plan.
            if key == "limit_bytes" and value == 0:
                continue
            result[key] = value
    return result


def parse_client_status(record: dict, *, now: float | None = None) -> dict:
    """Validate state fields from an already identity-checked panel profile.

    Return only safe status fields. Callers must separately match the exact
    client name and validate any private subscription link they intend to use.
    """
    if not isinstance(record, dict):
        raise H1PanelError("PANEL_INVALID_RESPONSE")
    expiry = client_expiry(record)
    banned = client_disabled(record)
    return {
        "active": not banned and expiry > (time.time() if now is None else now),
        "banned": banned,
        "expires_at": datetime.fromtimestamp(expiry, UTC).isoformat() if expiry else None,
        "traffic": verified_traffic_usage(record),
    }


async def _read_h1_client_name(
    name: str, *, transport: httpx.AsyncBaseTransport | None = None,
    now: float | None = None,
) -> dict:
    """Read a validated H1 username over verified TLS; redact response."""
    settings = panel_settings()
    if settings is None:
        return {"panel_ready": False, "found": False,
                "active": False, "expires_at": None}
    try:
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False, trust_env=False,
            verify=panel_tls_verify(), transport=transport
        ) as client:
            response = await client.get(
                f"{settings.origin}/api/info?{urlencode({'name': name})}",
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
    return {
        "panel_ready": True,
        "found": True,
        **parse_client_status(record, now=now),
    }


async def read_h1_status(
    telegram_id: str, *, transport: httpx.AsyncBaseTransport | None = None,
    now: float | None = None,
) -> dict:
    """Legacy Telegram-scoped user lookup."""
    if not re.fullmatch(r"[1-9][0-9]{0,17}", telegram_id):
        raise H1PanelError("TELEGRAM_ID_INVALID")
    settings = panel_settings()
    if settings is None:
        return {"panel_ready": False, "found": False,
                "active": False, "expires_at": None}
    return await _read_h1_client_name(
        settings.prefix + telegram_id, transport=transport, now=now
    )


async def read_h1_issued_client_status(
    client_name: str, *, transport: httpx.AsyncBaseTransport | None = None,
    now: float | None = None,
) -> dict:
    """Look up only Vainah-issued pseudonymous usernames, not arbitrary users."""
    if not re.fullmatch(r"vn[0-9a-f]{28}", client_name):
        raise H1PanelError("CLIENT_NAME_INVALID")
    return await _read_h1_client_name(
        client_name, transport=transport, now=now
    )


async def inspect_h1_panel(*,
                           transport: httpx.AsyncBaseTransport | None = None) -> dict:
    try:
        status = await read_h1_status(PROBE_TELEGRAM_ID, transport=transport)
    except H1PanelError as error:
        if error.code == "PANEL_UNAUTHORIZED":
            return {"ok": False, "panel": "reachable",
                    "authentication": "rejected"}
        if error.code in {"PANEL_URL_INVALID", "PANEL_PREFIX_INVALID", "PANEL_CA_INVALID", "PANEL_TOKEN_INVALID"}:
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


class H1ClientCheckRequest(BaseModel):
    """Exactly one H1 username selector; never put identifiers into URL logs."""

    model_config = ConfigDict(extra="forbid")

    telegram_id: str | None = Field(
        default=None, pattern=r"^[1-9][0-9]{0,17}$"
    )
    client_name: str | None = Field(
        default=None, pattern=r"^vn[0-9a-f]{28}$"
    )

    @model_validator(mode="after")
    def exactly_one_selector(self) -> H1ClientCheckRequest:
        if (self.telegram_id is None) == (self.client_name is None):
            raise ValueError("Provide exactly one H1 client selector")
        return self


@router.post("/h1cloud/client/check")
async def h1cloud_client_check(
    body: H1ClientCheckRequest,
    x_sandbox_token: str | None = Header(default=None),
) -> dict:
    """Operator-only read of one existing client. Never create or extend users.

    This intentionally returns no API response body, VLESS secret,
    subscription link, UUID, or device information.
    """
    _require_operator(x_sandbox_token)
    try:
        if body.client_name is not None:
            status = await read_h1_issued_client_status(body.client_name)
        else:
            status = await read_h1_status(body.telegram_id)
    except H1PanelError as exc:
        # Sanitized codes only; never expose the URL, token or provider text.
        raise HTTPException(status_code=503, detail=exc.code) from None
    return {
        "ok": status["panel_ready"],
        "found": status["found"],
        "active": status["active"],
        "banned": status.get("banned", False),
        "expires_at": status["expires_at"],
        "vpn_delivered": False,
    }
