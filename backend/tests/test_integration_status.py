"""Read-only health checks cannot create charges or VPN subscriptions."""
from __future__ import annotations

import asyncio

from vainah import integration_status as checks


def test_missing_configuration_is_not_reported_as_api_failure(monkeypatch):
    monkeypatch.delenv("PANEL_BASE_URL", raising=False)
    monkeypatch.delenv("PANEL_API_TOKEN", raising=False)
    monkeypatch.delenv("ROLLYPAY_API_KEY", raising=False)
    monkeypatch.delenv("ROLLYPAY_SIGNING_SECRET", raising=False)
    result = asyncio.run(checks.integration_status())
    assert result["h1"]["status"] == "not_connected"
    assert result["rollypay"]["status"] == "sandbox"
    assert result["webhook"]["status"] == "not_connected"
    assert not result["h1"].get("vpn_delivered")


def test_h1_read_only_probe_reports_reachable_without_subscription(monkeypatch):
    monkeypatch.setenv("PANEL_BASE_URL", "https://panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "private-secret-do-not-show")
    calls = []

    async def fake_inspect():
        calls.append("GET")
        return {"ok": True, "panel": "reachable",
                "authentication": "accepted", "vpn_delivered": False}

    monkeypatch.setattr(checks, "inspect_h1_panel", fake_inspect)
    status = asyncio.run(checks.probe_h1())
    assert status["status"] == "ok"
    assert calls == ["GET"]
    assert "private-secret-do-not-show" not in str(status)
    assert "выдача не проверены" in status["message"]


def test_h1_rejected_token_does_not_expose_remote_body(monkeypatch):
    monkeypatch.setenv("PANEL_BASE_URL", "https://panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "private-test-secret")

    async def rejected():
        return {"ok": False, "panel": "reachable", "authentication": "rejected"}

    monkeypatch.setattr(checks, "inspect_h1_panel", rejected)
    status = asyncio.run(checks.probe_h1())
    assert status["status"] == "error"
    assert "private-test-secret" not in str(status)


def test_rollypay_probe_uses_only_a_read_only_list(monkeypatch):
    monkeypatch.setenv("ROLLYPAY_API_KEY", "private-merchant-api-key")
    seen = []

    async def harmless_get(self):
        seen.append((self.mode, self.api_key))
        return {"connected": True, "new_payment_created": False}

    monkeypatch.setattr(checks.BillingSandbox, "provider_diagnostics", harmless_get)
    status = asyncio.run(checks.probe_rollypay())
    assert status["status"] == "ok"
    assert seen == [("provider", "private-merchant-api-key")]
    assert "private-merchant-api-key" not in str(status)
    assert "Счёт" not in str(status)


def test_webhook_secret_presence_does_not_claim_provider_delivery(monkeypatch):
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", "private-signature-secret-key")
    status = checks.webhook_status()
    assert status["status"] == "configured"
    assert "Реальная доставка webhook ещё не подтверждена" in status["message"]
    assert "private-signature-secret-key" not in str(status)


def test_provider_checks_are_cached_and_invalidate_when_config_changes(monkeypatch):
    monkeypatch.setenv("ROLLYPAY_API_KEY", "first-token")
    monkeypatch.delenv("PANEL_API_TOKEN", raising=False)
    monkeypatch.delenv("PANEL_BASE_URL", raising=False)
    calls = []

    async def fake_h1():
        calls.append("h1")
        return {"status": "not_connected", "message": "mock"}

    async def fake_rolly():
        calls.append("rollypay")
        return {"status": "ok", "message": "mock"}

    monkeypatch.setattr(checks, "probe_h1", fake_h1)
    monkeypatch.setattr(checks, "probe_rollypay", fake_rolly)
    monkeypatch.setattr(checks, "_cached_until", 0.0)
    first = asyncio.run(checks.integration_status())
    second = asyncio.run(checks.integration_status())
    assert first is second
    assert calls == ["h1", "rollypay"]
    monkeypatch.setenv("ROLLYPAY_API_KEY", "different-token")
    asyncio.run(checks.integration_status())
    assert calls == ["h1", "rollypay", "h1", "rollypay"]


def test_rollypay_failed_http_status_keeps_specific_code_without_secrets(monkeypatch):
    from vainah.billing import ProviderError

    monkeypatch.setenv("ROLLYPAY_API_KEY", "private-api-key-do-not-log")

    async def rejected(self):
        raise ProviderError("PROVIDER_HTTP_404")

    monkeypatch.setattr(checks.BillingSandbox, "provider_diagnostics", rejected)
    status = asyncio.run(checks.probe_rollypay())
    assert status["status"] == "error"
    assert "HTTP 404" in status["message"]
    assert "private-api-key-do-not-log" not in str(status)


def test_rollypay_invalid_schema_has_explanatory_status(monkeypatch):
    from vainah.billing import ProviderError

    monkeypatch.setenv("ROLLYPAY_API_KEY", "private-api-key-do-not-log")

    async def unexpected(self):
        raise ProviderError("PROVIDER_RESPONSE_INVALID")

    monkeypatch.setattr(checks.BillingSandbox, "provider_diagnostics", unexpected)
    status = asyncio.run(checks.probe_rollypay())
    assert status["status"] == "error"
    assert "формат JSON" in status["message"]
    assert "private-api-key-do-not-log" not in str(status)


def test_rollypay_throttle_reported_as_unavailable(monkeypatch):
    from vainah.billing import ProviderError

    monkeypatch.setenv("ROLLYPAY_API_KEY", "private-api-key-do-not-log")

    async def throttled(self):
        raise ProviderError("PROVIDER_HTTP_429")

    monkeypatch.setattr(checks.BillingSandbox, "provider_diagnostics", throttled)
    status = asyncio.run(checks.probe_rollypay())
    assert status["status"] == "unavailable"
    assert "HTTP 429" in status["message"]


def test_empty_webhook_secret_never_claims_connected(monkeypatch):
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", "short")
    status = checks.webhook_status()
    assert status["status"] == "not_connected"


def test_rollypay_terminal_id_is_used_and_does_not_leak(monkeypatch):
    terminal = "d290f1ee-6c54-4b01-90e6-d701748f0851"
    monkeypatch.setenv("ROLLYPAY_API_KEY", "private-key")
    monkeypatch.setenv("ROLLYPAY_TERMINAL_ID", terminal)
    seen = []

    async def diagnostic(self):
        seen.append(self.terminal_id)
        return {"connected": True, "new_payment_created": False}

    monkeypatch.setattr(checks.BillingSandbox, "provider_diagnostics", diagnostic)
    status = asyncio.run(checks.probe_rollypay())
    assert seen == [terminal]
    assert status["status"] == "ok"
    assert terminal not in str(status)


def test_rollypay_known_terminal_not_found_has_safe_message(monkeypatch):
    from vainah.billing import ProviderError

    monkeypatch.setenv("ROLLYPAY_API_KEY", "private-key")

    async def diagnostic(self):
        raise ProviderError("PROVIDER_TERMINAL_NOT_FOUND")

    monkeypatch.setattr(checks.BillingSandbox, "provider_diagnostics", diagnostic)
    status = asyncio.run(checks.probe_rollypay())
    assert status["status"] == "error"
    assert "касса не найдена" in status["message"]
    assert "private-key" not in str(status)
