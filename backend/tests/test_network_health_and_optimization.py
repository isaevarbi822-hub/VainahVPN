"""Connection-health and Speed Lab regression tests.

Only read-only API checks and bounded, mock/testclient requests are exercised.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vainah import speedtest
from vainah.main import app

ROOT = Path(__file__).resolve().parents[2] / "storefront"


def test_network_health_page_has_six_working_check_targets():
    with TestClient(app) as client:
        page = client.get("/network-check.html")
        script = client.get("/network-check.js")
        assert page.status_code == 200
        assert script.status_code == 200
        assert "/api/health" in script.text
        assert "/api/email-auth/config" in script.text
        assert "/api/shop/config" in script.text
        for suffix in ("internet", "https", "api", "ping", "login", "shop"):
            assert f'id="network-{suffix}"' in page.text
        assert 'id="network-stop"' in page.text
        assert "AbortController" in script.text


def test_network_health_is_linked_from_navigation_and_tools():
    shell = (ROOT / "site-shell.js").read_text(encoding="utf-8")
    catalog = (ROOT / "tools.html").read_text(encoding="utf-8")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    assert "['network-check.html','Проверка соединения'" in shell
    assert 'href="network-check.html"' in catalog
    assert "/network-check.html" in sitemap


def test_speed_comparison_is_session_only_and_stays_client_side():
    js = (ROOT / "speed-test.js").read_text(encoding="utf-8")
    page = (ROOT / "speed.html").read_text(encoding="utf-8")
    assert 'id="speed-copy"' in page
    assert 'id="speed-previous"' in page
    assert "navigator.clipboard.writeText(summary)" in js
    assert "previous={...latest}" in js
    assert "localStorage" not in js
    assert "sessionStorage" not in js


def test_speedtest_rejects_unbounded_new_client_identities():
    speedtest._recent.clear()
    now = time.monotonic()
    try:
        speedtest._recent.update({
            f"sample-{n}": deque([now])
            for n in range(speedtest.MAX_IDENTITIES)
        })
        request = SimpleNamespace(
            client=SimpleNamespace(host="a-new-client")
        )
        with pytest.raises(HTTPException) as err:
            asyncio.run(speedtest._allow(request))
        assert err.value.status_code == 429
        assert "a-new-client" not in speedtest._recent
        assert len(speedtest._recent) <= speedtest.MAX_IDENTITIES
    finally:
        speedtest._recent.clear()


def test_speedtest_prunes_expired_client_rate_limits():
    speedtest._recent.clear()
    try:
        speedtest._recent.update({
            f"sample-{n}": deque([time.monotonic()-speedtest.WINDOW_SECONDS-2])
            for n in range(speedtest.MAX_IDENTITIES)
        })
        request = SimpleNamespace(client=SimpleNamespace(host="fresh"))
        asyncio.run(speedtest._allow(request))
        assert len(speedtest._recent) == 1
        assert "fresh" in speedtest._recent
    finally:
        speedtest._recent.clear()
