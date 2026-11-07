"""Prevent stale pre-RollyPay copy and pre-50-plan prices returning to the site.

This tests marketing copy only; it never changes payment or fulfillment state.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from vainah.billing import CATALOG, price_rub
from vainah.main import app
from vainah.tariff_catalog import public_tariff_catalog

SITE = Path(__file__).resolve().parents[2] / "storefront"
PUBLIC_PAGES = (
    "index.html", "plans.html", "checkout.html", "compare.html",
    "assistant.html", "hub.html", "whats-new.html", "about.html",
    "features.html", "start.html", "help.html", "trial.html",
    "terms.html", "privacy.html", "account.html", "servers.html",
    "status.html", "device-center.html", "support-center.html",
)
OUTDATED = (
    "30 дней — 99 ₽, 60 — 160 ₽",
    "Тарифы от 99 ₽ за 30 дней",
    "Сравните 12 вариантов Vainah VPN",
    "пять предложений в подготовке и пробный день",
    "Настоящий сайт не принимает оплату",
    "оформление происходит в отдельном Telegram-боте",
    "Покупки в Telegram-боте работают отдельно",
    "Выбери один из 21 платного тарифа",
    "Все 21 тарифа",
    "21 платный тариф с оформлением",
    "21 тариф + пробник",
)


def test_all_public_pages_have_no_superseded_pricing_or_checkout_claims():
    for name in PUBLIC_PAGES:
        html = (SITE / name).read_text(encoding="utf-8")
        assert "<main" in html, name
        for phrase in OUTDATED:
            assert phrase not in html, (name, phrase)


def test_current_canonical_prices_and_exposed_site_catalog_match():
    data = public_tariff_catalog()
    assert data["total"] == 51
    assert data["existing_paid_count"] == len(CATALOG) == 50
    assert data["trial_count"] == 1
    assert data["upcoming_count"] == 0
    prices = {p["id"]: price_rub(p) for p in CATALOG}
    assert prices["pulse-2d"] == "25.00"
    assert prices["30"] == "149.00"
    assert prices["365-family"] == "1499.00"
    for row in data["plans"]:
        if row["id"] == "trial-free":
            assert row["price_rub"] == "0.00"
            assert row["devices"] == 2
            assert row["traffic_gb"] == 10
            assert row["checkout_supported"] is False
            continue
        assert row["price_rub"] == prices[row["id"]]
        assert row["checkout_path"] == "/checkout.html?plan=" + row["id"]


def test_key_customer_pages_describe_the_correct_purchase_process():
    index = (SITE / "index.html").read_text(encoding="utf-8")
    help_page = (SITE / "help.html").read_text(encoding="utf-8")
    checkout = (SITE / "checkout.html").read_text(encoding="utf-8")
    terms = (SITE / "terms.html").read_text(encoding="utf-8")
    trial = (SITE / "trial.html").read_text(encoding="utf-8")
    compare = (SITE / "compare.html").read_text(encoding="utf-8")

    assert "50 платных тарифов" in index
    assert "50 тарифов + пробник" in index
    assert "50 платных тарифов" in help_page
    assert "support-center.html" in help_page
    assert "один из 50 платных тарифов" in checkout
    assert "Все 50 тарифов" in checkout
    assert "50 платных тарифов" in compare
    assert "отдельный бесплатный пробный день" in terms
    assert "RollyPay" in terms
    assert "H1Cloud" in terms
    assert "2 дня за 25 ₽" in trial
    assert "149 ₽ за 30 дней" in trial


def test_refreshed_pages_are_served_by_python_application():
    with TestClient(app) as client:
        for name in PUBLIC_PAGES:
            response = client.get("/" + name)
            assert response.status_code == 200, name
            assert "<main" in response.text
