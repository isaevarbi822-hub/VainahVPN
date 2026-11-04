"""Read-only H1Cloud integration tests; no live provider needed."""
from __future__ import annotations

import socket
import ssl

import httpx
import pytest
from fastapi.testclient import TestClient

from vainah.h1_panel import (
    H1PanelError,
    inspect_h1_panel,
    panel_settings,
    public_h1_status,
    read_h1_status,
)
from vainah.main import app

client = TestClient(app)
BASE = "https://vpn-panel.example.com/api"
TOKEN = "fake-test-only-h1-token"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("PANEL_BASE_URL", BASE)
    monkeypatch.setenv("PANEL_API_TOKEN", TOKEN)
    monkeypatch.setenv("PANEL_CLIENT_PREFIX", "tg")


def test_h1_origin_requires_https_and_public_hostname(monkeypatch):
    monkeypatch.setenv("PANEL_API_TOKEN", TOKEN)
    for url in (
        "http://vpn-panel.example.com",
        "https://127.0.0.1",
        "https://localhost",
        "https://vpn-panel.example.com@evil.example",
        "https://vpn-panel.example.com/?token=private",
        "https://vpn-panel.example.com/api/clients",
    ):
        monkeypatch.setenv("PANEL_BASE_URL", url)
        with pytest.raises(H1PanelError):
            panel_settings()


def test_h1_dedicated_https_management_port_is_preserved(config):
    import asyncio

    expected = "https://vpn-panel.example.com:25626/api"
    from vainah.h1_panel import panel_settings

    import os

    os.environ["PANEL_BASE_URL"] = expected
    settings = panel_settings()
    assert settings is not None
    assert settings.origin == "https://vpn-panel.example.com:25626"

    observed = []

    def fake_api(request: httpx.Request):
        observed.append(str(request.url))
        return httpx.Response(404, json={"error": "user_not_found"})

    result = asyncio.run(inspect_h1_panel(
        transport=httpx.MockTransport(fake_api),
    ))
    assert result["authentication"] == "accepted"
    assert observed == [
        "https://vpn-panel.example.com:25626/api/clients/tg999999999999999999"
    ]


@pytest.mark.parametrize("bad_port_url", [
    "https://vpn-panel.example.com:0/api",
    "https://vpn-panel.example.com:22/api",
    "https://vpn-panel.example.com:99999/api",
    "https://vpn-panel.example.com:notanumber/api",
])
def test_h1_rejects_invalid_or_privileged_port(config, monkeypatch, bad_port_url):
    monkeypatch.setenv("PANEL_BASE_URL", bad_port_url)
    with pytest.raises(H1PanelError, match="PANEL_URL_INVALID"):
        panel_settings()


def test_h1_read_only_and_redacted_status(config):
    import asyncio

    observed = []
    def provider(request: httpx.Request):
        observed.append((request.method, str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json={"ok": True, "client": {
            "name": "tg123456789", "expires_at": 2000000000,
            "uuid": "SECRET_UUID", "subscription_url": "https://vpn.example/SECRET",
            "vless": "vless://TOP_SECRET", "devices": ["secret-device"],
        }})

    result = asyncio.run(read_h1_status(
        "123456789", transport=httpx.MockTransport(provider), now=1800000000
    ))
    assert result["panel_ready"] is True
    assert result["found"] is True
    assert result["active"] is True
    assert result["banned"] is False
    assert len(observed) == 1
    assert observed[0] == (
        "GET", "https://vpn-panel.example.com/api/clients/tg123456789",
        "Bearer " + TOKEN
    )
    assert not any(secret in str(result) for secret in (
        "SECRET_UUID", "TOP_SECRET", "SECRET", "vless://", "devices", TOKEN,
    ))


def test_h1_probe_404_missing_sentinel_proves_auth_without_real_user(config):
    import asyncio

    def provider(request: httpx.Request):
        assert request.method == "GET"
        assert request.url.path == "/api/clients/tg999999999999999999"
        return httpx.Response(404, json={"error": "user_not_found"})

    result = asyncio.run(inspect_h1_panel(transport=httpx.MockTransport(provider)))
    assert result == {"ok": True, "panel": "reachable",
                      "authentication": "accepted", "vpn_delivered": False}


def test_h1_wrong_auth_and_html_response_redact_provider_error(config):
    import asyncio

    result = asyncio.run(inspect_h1_panel(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                401, text="token=" + TOKEN + " SECRET host/private"
            )
        )
    ))
    assert result == {"ok": False, "panel": "reachable",
                      "authentication": "rejected"}

    result = asyncio.run(inspect_h1_panel(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, text="<html>SECRET</html>")
        )
    ))
    assert result["ok"] is False
    assert "SECRET" not in str(result)


def test_h1_profile_banned_cannot_be_active(config):
    import asyncio

    response = httpx.MockTransport(lambda _request: httpx.Response(
        200, json={"ok": True, "client": {
            "name": "tg123456789", "expires_at": 2000000000,
            "status": "banned",
        }}
    ))
    result = asyncio.run(read_h1_status(
        "123456789", transport=response, now=1800000000
    ))
    assert result["found"] is True and result["active"] is False


def test_h1_operator_endpoint_is_protected(monkeypatch):
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", "x" * 32)
    response = client.get("/api/site/integrations/h1cloud/check")
    assert response.status_code == 401
    assert public_h1_status()["status"] in {"not_connected", "configured", "error"}
    # Unknown code/data is never turned into public details.


def test_h1_invalid_identity_rejected_without_request(config):
    import asyncio

    with pytest.raises(H1PanelError):
        asyncio.run(read_h1_status("123/../../no"))


@pytest.mark.parametrize(("failure", "reason"), [
    ("dns", "dns_failed"),
    ("tls", "tls_failed"),
    ("connect", "connect_failed"),
    ("connect_timeout", "connect_timeout"),
    ("read_timeout", "response_timeout"),
    ("protocol", "protocol_error"),
])
def test_h1_network_diagnostics_redact_errors(config, failure, reason):
    import asyncio

    def unavailable(request: httpx.Request):
        if failure == "dns":
            try:
                raise socket.gaierror(-2, "secret DNS hostname")
            except socket.gaierror as exc:
                raise httpx.ConnectError(
                    "secret DNS hostname", request=request,
                ) from exc
        if failure == "tls":
            try:
                raise ssl.SSLCertVerificationError("secret certificate hostname")
            except ssl.SSLError as exc:
                raise httpx.ConnectError(
                    "secret TLS hostname", request=request,
                ) from exc
        if failure == "connect":
            raise httpx.ConnectError("secret address", request=request)
        if failure == "connect_timeout":
            raise httpx.ConnectTimeout("secret address", request=request)
        if failure == "read_timeout":
            raise httpx.ReadTimeout("secret address", request=request)
        raise httpx.RemoteProtocolError("secret address", request=request)

    status = asyncio.run(inspect_h1_panel(
        transport=httpx.MockTransport(unavailable),
    ))
    assert status == {
        "ok": False, "panel": "unavailable", "reason": reason,
    }
    assert "secret" not in str(status)
    assert TOKEN not in str(status)
