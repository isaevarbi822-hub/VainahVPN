"""Read-only, privacy-preserving Vainah Check API.

Infrastructure checks cover the control plane only. A successful H1Cloud API
probe does NOT establish real VPN server uptime, RTT, capacity or egress.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from .customer_portal import overview as account_overview
from .db_health import database_status
from .integration_status import integration_status

router = APIRouter(tags=["Vainah Check"])

PUBLIC_STATUSES = {
    "ok": "ok",
    "error": "attention",
    "unavailable": "unknown",
    "sandbox": "unknown",
    "configured": "unknown",
    "not_connected": "unknown",
    "not_configured": "unknown",
}
CHECK_TITLES = {
    "api": "Сайт и Python API",
    "database": "База данных",
    "h1": "H1Cloud API",
    "rollypay": "RollyPay API",
    "webhook": "Настройка webhook",
}
CHECK_NOTES = {
    "api": "Сайт отвечает на запрос. Это не проверка VPN-туннеля.",
    "database": "Проверяется доступность базы для сайта, а не каждый заказ.",
    "h1": "Проверяется API управления H1Cloud, не отдельные VPN-серверы.",
    "rollypay": "Проверяется ответ API кассы; платежи этим не тестируются.",
    "webhook": "Проверяется конфигурация. Это не подтверждение доставки webhook.",
}


def summarize_services(database: dict, integrations: dict) -> dict:
    raw = {"api": {"status": "ok"}, "database": database, **integrations}
    checks = []
    for key in ("api", "database", "h1", "rollypay", "webhook"):
        value = raw.get(key)
        code = value.get("status") if isinstance(value, dict) else None
        checks.append({
            "id": key,
            "title": CHECK_TITLES[key],
            "state": PUBLIC_STATUSES.get(code, "unknown"),
            "note": CHECK_NOTES[key],
        })
    ok = sum(x["state"] == "ok" for x in checks)
    attention = sum(x["state"] == "attention" for x in checks)
    return {
        "scope": "control_plane_only",
        "observed_at": datetime.now(UTC).isoformat(),
        "provider_checks_cached_up_to_seconds": 180,
        "summary": ("attention" if attention else "partial" if ok < len(checks)
                    else "control_plane_checks_ok"),
        "checks": checks,
        "verified_vpn_tunnel": False,
        "server_latency_measured": False,
        "payment_completion_tested": False,
    }


@router.get("/api/site/check/summary")
async def public_check_summary() -> dict:
    # Reuse the existing cached provider probes. No new money flows, no
    # H1 user provisioning and no raw upstream secrets returned to visitors.
    import asyncio

    db, providers = await asyncio.gather(database_status(), integration_status())
    return summarize_services(db, providers)


def diagnose_account(data: dict) -> dict:
    """Build conservative decisions from the SAME owner-scoped account overview."""
    orders = data.get("orders")
    orders = orders if isinstance(orders, list) else []
    subscription = data.get("subscription")
    sub = subscription if isinstance(subscription, dict) else {}
    provider = data.get("h1cloud")
    h1 = provider if isinstance(provider, dict) else {}
    state = h1.get("status")
    paid = any(
        isinstance(item, dict) and item.get("paid") is True
        and item.get("delivered") is True
        for item in orders
    )
    confirmed = (
        sub.get("paid") is True
        and sub.get("status") == "delivered"
        and state == "active"
    )

    if not paid:
        headline = "Подтверждённая выданная подписка не найдена"
        level = "information"
        instruction = "Проверь историю заказов. Если оплата была, обратись в поддержку, не оплачивая повторно."
        code = "no_confirmed_delivery"
    elif state in ("unavailable", "not_configured", None):
        headline = "Сейчас нельзя проверить профиль H1Cloud"
        level = "unknown"
        instruction = "Попробуй обновить проверку позднее. Это не означает, что подписка истекла."
        code = "provider_unverified"
    elif state in ("inactive", "not_found"):
        headline = "H1Cloud не подтвердил активный профиль"
        level = "attention"
        instruction = "Покупка есть, но состояние профиля требует проверки. Обратись в поддержку с номером заказа из кабинета; не покупай второй раз."
        code = "paid_profile_not_active"
    elif confirmed:
        headline = "Оплаченный VPN-профиль активен по данным H1Cloud"
        level = "ok"
        instruction = "Это проверка профиля, но не соединения на твоём устройстве. При проблеме проверь приложение, сеть и импорт подписки."
        code = "paid_profile_active"
    else:
        headline = "Статус оплаты и профиль требуют уточнения"
        level = "unknown"
        instruction = "Проверь историю заказов и обратись в поддержку, если подключение не работает."
        code = "account_state_unverified"

    traffic = sub.get("traffic") if confirmed else None
    traffic = traffic if isinstance(traffic, dict) else {}
    used, limit = traffic.get("used_bytes"), traffic.get("limit_bytes")
    ratio = None
    if (type(used) is int and 0 <= used <= 2**63 - 1
            and type(limit) is int and 0 < limit <= 2**63 - 1):
        ratio = round(min(100, 100 * used / limit))
    return {
        "result": code,
        "level": level,
        "headline": headline,
        "next_step": instruction,
        "source": "owner_scoped_paid_orders_and_h1_read_only",
        "profile_checked": state in ("active", "inactive", "not_found"),
        "tunnel_tested": False,
        "traffic_used_percent": ratio,
        "expires_at": sub.get("expires_at") if confirmed else None,
        "support_path": "/support-center.html",
    }


@router.get("/api/account/connection-check")
async def customer_connection_check(request: Request) -> dict:
    # account_overview enforces a verified signed session and checks owner
    # purchases. Do NOT echo the private subscription URL or entire profile.
    data = await account_overview(request)
    return diagnose_account(data)


@router.get("/api/site/check/server-selection")
async def server_selection_readiness() -> dict:
    # No documented per-server health/RTT/capacity feed or client-side libbox
    # tunnel selector is available. Fail closed, never invent a "best" server.
    return {
        "available": False,
        "recommended_server": None,
        "locations": [],
        "latency_source": "not_connected",
        "vpn_sessions_readable": False,
        "reason": "H1Cloud пока не предоставляет проверенный список серверов с измеренной задержкой и нагрузкой. Автовыбор отключён.",
    }
