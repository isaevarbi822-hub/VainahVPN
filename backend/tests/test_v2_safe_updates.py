"""Vainah VPN 2.0 public/static and operator read-only regression checks."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

STORE = Path(__file__).resolve().parents[2] / "storefront"
STATIC = "https://vainahvpn.onrender.com"


def test_static_origin_can_read_only_public_tariff_catalog():
    with TestClient(app) as client:
        result = client.get("/api/site/tariffs", headers={"Origin": STATIC})
        assert result.status_code == 200
        assert result.headers["access-control-allow-origin"] == STATIC
        assert result.headers["vary"] == "Origin"
        assert "access-control-allow-credentials" not in result.headers
        assert result.json()["total"] == 76

        untrusted = client.get("/api/site/tariffs", headers={
            "Origin": "https://example.com"
        })
        assert "access-control-allow-origin" not in untrusted.headers

        private = client.get("/api/email-auth/config", headers={"Origin": STATIC})
        assert "access-control-allow-origin" not in private.headers


def test_static_featured_catalog_uses_read_only_backend_with_safe_fallback():
    js = (STORE / "live-plan-picks.js").read_text(encoding="utf-8")
    assert "https://vainahvpn-python-preview.onrender.com" in js
    assert "publicApi+'/api/site/tariffs'" in js
    assert "credentials:'omit'" in js
    assert "link.href='plans.html'" in js
    assert "Открыть страницу тарифов" in js
    assert "fetch('/api/shop/checkout'" not in js


def test_homepage_has_valid_public_jsonld_and_video_stays_on_demand():
    html = (STORE / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<script type="application/ld\+json">(.+?)</script>', html, re.DOTALL)
    assert match
    graph = json.loads(match.group(1))
    assert graph["@context"] == "https://schema.org"
    assert {node["@type"] for node in graph["@graph"]} == {
        "Organization", "WebSite", "WebPage"
    }
    assert all("vainahvpn.onrender.com" in node["url"] for node in graph["@graph"])
    assert 'preload="none"' in html
    assert 'data-intro-video' in html


def test_operator_csv_export_is_aggregate_only_and_disabled_until_auth():
    html = (STORE / "operations.html").read_text(encoding="utf-8")
    js = (STORE / "operations.js").read_text(encoding="utf-8")
    assert 'id="ops-export" type="button" disabled' in html
    assert 'credentials: "same-origin"' in js
    assert "Number.isInteger(data[field])" in js
    assert "lastReport.counters" in js
    assert 'link.download="vainahvpn-orders-summary-"+lastReport.checked_at' in js
    assert "localStorage" not in js
    assert "sessionStorage" not in js
