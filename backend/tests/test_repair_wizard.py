"""Storefront repair wizard and navigation regression checks.

Only public static pages are exercised. No payments or VPN profiles are created.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

ROOT = Path(__file__).resolve().parents[2] / "storefront"


def test_repair_wizard_and_assets_load():
    with TestClient(app) as client:
        for path in ("/repair-wizard.html", "/repair-wizard.js"):
            page = client.get(path)
            assert page.status_code == 200, path
        page = client.get("/repair-wizard.html").text
        assert 'id="repair-issue"' in page
        assert 'id="repair-platform"' in page
        assert 'id="repair-run"' in page
        assert 'id="repair-reset"' in page
        assert 'id="repair-copy"' in page
        assert 'src="repair-wizard.js"' in page


def test_five_issue_types_and_four_platforms_are_supported():
    html = (ROOT / "repair-wizard.html").read_text(encoding="utf-8")
    js = (ROOT / "repair-wizard.js").read_text(encoding="utf-8")
    for kind in ("connect", "import", "slow", "payment", "email"):
        assert f'<option value="{kind}">' in html
        assert f"    {kind}:{{" in js
    for platform in ("android", "ios", "windows", "mac"):
        assert f'<option value="{platform}">' in html
        assert f"    {platform}:" in js
    assert "document.createElement('li')" in js
    assert "textContent=step" in js


def test_wizard_stays_client_only_and_does_not_request_credentials():
    js = (ROOT / "repair-wizard.js").read_text(encoding="utf-8")
    assert "fetch(" not in js
    assert "localStorage" not in js
    assert "sessionStorage" not in js
    assert "innerHTML" not in js
    assert "navigator.clipboard.writeText(summary)" in js
    assert "Платёж" not in js or "платёж" in js


def test_every_wizard_link_is_safe_local_page():
    js = (ROOT / "repair-wizard.js").read_text(encoding="utf-8")
    for path in ("account.html", "contact.html", "speed.html",
                 "network-check.html", "device-center.html", "servers.html"):
        assert path in js
        assert (ROOT / path).is_file(), path


def test_wizard_is_findable_in_navigation_catalog_sitemap():
    shell=(ROOT / "site-shell.js").read_text(encoding="utf-8")
    tools=(ROOT / "tools.html").read_text(encoding="utf-8")
    sitemap=(ROOT / "sitemap.xml").read_text(encoding="utf-8")
    assert "['repair-wizard.html','Мастер решения проблем'" in shell
    assert 'href="repair-wizard.html"' in tools
    assert "/repair-wizard.html" in sitemap
