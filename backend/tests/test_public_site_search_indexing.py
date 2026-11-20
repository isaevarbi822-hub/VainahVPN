"""Public site SEO smoke tests: accessible sitemap, canonical pages, private noindex."""
from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from vainah.main import app

BASE = "https://vainahvpn.online"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def test_sitemap_and_robots_expose_only_public_canonical_pages():
    with TestClient(app) as client:
        robot = client.get("/robots.txt")
        assert robot.status_code == 200
        assert "Allow: /" in robot.text
        assert "Disallow: /api/" in robot.text
        assert f"Sitemap: {BASE}/sitemap.xml" in robot.text

        sitemap = client.get("/sitemap.xml")
        assert sitemap.status_code == 200
        xml = ElementTree.fromstring(sitemap.content)
        addresses = [
            node.text for node in xml.findall(".//s:loc", NS)
        ]
        assert len(addresses) >= 10
        assert len(addresses) == len(set(addresses))
        assert "vainahvpn.onrender.com" not in sitemap.text
        assert len(addresses) == 24
        assert BASE + "/" in addresses
        for url in addresses:
            assert url is not None and url.startswith(BASE + "/")
            path = url[len(BASE):]
            assert path == "/" or path.endswith(".html")
            assert "/account" not in path and "/checkout" not in path
            page = client.get(path)
            assert page.status_code == 200, path
            assert page.headers["content-type"].startswith("text/html")
            assert (
                f'<link rel="canonical" href="{url}">' in page.text
            ), f"Missing canonical for {path}"
            assert not re.search(
                r'<meta[^>]+name=["\']robots["\'][^>]+noindex',
                page.text,
                flags=re.IGNORECASE,
            ), f"Public sitemap page is noindex: {path}"


def test_private_pages_are_not_advertised_for_google_indexing():
    with TestClient(app) as client:
        for path in ("/account.html", "/checkout.html"):
            page = client.get(path)
            assert page.status_code == 200
            assert 'name="robots" content="noindex, nofollow"' in page.text


def test_homepage_contains_google_search_console_verification_tag():
    with TestClient(app) as client:
        homepage = client.get("/")
        assert homepage.status_code == 200
        assert (
            '<meta name="google-site-verification" '
            'content="flLPB_2_9zWLkQ6Dg_Y9GsTyNtCS1ORGpW0hia6i7hU" />'
        ) in homepage.text


def test_homepage_brand_metadata_matches_visible_heading():
    with TestClient(app) as client:
        homepage = client.get("/")
    assert homepage.status_code == 200
    html = homepage.text
    assert "<title>Vainah VPN — тарифы, подключение и личный кабинет</title>" in html
    assert '<meta name="description" content="Vainah VPN — VPN-сервис' in html
    assert '<h1 id="home-title"><small class="refresh-home-brand">Vainah VPN</small>' in html
    assert '<link rel="canonical" href="https://vainahvpn.online/">' in html
    match = re.search(r'<script type="application/ld\\+json">(.*?)</script>', html, re.S)
    assert match is not None
    markup = json.loads(match.group(1))
    websites = [node for node in markup.get("@graph", [])
                if node.get("@type") == "WebSite"]
    assert len(websites) == 1
    assert websites[0]["name"] == "Vainah VPN"
    assert websites[0]["url"] == "https://vainahvpn.online/"
    assert websites[0]["alternateName"] == "Вайнах VPN"


def test_public_contact_page_is_not_redirected_away_from_indexed_domain():
    site = Path(__file__).resolve().parents[2] / "storefront"
    shell = (site / "site-shell.js").read_text(encoding="utf-8")
    routes = shell.split("const backendPages=new Set([", 1)[1].split("]);", 1)[0]
    assert "'/contact.html'" not in routes
    # Customer authentication, payment and private support pages remain backend-only.
    for protected in ("'/account.html'", "'/checkout.html'", "'/support-center.html'"):
        assert protected in routes
    with TestClient(app) as client:
        contact = client.get("/contact.html")
    assert contact.status_code == 200
    assert '<link rel="canonical" href="https://vainahvpn.online/contact.html">' in contact.text
    assert 'href="/"' in contact.text
    assert "site-shell.js?v=20261120-seo-route1" in contact.text
