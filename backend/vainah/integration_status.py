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

import psycopg

from .billing import BillingSandbox, ProviderError
from .h1_direct_health import probe_direct_health
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
        "VAINAH_SHOP_SANDBOX_MODE", "PANEL_DIRECT_HEALTH_URL",
        "PANEL_TLS_CA_PEM",
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
        "connect_failed": "Не удалось установить соединение с API H1Cloud. Проверь адрес и порт 443.",
        "dns_failed": "Домен API H1Cloud не разрешается в DNS с сервера Render.",
        "tls_failed": "HTTPS-сертификат панели H1Cloud не проходит проверку TLS.",
        "connect_timeout": "Render не может подключиться к API H1Cloud за 8 секунд.",
        "response_timeout": "API H1Cloud установил соединение, но не ответил вовремя.",
        "protocol_error": "API H1Cloud прервал HTTPS-соединение без корректного ответа.",
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
            ) + " Эта GET-проверка не подтверждает состояние отдельных платежей и выдачи VPN.",
        }
    return {
        "status": "ok",
        "message": "RollyPay API принял ключ кассы при безопасной GET-проверке. "
                   "Баланс скрыт; платежи и выдача VPN не проверены.",
    }


def _live_webhook_evidence(database_url: str) -> tuple[bool, bool] | None:
    """Read only non-identifying proof of previously signed live payments.

    Historical events do not guarantee that any future callback will arrive.
    The live order ledger only sets webhook_at after signature verification.
    """
    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '1500ms'")
                cur.execute("""
                    SELECT
                        EXISTS (
                            SELECT 1 FROM vainah_live_orders
                            WHERE webhook_at IS NOT NULL AND payment_state = 'paid'
                        ),
                        EXISTS (
                            SELECT 1 FROM vainah_live_orders
                            WHERE webhook_at IS NOT NULL AND payment_state = 'paid'
                              AND delivery_state = 'delivered'
                        )
                """)
                row = cur.fetchone()
                return (bool(row[0]), bool(row[1])) if row else None
    except (psycopg.Error, OSError, ValueError):
        # Missing database evidence is not proof of webhook failure.
        return None


def webhook_status() -> dict:
    secret = os.environ.get("ROLLYPAY_SIGNING_SECRET", "")
    if len(secret) < 16:
        return {
            "status": "not_connected",
            "message": "Секрет ROLLYPAY_SIGNING_SECRET не настроен. "
                       "Входящие webhook не будут подтверждены.",
        }
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgres://")):
        return {
            "status": "configured",
            "message": "Подпись webhook настроена. Историю подписанных платежей "
                       "пока нельзя проверить: PostgreSQL не подключён.",
        }
    evidence = _live_webhook_evidence(database_url)
    if evidence is None:
        return {
            "status": "configured",
            "message": "Подпись webhook настроена. Историческое подтверждение "
                       "в PostgreSQL сейчас недоступно; это не означает сбой доставки.",
        }
    signed_paid, delivered = evidence
    if delivered:
        return {
            "status": "verified",
            "message": "Подтверждено по истории: RollyPay прислал подписанный "
                       "webhook об оплате, и VPN был выдан автоматически. "
                       "Это не проверка доставки новых webhook в реальном времени.",
        }
    if signed_paid:
        return {
            "status": "received",
            "message": "В PostgreSQL есть подтверждённый подписанный webhook "
                       "об оплате. Автоматическая выдача по этой проверке не "
                       "подтверждена; проверь состояние заказа в кабинете.",
        }
    return {
        "status": "configured",
        "message": "Подпись webhook настроена. Подтверждённых записей об "
                   "оплаченном live-заказе пока не найдено. Это не означает сбой.",
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
        if os.environ.get("PANEL_DIRECT_HEALTH_URL", "").strip():
            h1, direct, rollypay = await asyncio.gather(
                probe_h1(), probe_direct_health(), probe_rollypay()
            )
            report = {
                "h1": h1,
                "h1_direct": direct,
                "rollypay": rollypay,
                "webhook": await asyncio.to_thread(webhook_status),
            }
        else:
            h1, rollypay = await asyncio.gather(probe_h1(), probe_rollypay())
            report = {
                "h1": h1,
                "rollypay": rollypay,
                "webhook": await asyncio.to_thread(webhook_status),
            }
        _cached_fingerprint = fingerprint
        _cached_until = time.monotonic() + CACHE_TTL_SECONDS
        _cached_report = report
        return report
