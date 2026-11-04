"""Safe, read-only integration checks for Vainah's public status page.

This module never creates payments, VPN users or subscriptions. Provider
requests are cached to avoid causing traffic spikes when the status page is
visited. Only coarse status codes are returned, never provider response data.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time

from .billing import BillingSandbox, ProviderError
from .h1_panel import inspect_h1_panel, public_h1_status

CACHE_TTL_SECONDS = 180
_cached_until = 0.0
_cached_fingerprint = ""
_cached_report: dict | None = None
_lock = asyncio.Lock()


def _fingerprint() -> str:
    relevant = (
        "PANEL_BASE_URL", "PANEL_API_TOKEN", "PANEL_CLIENT_PREFIX",
        "ROLLYPAY_API_KEY", "ROLLYPAY_SIGNING_SECRET",
        "ROLLYPAY_TERMINAL_ID",
        "VAINAH_SHOP_SANDBOX_MODE",
    )
    text = "\n".join(os.environ.get(name, "") for name in relevant)
    return hashlib.sha256(text.encode()).hexdigest()


async def probe_h1() -> dict:
    config = public_h1_status()
    if config["status"] != "configured":
        return config
    try:
        report = await asyncio.wait_for(inspect_h1_panel(), timeout=10)
    except (TimeoutError, OSError):
        return {
            "status": "unavailable",
            "message": "Панель не ответила на безопасную проверку API. "
                       "Это не проверка VPN-серверов.",
        }
    if report.get("ok") is True and report.get("authentication") == "accepted":
        return {
            "status": "ok",
            "message": "H1Cloud API отвечает и принимает токен. "
                       "VPN-пользователь не создавался; серверы и выдача не проверены.",
        }
    if report.get("authentication") == "rejected":
        return {
            "status": "error",
            "message": "H1Cloud отклонил API-токен (HTTP 401/403). "
                       "Проверь PANEL_API_TOKEN.",
        }
    if report.get("panel") == "invalid_configuration":
        return {
            "status": "error",
            "message": "Проверь PANEL_BASE_URL и PANEL_CLIENT_PREFIX.",
        }
    reason = report.get("reason")
    reasons = {
        "connection_failed": "Нет ответа API панели H1Cloud.",
        "rate_limited": "H1Cloud ограничил частоту проверок.",
        "server_error": "API панели H1Cloud сообщил о временной ошибке.",
        "invalid_response": "API H1Cloud вернул ответ неожиданного формата.",
        "api_error": "H1Cloud вернул ошибку API. Доступ не подтверждён.",
    }
    return {
        "status": "unavailable",
        "message": reasons.get(reason, "Связь с H1Cloud не подтверждена.")
                   + " Это не проверка доступности VPN-серверов.",
    }


async def probe_rollypay() -> dict:
    key = os.environ.get("ROLLYPAY_API_KEY", "")
    if not key:
        return {
            "status": "sandbox",
            "message": "RollyPay API-ключ не обнаружен. Доступна лишь локальная "
                       "симуляция; списаний нет.",
        }
    # GET only: no payment, wallet, bill, or refund is created.
    try:
        await asyncio.wait_for(
            BillingSandbox(
                mode="provider", api_key=key,
                terminal_id=os.environ.get("ROLLYPAY_TERMINAL_ID", ""),
            ).provider_diagnostics(),
            timeout=10,
        )
    except (TimeoutError, ProviderError) as error:
        code = error.code if isinstance(error, ProviderError) else "TIMEOUT"
        # Keep diagnostics specific, but never expose provider response data,
        # account balances, API keys, or arbitrary exception strings.
        messages = {
            "PROVIDER_HTTP_400": (
                "RollyPay вернул HTTP 400 при проверке баланса кассы. "
                "Причина не входит в список известных; запрос не создавал платёж."
            ),
            "PROVIDER_TERMINAL_ID_INVALID": (
                "Переменная ROLLYPAY_TERMINAL_ID должна содержать корректный UUID кассы. "
                "Если ключ привязан к кассе, этот параметр можно убрать."
            ),
            "PROVIDER_TERMINAL_NOT_FOUND": (
                "RollyPay ответил: касса не найдена (HTTP 400). "
                "Проверь Terminal ID и его соответствие API-ключу."
            ),
            "PROVIDER_TERMINAL_ID_REQUIRED": (
                "RollyPay запросил идентификатор кассы (HTTP 400). "
                "Задай ROLLYPAY_TERMINAL_ID (UUID кассы) в Render."
            ),
            "PROVIDER_HTTP_401": (
                "RollyPay отклонил авторизацию (HTTP 401). "
                "Проверь API-ключ именно кассы и отсутствие пробелов."
            ),
            "PROVIDER_HTTP_403": (
                "RollyPay не разрешил доступ к API (HTTP 403). "
                "Проверь права и активность кассы."
            ),
            "PROVIDER_HTTP_404": (
                "RollyPay вернул HTTP 404 для проверки баланса. "
                "Возможно, используемый API-домен не поддерживает этот маршрут."
            ),
            "PROVIDER_HTTP_409": (
                "RollyPay вернул HTTP 409 (конфликт запроса). "
                "Новый запрос использует уникальный X-Nonce."
            ),
            "PROVIDER_HTTP_429": (
                "RollyPay временно ограничил число запросов (HTTP 429). "
                "Повтори проверку позднее."
            ),
            "PROVIDER_HTTP_500": "RollyPay сообщил о внутренней ошибке (HTTP 500).",
            "PROVIDER_HTTP_502": "Шлюз RollyPay вернул HTTP 502.",
            "PROVIDER_HTTP_503": "Сервис RollyPay временно недоступен (HTTP 503).",
            "PROVIDER_RESPONSE_INVALID": (
                "RollyPay ответил на GET, но формат JSON не соответствует "
                "документированной схеме баланса."
            ),
            "PROVIDER_TIMEOUT": "Превышено время ожидания ответа RollyPay.",
            "TIMEOUT": "Превышено время ожидания проверки RollyPay.",
            "PROVIDER_NETWORK": "Render не смог установить соединение с RollyPay.",
        }
        return {
            "status": "error" if code in {
                "PROVIDER_HTTP_400", "PROVIDER_HTTP_401", "PROVIDER_HTTP_403",
                "PROVIDER_HTTP_404", "PROVIDER_RESPONSE_INVALID",
                "PROVIDER_TERMINAL_ID_INVALID", "PROVIDER_TERMINAL_NOT_FOUND",
                "PROVIDER_TERMINAL_ID_REQUIRED",
            } else "unavailable",
            "message": messages.get(
                code,
                "RollyPay отклонил API-запрос или вернул неожиданный HTTP-код."
            ) + " Реальные платежи выключены.",
        }
    return {
        "status": "ok",
        "message": "RollyPay API принял ключ кассы при безопасной GET-проверке. "
                   "Баланс скрыт; платежи и выдача VPN не проверены.",
    }


def webhook_status() -> dict:
    secret = os.environ.get("ROLLYPAY_SIGNING_SECRET", "")
    if len(secret) < 16:
        return {
            "status": "not_connected",
            "message": "Секрет ROLLYPAY_SIGNING_SECRET не настроен. "
                       "Входящие webhook не будут подтверждены.",
        }
    return {
        "status": "configured",
        "message": "Секрет подписи RollyPay есть. HTTPS-обработчик реализован "
                   "и проверен тестами. Реальная доставка webhook ещё не подтверждена.",
    }


async def integration_status() -> dict:
    global _cached_until, _cached_fingerprint, _cached_report
    now = time.monotonic()
    fingerprint = _fingerprint()
    if (now < _cached_until and fingerprint == _cached_fingerprint
            and _cached_report is not None):
        return _cached_report
    async with _lock:
        now = time.monotonic()
        if (now < _cached_until and fingerprint == _cached_fingerprint
                and _cached_report is not None):
            return _cached_report
        h1, rollypay = await asyncio.gather(probe_h1(), probe_rollypay())
        report = {
            "h1": h1,
            "rollypay": rollypay,
            "webhook": webhook_status(),
        }
        _cached_fingerprint = fingerprint
        _cached_until = time.monotonic() + CACHE_TTL_SECONDS
        _cached_report = report
        return report
