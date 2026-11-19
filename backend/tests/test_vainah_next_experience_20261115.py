"""Vainah Next: read-only, responsive customer journey and static catalog correctness."""
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

ROOT = Path(__file__).resolve().parents[2] / "storefront"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_new_hero_journey_is_accessible_and_on_homepage():
    html = _read("index.html")
    assert 'id="vainah-route" data-vx-next-journey' in html
    assert 'data-vx-next-status role="status" aria-live="polite"' in html
    assert 'data-vx-next-results aria-live="polite"' in html
    assert html.count('data-vx-next-choice="platform"') == 5
    assert html.count('data-vx-next-choice="devices"') == 2
    assert html.count('data-vx-next-choice="days"') == 3
    assert 'vainah-next.js?v=20261115-reliable2' in html
    assert 'vainah-next.css?v=20261115-next1' in html


def test_next_journey_never_creates_payment_or_uses_fake_prices():
    script = _read("vainah-next.js")
    assert "apiOrigin+'/api/site/tariffs'" in script
    assert "checkout_supported===true" in script
    assert "data.plans.length!==76" in script
    assert "confirmed.length!==75" in script
    assert "money(Number(plan.price_rub))" in script
    assert "method:'GET'" in script
    assert "method:'POST'" not in script
    assert "/api/shop/checkout" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "Не удалось проверить цены на сервере" in script


def test_plans_catalog_reads_cross_origin_readonly_api_on_static_site():
    script = _read("tariff-catalog.js")
    assert "window.location.origin===staticOrigin" in script
    assert "fetch(apiOrigin+'/api/site/tariffs'" in script
    # Public readiness now has explicit read-only CORS, with no checkout writes.
    assert "async function checkCheckoutReadiness()" in script
    assert "fetch(apiOrigin+'/api/shop/config'" in script
    assert "method:'GET'" in script and "credentials:'omit'" in script
    assert "data.platega_ready?'Platega':null" in script
    assert "['3','6'].includes(initial.get('devices'))" in script
    assert "['days','price','daily','longest'].includes(initial.get('sort'))" in script
    assert "fetch(apiOrigin+'/api/shop/checkout'" not in script


def test_home_plans_checkout_and_hub_have_real_navigation():
    home = _read("index.html")
    plans = _read("plans.html")
    checkout = _read("checkout.html")
    hub = _read("command-hub.html")
    assert 'href="plans.html?devices=3&amp;sort=days"' in home
    assert 'href="index.html#vainah-route"' in plans
    assert "Подбери подписку по сроку, цене и числу устройств" in plans
    assert "вариантовова" not in plans
    assert "Умный подбор VPN" in hub
    assert 'href="index.html#vainah-route"' in hub
    assert 'class="shop-gateways"' in checkout
    assert 'name="shop-gateway" value="platega" disabled' in checkout
    assert 'id="shop-buy"' in checkout
    assert "RollyPay" in checkout
    assert 'href="https://vainahvpn.onrender.com/refund.html"' in checkout
    assert 'href="https://vainahvpn.onrender.com/terms.html"' in checkout


def test_global_design_loads_purple_styles_without_js_checkout_changes():
    shell = _read("site-shell.js")
    css = _read("vainah-next.css")
    assert "vainah-next.css?v=20261115-next2" in shell
    assert "document.createElement('link')" in shell
    assert '--fresh-bg:#080b15;' in css
    assert '--fresh-accent:#b69aff;' in css
    assert '@media(max-width:950px)' in css
    assert '@media(max-width:620px)' in css
    assert '@media(prefers-reduced-motion:reduce)' in css


def test_existing_server_catalog_is_unchanged_and_still_75_paid():
    with TestClient(app) as client:
        response = client.get("/api/site/tariffs")
    assert response.status_code == 200
    catalog = response.json()
    assert catalog["total"] == 76
    assert len(catalog["plans"]) == 76
    assert sum(plan.get("status") == "existing" for plan in catalog["plans"]) == 75
