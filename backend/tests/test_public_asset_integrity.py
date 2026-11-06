"""Catch missing public HTML links and scripts before a release reaches Render."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("a", "link", "script", "img", "source"):
            return
        for key, value in attrs:
            if key in ("href", "src") and value:
                self.references.append((tag, value))


def test_all_public_html_local_links_and_assets_exist():
    broken = []
    for page in sorted(SITE.glob("*.html")):
        reader = Refs()
        reader.feed(page.read_text(encoding="utf-8"))
        for tag, raw in reader.references:
            value = raw.strip()
            if (not value or value == "/" or value.startswith(
                    ("#", "//", "/api/", "/app", "mailto:", "tel:", "data:")
            )):
                continue
            parts = urlsplit(value)
            if parts.scheme or parts.netloc:
                continue
            local = unquote(parts.path).lstrip("/")
            if not local or "{" in local or "}" in local:
                continue
            file = (SITE / local).resolve()
            if not file.is_relative_to(SITE.resolve()) or not file.is_file():
                broken.append(f"{page.name}: {tag} {raw}")
    assert not broken, "Broken internal resources:\n" + "\n".join(broken)


def test_restored_modules_and_new_network_tools_load():
    with TestClient(app) as client:
        for path in (
            "/toolkit-ui.mjs", "/command-center.mjs",
            "/network-toolkit.html", "/network-toolkit.js", "/network-toolkit.css",
            "/assistant.html", "/library.html", "/device-center.html",
            "/diagnostics.html", "/hub.html",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.content, path


def test_site_has_no_outdated_checkout_or_telegram_login_promises():
    pages = {
        name: (SITE / name).read_text(encoding="utf-8")
        for name in ("library.html", "hub.html", "device-center.html",
                     "diagnostics.html")
    }
    assert "Telegram Login, выбор плана" not in pages["library.html"]
    assert "Сейчас выключена" not in pages["hub.html"]
    assert "после входа через Telegram" not in pages["device-center.html"]
    assert "Ошибка Telegram Login" not in pages["diagnostics.html"]


def test_new_calculator_is_local_and_protects_results():
    page = (SITE / "network-toolkit.html").read_text(encoding="utf-8")
    script = (SITE / "network-toolkit.js").read_text(encoding="utf-8")
    for name in ("convert", "download", "upload", "stream",
                 "quota", "daily", "compare", "latency"):
        assert f'data-calculator="{name}"' in page
        assert f"    {name}(form)" in script
    assert "fetch(" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "navigator.clipboard" in script
    assert "network-toolkit.html" in (SITE / "sitemap.xml").read_text(
        encoding="utf-8"
    )


def test_recovered_modules_only_use_safe_read_only_api_endpoints():
    toolkit = (SITE / "toolkit-ui.mjs").read_text(encoding="utf-8")
    command = (SITE / "command-center.mjs").read_text(encoding="utf-8")
    assert "/api/shop/plans" in toolkit
    assert "/api/account/overview" in command
    assert "/api/site/services" in command
    assert "method:'POST'" not in toolkit
    assert "method:'POST'" not in command
    assert "innerHTML" not in toolkit
    assert "innerHTML" not in command
