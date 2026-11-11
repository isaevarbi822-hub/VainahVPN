"""Public crawl endpoints stay available without private-account exposure."""
from fastapi.testclient import TestClient

from vainah.main import app


def test_public_robots_and_sitemap_are_fetchable():
    with TestClient(app) as client:
        robots = client.get("/robots.txt")
        assert robots.status_code == 200
        assert robots.headers["content-type"].startswith("text/plain")
        assert "max-age=300" in robots.headers["cache-control"]
        rules = robots.text.splitlines()
        assert "User-agent: *" in rules
        assert "Allow: /" in rules
        assert "Disallow: /" not in rules
        assert "Disallow: /api/" in rules
        assert "Sitemap: https://vainahvpn.onrender.com/sitemap.xml" in rules

        sitemap = client.get("/sitemap.xml")
        assert sitemap.status_code == 200
        assert sitemap.headers["content-type"].startswith("application/xml")
        assert "https://vainahvpn.onrender.com/" in sitemap.text
        assert "/api/" not in sitemap.text
        assert "account.html" not in sitemap.text
        assert "checkout.html" not in sitemap.text


def test_homepage_is_not_marked_noindex():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "noindex" not in response.headers.get("x-robots-tag", "").lower()
        assert '<link rel="canonical" href="https://vainahvpn.onrender.com/">' in response.text
