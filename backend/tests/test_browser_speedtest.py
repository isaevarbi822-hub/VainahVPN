"""Bounded same-origin browser speed test contract and storefront integration."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vainah import speedtest
from vainah.main import app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def reset_speed_limit():
    speedtest._recent.clear()
    yield
    speedtest._recent.clear()


def test_ping_and_download_are_no_cache_and_bounded():
    with TestClient(app) as client:
        ping = client.get("/api/speedtest/ping")
        assert ping.status_code == 204
        assert ping.headers.get("cache-control") == "no-store"

        download = client.get("/api/speedtest/download")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("application/octet-stream")
        assert len(download.content) == 512 * 1024
        assert "no-store" in download.headers["cache-control"]


def test_upload_requires_bounded_exact_content_length():
    with TestClient(app) as client:
        good = client.post(
            "/api/speedtest/upload",
            content=b"x" * (256 * 1024),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert good.status_code == 200
        assert good.json() == {"received_bytes": 256 * 1024}
        too_large = client.post(
            "/api/speedtest/upload",
            content=b"x" * (256 * 1024 + 1),
        )
        assert too_large.status_code == 413


def test_request_limit_is_enforced_on_server():
    with TestClient(app) as client:
        for _ in range(speedtest.REQUESTS_PER_WINDOW):
            assert client.get("/api/speedtest/ping").status_code == 204
        blocked = client.get("/api/speedtest/download")
        assert blocked.status_code == 429


def test_speed_page_and_tool_directory_are_public_and_linked():
    with TestClient(app) as client:
        for page in ("/speed.html", "/tools.html", "/speed-test.js", "/speed-test.css"):
            response = client.get(page)
            assert response.status_code == 200, page
        html = client.get("/speed.html").text
        assert 'id="speed-start"' in html
        assert 'id="speed-stop"' in html
        assert 'src="speed-test.js"' in html
        assert 'href="speed-test.css"' in html
        directory = client.get("/tools.html").text
        assert 'href="speed.html"' in directory
        assert 'href="trial.html"' in directory
        assert 'href="account.html"' in directory


def test_client_uses_real_endpoints_not_fabricated_results():
    js = (ROOT / "storefront/speed-test.js").read_text(encoding="utf-8")
    assert "'/api/speedtest/'" in js
    assert "response.arrayBuffer()" in js
    assert "performance.now()" in js
    assert "received_bytes" in js
    assert "AbortController()" in js
    assert "speed-download" in js and "speed-upload" in js
