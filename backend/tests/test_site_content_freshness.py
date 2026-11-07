"""Prevent obsolete marketing and checkout facts from returning to Vainah VPN.

Prices and checkout approval are server-controlled. Static pages should describe
the verified product, not cite legacy Telegram-only purchasing or obsolete rates.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from vainah.billing import CATALOG, get_plan, price_rub
from vainah.main import app
from vainah.tariff_catalog import public_tariff_catalog

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_all_public_pages_remove_outdated_purchase_footer_and_login_label():
    pages = sorted(SITE.glob("*.html"))
    assert len(pages) >= 45
    old_fragments = (
        "Сайт и Telegram Mini App — разные интерфейсы одного проекта",
        'aria-label="Войти через Telegram в личный кабинет"',
        'aria-label="Войти в личный кабинет через почту или Telegram"',
        "Настоящий сайт не принимает оплату",
        "оформление происходит в отдельном Telegram-боте",
    )
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for old in old_fragments:
            assert old not in text, (page.name, old)


def test_public_prices_and_marketing_describe_the_actual_fifty_plan_backend():
    catalog = public_tariff_catalog()
    assert catalog["existing_paid_count"] == len(CATALOG) == 50
    assert catalog["total"] == 51
    assert len({plan["id"] for plan in CATALOG}) == 50
    assert min(plan["days"] for plan in CATALOG) == 2
    assert max(plan["days"] for plan in CATALOG) == 730
    assert min(plan["kopeks"] for plan in CATALOG) == 2500
    assert price_rub(get_plan("30")) == "149.00"
    assert price_rub(get_plan("365-family")) == "1499.00"
    with TestClient(app) as client:
        response = client.get("/api/site/tariffs")
        assert response.status_code == 200
        assert response.json()["total"] == 51
        paid = client.get("/api/shop/plans")
        assert paid.status_code == 200
        assert len(paid.json()["items"]) == 50


def test_shop_and_help_no_longer_advertise_legacy_rates_or_telegram_checkout():
    expected = {
        "checkout.html": ("50 платных тарифов", "RollyPay"),
        "help.html": ("50 платных тарифов", "серверного каталога"),
        "hub.html": ("Срок от 2 до 730 дней", "RollyPay"),
        "trial.html": ("25 ₽ за 2 дня", "10 ГБ"),
        "terms.html": ("50 платных тарифов", "RollyPay"),
        "contact.html": ("центр поддержки", "@VainahSupport"),
        "troubleshooting.html": ("личный кабинет", "повторный платёж"),
    }
    for filename, fragments in expected.items():
        text = (SITE / filename).read_text("utf-8")
        for fragment in fragments:
            assert fragment.casefold() in text.casefold(), (filename, fragment)
    assert "30 дней — 99 ₽, 60 — 160 ₽" not in (SITE / "help.html").read_text("utf-8")
    assert "Тарифы от 99 ₽ за 30 дней" not in (SITE / "trial.html").read_text("utf-8")
    assert "один из 21 платного тарифа" not in (SITE / "checkout.html").read_text("utf-8")
    operator_js = (SITE / "operator-pilot.js").read_text("utf-8")
    assert "99 ₽" not in operator_js
    assert "текущей серверной цене" in operator_js
    assert "/api/shop/checkout" not in (SITE / "site-shell.js").read_text("utf-8")
