"""Public site SEO smoke tests: accessible sitemap, canonical pages, private noindex."""
from __future__ import annotations

import re
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from vainah.main import app

BASE = "https://vainahvpn-python-preview.onrender.com"
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
