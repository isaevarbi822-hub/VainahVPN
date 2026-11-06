"""Smoke checks for the customer-facing storefront refresh.

These checks intentionally do not create payments, orders or VPN profiles.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

ROOT = Path(__file__).resolve().parents[2]
STOREFRONT = ROOT / "storefront"


def test_customer_journey_navigation_has_working_local_destinations():
    script = (STOREFRONT / "site-shell.js").read_text(encoding="utf-8")
    css = (STOREFRONT / "site-shell.css").read_text(encoding="utf-8")
    assert "vx-journeys" in script
    assert "vx-journey" in css
    assert "aria-current" in script
    assert "trial.html" in script
    with TestClient(app) as client:
        for path in ("/", "/trial.html", "/plans.html", "/account.html", "/device-center.html"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["content-type"].startswith("text/html"), path


def test_help_uses_current_support_and_payment_copy():
    help_page = (STOREFRONT / "help.html").read_text(encoding="utf-8")
    assert "Я оплатил, но подписка не появилась" in help_page
    assert "Как получить бесплатный пробный VPN" in help_page
    assert "https://t.me/VainahSupport" in help_page
    assert "Настоящие платежи на сайте пока выключены" not in help_page
    assert "обращение попадёт в очередь поддержки" not in help_page


def test_storefront_does_not_hide_trial_or_declare_payment_available_without_api():
    home = (STOREFRONT / "index.html").read_text(encoding="utf-8")
    js = (STOREFRONT / "experience.js").read_text(encoding="utf-8")
    assert 'href="trial.html"' in home
    assert "data-checkout-message" in home
    assert "/api/shop/config" in js
    assert "checkout_ready===true" in js
    assert "Онлайн-оформление доступно после подтверждения email" in js
