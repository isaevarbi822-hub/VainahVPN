from pathlib import Path
from urllib.parse import urlsplit

import re

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "storefront"


def test_historical_storefront_pages_and_checkout_assets_exist():
    required = (
        "index.html", "plans.html", "features.html", "servers.html",
        "devices.html", "guide.html", "security.html", "speed.html",
        "troubleshooting.html", "help.html", "contact.html", "about.html",
        "privacy.html", "terms.html", "account.html", "checkout.html",
        "checkout-flow.css", "checkout-flow.js", "site-shell.css",
        "site-shell.js",
    )
    for file in required:
        assert (STORE / file).is_file(), file


def test_local_page_links_have_files():
    missing = []
    for html in STORE.glob("*.html"):
        source = html.read_text(encoding="utf-8")
        for match in re.finditer(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', source):
            link = match.group(1)
            if not link or link.startswith(("#", "data:", "mailto:", "tel:", "/.netlify/")):
                continue
            u = urlsplit(link)
            if u.scheme or u.netloc:
                continue
            if not (u.path.endswith((".html", ".css", ".js", ".svg", ".png", ".jpg", ".webp"))):
                continue
            path = u.path.lstrip("/")
            if not (STORE / path).is_file():
                missing.append((html.name, path))
    assert not missing, missing


def test_checkout_requires_explicit_server_readiness():
    markup = (STORE / "checkout.html").read_text(encoding="utf-8")
    script = (STORE / "checkout-flow.js").read_text(encoding="utf-8")
    assert "api/shop/config" in script
    assert "api/shop/plans" in script
    assert "state.config?.checkout_ready" in script
    assert "shop-buy" in markup
    assert "shop-test-create" in markup
