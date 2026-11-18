"""Regression checks for public site data and read-only frontend API access."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app
from vainah.public_locations import public_locations

STATIC_ORIGIN = "https://vainahvpn.onrender.com"


def test_no_unpublished_servers_are_claimed(monkeypatch):
    monkeypatch.delenv("VAINAH_PUBLIC_LOCATIONS_JSON", raising=False)
    assert public_locations()["locations"] == []
    assert public_locations()["source"] == "not_published"


def test_public_server_directory_is_bounded_and_sanitized(monkeypatch):
    data = [
        {"name": "Германия 1", "flag": "🇩🇪"},
        {"name": "германия 1", "flag": "🇩🇪"},
        {"name": "https://internal.example", "flag": "🌐"},
        {"name": "10.0.0.1", "flag": "🌐"},
        {"name": "Испания (1)", "flag": "🇪🇸"},
        {"name": "<script>", "flag": "🌐"},
    ]
    monkeypatch.setenv("VAINAH_PUBLIC_LOCATIONS_JSON", json.dumps(data))
    result = public_locations()
    assert result["source"] == "operator_published"
    assert result["availability_verified"] is False
    assert result["locations"] == [
        {"name": "Германия 1", "flag": "🇩🇪"},
        {"name": "Испания (1)", "flag": "🇪🇸"},
    ]


def test_public_api_allows_exact_static_origin_only():
    client = TestClient(app)
    for path in ("/api/site/locations", "/api/site/tariffs", "/api/shop/config"):
        response = client.get(path, headers={"Origin": STATIC_ORIGIN})
        assert response.headers.get("access-control-allow-origin") == STATIC_ORIGIN
        assert response.headers.get("access-control-allow-credentials") is None
        assert response.headers.get("vary") == "Origin"
        blocked = client.get(path, headers={"Origin": "https://untrusted.example"})
        assert "access-control-allow-origin" not in blocked.headers
    response = client.post("/api/shop/checkout", headers={"Origin": STATIC_ORIGIN})
    assert "access-control-allow-origin" not in response.headers


def test_site_refresh_is_loaded_only_from_local_assets():
    root = Path(__file__).resolve().parents[2] / "storefront"
    shell = (root / "site-shell.js").read_text(encoding="utf-8")
    directory = (root / "public-servers.js").read_text(encoding="utf-8")
    panel = (root / "site-health.js").read_text(encoding="utf-8")
    assert "site-upgrade.css" in shell
    assert "site-health.js" in shell
    assert "apiOrigin+'/api/site/locations'" in directory
    assert "credentials:'omit'" in panel
    assert "fetch(apiOrigin+'/api/shop/config'" in panel
