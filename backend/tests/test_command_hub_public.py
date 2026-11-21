"""Static regression checks for the public Vainah Control refresh.

These tests never contact external services or execute checkout operations.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOREFRONT = ROOT / "storefront"


def test_command_hub_assets_and_navigation_exist():
    homepage = (STOREFRONT / "index.html").read_text(encoding="utf-8")
    shell = (STOREFRONT / "site-shell.js").read_text(encoding="utf-8")
    hub = (STOREFRONT / "command-hub.html").read_text(encoding="utf-8")

    assert 'href="command-hub.html"' in homepage
    assert "command-hub.html" in shell
    assert 'href="command-hub.css?v=20261114-2"' in hub
    assert 'src="command-hub.js?v=20261115-reliable2-catalog13"' in hub
    for element_id in (
        "vx-hub-search",
        "vx-hub-features",
        "vx-hub-steps",
        "vx-hub-recommendation",
        "vx-api-status",
        "vx-checkout-status",
    ):
        assert f'id="{element_id}"' in hub


def test_public_sitemap_excludes_private_routes():
    tree = ET.parse(STOREFRONT / "sitemap.xml")
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = [el.text for el in tree.findall(".//s:loc", namespace)]
    assert "https://vainahvpn.online/command-hub.html" in locations
    assert all(url.startswith("https://vainahvpn.online/") for url in locations)
    assert not any("support-center.html" in url for url in locations)
    assert not any("/api/" in url or "checkout.html" in url for url in locations)


def test_control_hub_does_not_mutate_payment_or_account_data():
    js = (STOREFRONT / "command-hub.js").read_text(encoding="utf-8")
    assert "method: 'GET'" in js
    assert "/api/health" in js
    assert "/api/shop/config" in js
    assert "typeof config.checkout_ready === 'boolean'" in js
    assert "/api/shop/checkout" not in js
    assert "method: 'POST'" not in js
    assert "credentials: 'omit'" in js


def test_responsive_and_reduced_motion_css():
    css = (STOREFRONT / "command-hub.css").read_text(encoding="utf-8")
    assert "@media(max-width:550px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert ":focus-visible" in css
