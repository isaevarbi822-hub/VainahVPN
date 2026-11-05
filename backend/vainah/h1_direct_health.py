"""Unauthenticated read-only connectivity probe for H1Cloud direct endpoints.

The direct endpoint may serve plain HTTP. Never send PANEL_API_TOKEN,
cookies, merchant tokens or customer information to it. This module probes
only a documented public health route, to diagnose connectivity from Render.

This module does NOT make plain HTTP acceptable for provisioning.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

import httpx


class DirectHealthError(Exception):
    """Local configuration errors only; no secret URL/hostname in response."""


def _failure(reason: str, message: str, *, status: str = "error") -> dict:
    # This optional tokenless HTTP probe is independent of the authenticated
    # HTTPS management API. Never diagnose a token failure from its response.
    return {
        "status": status, "reason": reason, "message": message,
        "read_only": True, "api_token_sent": False,
        "protected_connection": False,
    }


def _direct_health_url() -> str | None:
    raw = os.environ.get("PANEL_DIRECT_HEALTH_URL", "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        host = parts.hostname
        port = parts.port
        if (
            parts.scheme != "http"
            or not host
            or not re.fullmatch(r"direct-[a-z0-9-]{3,50}\.h1cloud\.net", host)
            or not isinstance(port, int)
            or not 1024 <= port <= 65535
            or parts.path != "/api/health"
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("not a documented direct health endpoint")
    except ValueError:
        raise DirectHealthError("DIRECT_HEALTH_URL_INVALID") from None
    return raw


async def probe_direct_health(
    *, transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Return only coarse, non-sensitive connectivity results.

    No Authorization / Cookie headers. No redirects or environment proxy.
    The public health response may mention management endpoints: only
    boolean flags are exposed, not a raw list or any client data.
    """
    try:
        target = _direct_health_url()
    except DirectHealthError:
        return _failure("invalid_url", "Некорректный адрес прямой проверки H1Cloud.")
    if target is None:
        return {"status": "not_configured",
                "message": "Адрес прямой проверки H1Cloud не задан."}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=5),
            follow_redirects=False, trust_env=False, transport=transport,
        ) as session:
            response = await session.get(
                target, headers={"Accept": "application/json"}
            )
    except httpx.TimeoutException:
        return _failure(
            "timeout", "Render не дождался ответа от прямого H1Cloud API.",
            status="unavailable",
        )
    except httpx.RequestError:
        return _failure(
            "connection_failed",
            "Render не смог установить соединение с прямым H1Cloud API.",
            status="unavailable",
        )

    if response.status_code in {401, 403}:
        return _failure(
            "public_health_rejected",
            "Прямой HTTP health endpoint отклонил запрос без токена. "
            "Это не проверка токена защищённого H1Cloud API.",
        )
    if response.status_code != 200:
        return _failure(
            "unexpected_http_status",
            "Прямой адрес H1Cloud ответил, но health endpoint недоступен.",
        )
    if len(response.content) > 32768:
        return _failure("response_too_large", "Ответ health endpoint слишком велик.")
    try:
        data = response.json()
    except ValueError:
        return _failure("invalid_json", "H1Cloud вернул некорректный JSON.")
    if (not isinstance(data, dict) or data.get("ok") is not True
            or data.get("service") != "vpn-api"):
        return _failure(
            "health_contract_mismatch",
            "Ответ прямого API не похож на H1Cloud VPN API.",
        )

    routes = data.get("endpoints")
    if not isinstance(routes, list) or not all(isinstance(x, str) for x in routes):
        return _failure(
            "endpoints_contract_mismatch",
            "Список возможностей H1Cloud API не распознан.",
        )

    return {
        "status": "ok",
        "message": (
            "Render видит прямой H1Cloud VPN API. Проверено без токена "
            "по HTTP; для реальной выдачи требуется защищённый канал."
        ),
        "read_only": True,
        "api_token_sent": False,
        "protected_connection": False,
        "create_endpoint_listed": "POST /create" in routes,
        "extend_endpoint_listed": "PATCH /edit" in routes,
        "client_info_endpoint_listed": "GET /info?name=NAME" in routes,
    }
