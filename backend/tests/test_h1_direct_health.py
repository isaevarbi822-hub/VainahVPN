"""Direct H1Cloud API check is read-only, tokenless and host-restricted."""
from __future__ import annotations

import asyncio
import httpx
import pytest

from vainah.h1_direct_health import probe_direct_health

TEST_URL = "http://direct-de12b.h1cloud.net:25105/api/health"


@pytest.fixture
def direct(monkeypatch):
    monkeypatch.setenv("PANEL_DIRECT_HEALTH_URL", TEST_URL)
    monkeypatch.setenv("PANEL_API_TOKEN", "HIGH_PRIVILEGE_PRIVATE_TEST_TOKEN")


def api_response():
    return {
        "ok": True,
        "service": "vpn-api",
        "api_port": 25105,
        "endpoints": [
            "GET /clients",
            "GET /info?name=NAME",
            "POST /create",
            "PATCH /edit",
            "DELETE /clients/NAME",
        ],
        "auth": "Authorization: Bearer TOKEN or X-API-Key: TOKEN",
    }


def test_direct_health_uses_get_without_any_credentials(direct):
    seen = []

    def api(request: httpx.Request):
        seen.append(request)
        assert request.method == "GET"
        assert str(request.url) == TEST_URL
        assert request.url.scheme == "http"
        assert "authorization" not in request.headers
        assert "x-api-key" not in request.headers
        assert "cookie" not in request.headers
        assert request.content == b""
        return httpx.Response(200, json=api_response())

    report = asyncio.run(probe_direct_health(
        transport=httpx.MockTransport(api),
    ))
    assert len(seen) == 1
    assert report["status"] == "ok"
    assert report["read_only"] is True
    assert report["api_token_sent"] is False
    assert report["protected_connection"] is False
    assert report["create_endpoint_listed"] is True
    assert report["extend_endpoint_listed"] is True
    assert report["client_info_endpoint_listed"] is True
    assert "HIGH_PRIVILEGE_PRIVATE_TEST_TOKEN" not in str(report)
    assert "direct-de12b.h1cloud.net" not in str(report)


@pytest.mark.parametrize("invalid", [
    "http://127.0.0.1:25105/api/health",
    "http://localhost:25105/api/health",
    "http://direct-de12b.h1cloud.net:80/api/health",
    "http://direct-de12b.h1cloud.net:25105/api/clients",
    "http://direct-de12b.h1cloud.net:25105/api/health?token=abc",
    "http://direct-de12b.h1cloud.net:25105/api/health#fragment",
    "http://direct-de12b.h1cloud.net:25105/api/health/",
    "http://direct-de12b.h1cloud.net@evil.example:25105/api/health",
    "http://direct-de12b.h1cloud.net.evil.example:25105/api/health",
    "https://direct-de12b.h1cloud.net:25105/api/health",
    "http://direct-de12b.h1cloud.net:99999/api/health",
])
def test_invalid_url_never_makes_request(monkeypatch, invalid):
    monkeypatch.setenv("PANEL_DIRECT_HEALTH_URL", invalid)

    def forbidden(_request):
        raise AssertionError("The direct probe must reject the URL locally")

    report = asyncio.run(probe_direct_health(
        transport=httpx.MockTransport(forbidden),
    ))
    assert report["status"] == "error"


def test_missing_url_is_not_configured(monkeypatch):
    monkeypatch.delenv("PANEL_DIRECT_HEALTH_URL", raising=False)
    report = asyncio.run(probe_direct_health())
    assert report["status"] == "not_configured"


@pytest.mark.parametrize(("status", "payload"), [
    (302, {"ok": True, "service": "vpn-api", "endpoints": []}),
    (401, {"ok": False}),
    (200, {"ok": False, "service": "vpn-api", "endpoints": []}),
    (200, {"ok": True, "service": "other-service", "endpoints": []}),
    (200, {"ok": True, "service": "vpn-api", "endpoints": "fake"}),
])
def test_bad_response_never_claims_connection(direct, status, payload):
    report = asyncio.run(probe_direct_health(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status, json=payload)
        )
    ))
    assert report["status"] == "error"


def test_connection_timeout_is_clear_and_redacted(direct):
    def unreachable(request):
        raise httpx.ConnectTimeout("secret host/invalid", request=request)

    report = asyncio.run(probe_direct_health(
        transport=httpx.MockTransport(unreachable),
    ))
    assert report["status"] == "unavailable"
    assert "secret" not in str(report)
