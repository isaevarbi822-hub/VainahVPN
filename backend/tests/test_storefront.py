import re
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

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
        for match in re.finditer(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", source):
            link = match.group(1)
            if not link or link.startswith(("#", "data:", "mailto:", "tel:")):
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


def test_public_sitemap_is_valid_and_contains_existing_marketing_pages():
    content = (STORE / "sitemap.xml").read_text(encoding="utf-8")
    root = ElementTree.fromstring(content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    paths = [
        item.text
        for item in root.findall(".//s:loc", namespace)
    ]
    assert len(paths) >= 10
    assert len(paths) == len(set(paths))
    assert "https://vainahvpn-python-preview.onrender.com/" in paths
    assert "https://vainahvpn-python-preview.onrender.com/plans.html" in paths
    for url in paths:
        assert url is not None
        parsed = urlsplit(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "vainahvpn-python-preview.onrender.com"
        if parsed.path != "/":
            assert (STORE / parsed.path.lstrip("/")).is_file()
        assert not parsed.path.startswith(("/api/", "/app"))
        assert parsed.path not in {"/account.html", "/checkout.html", "/thanks.html"}


def test_robots_points_to_sitemap_and_prevents_api_crawling():
    robots = (STORE / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Disallow: /api/" in robots
    assert "Sitemap: https://vainahvpn-python-preview.onrender.com/sitemap.xml" in robots


def test_preview_account_checkout_and_confirmation_are_not_indexed():
    for filename in ("account.html", "checkout.html", "thanks.html", "404.html"):
        html = (STORE / filename).read_text(encoding="utf-8")
        assert '<meta name="robots" content="noindex, nofollow">' in html


def test_homepage_has_canonical_public_url():
    html = (STORE / "index.html").read_text(encoding="utf-8")
    assert (
        '<link rel="canonical" '
        'href="https://vainahvpn-python-preview.onrender.com/">'
    ) in html


def test_no_obsolete_provider_dependencies_in_project_sources():
    # A migration regression must fail even for references hidden in old HTML.
    forbidden = "net" + "lify"
    allowed = {".md", ".py", ".html", ".js", ".css", ".kt", ".kts",
               ".yml", ".yaml", ".toml", ".json", ".xml", ".cmd", ".txt"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if any(part in {".git", ".venv", "node_modules", "__pycache__"}
               for part in path.relative_to(ROOT).parts):
            continue
        assert forbidden not in path.read_text(encoding="utf-8").lower(), str(path)


def test_render_owns_deployment():
    manifest = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "vainahvpn-python-preview" in manifest
    assert "uvicorn vainah.main:app" in manifest
    assert "healthCheckPath: /api/health" in manifest


def test_account_login_uses_secure_render_telegram_api():
    code = (STORE / "account-login.js").read_text(encoding="utf-8")
    dashboard = (STORE / "account-dashboard.js").read_text(encoding="utf-8")
    assert "/api/account/overview" in dashboard
    assert "/api/telegram/config" in code
    assert "VainahTelegramWidget.mount" in code
    assert "/api/telegram/account" in dashboard
    assert "alternate-login" not in code
    assert "website-account-overview" not in dashboard
    assert "telegram-login-widget.js" in (STORE / "account.html").read_text(encoding="utf-8")
    assert "account-email-form" in (STORE / "account.html").read_text(encoding="utf-8")


def test_support_form_does_not_accept_messages_without_working_backend():
    page = (STORE / "contact.html").read_text(encoding="utf-8")
    assert 'https://t.me/VainahSupport' in page
    assert 'rel="noopener noreferrer"' in page
    assert "<form name=\"vainah-support\"" not in page


def test_telegram_login_assets_are_cache_busted_and_not_stored():
    from fastapi.testclient import TestClient

    from vainah.main import app

    page = (STORE / "account.html").read_text(encoding="utf-8")
    for name in (
        "telegram-login-widget.js",
        "account-dashboard.js",
        "account-login.js",
    ):
        assert f'{name}?v=' in page
        assert f'{name}?v="' not in page
    with TestClient(app) as client:
        for path in (
            "/account.html",
            "/telegram-login-widget.js",
            "/account-dashboard.js",
            "/account-login.js",
            "/api/telegram/config",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
            assert "no-store" in response.headers.get("Cache-Control", ""), path


def test_email_login_form_and_dashboard_are_wired():
    page = (STORE / "account.html").read_text(encoding="utf-8")
    script = (STORE / "account-login.js").read_text(encoding="utf-8")
    dashboard = (STORE / "account-dashboard.js").read_text(encoding="utf-8")
    assert 'data-auth-form="email"' in page
    assert 'data-auth-verify="email"' in page
    assert 'pattern="[0-9]{6}"' in page
    assert "/api/email-auth/request" in script
    assert "/api/email-auth/verify" in script
    assert "/api/email-auth/config" in script
    assert "/api/email-auth/account" in dashboard
    assert "/api/email-auth/logout" in dashboard


def test_email_login_shows_safe_missing_configuration_keys():
    code = (STORE / "account-login.js").read_text(encoding="utf-8")
    assert "missing_settings" in code
    assert "В Render проверь переменные" in code
