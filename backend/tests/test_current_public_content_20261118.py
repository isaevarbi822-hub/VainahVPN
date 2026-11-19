"""Public copy regression: November 18 version is not mixed with old checkout claims.

This only reads storefront files. It never touches payment providers, accounts,
subscription provisioning, or legal status of the seller.
"""
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "storefront"
CURRENT_PAGES = (
    "index", "plans", "about", "help", "features", "hub", "assistant",
    "trial", "library", "account", "status", "diagnostics", "tools",
    "command-hub", "privacy", "terms", "oferta", "refund",
    "whats-new", "start", "compare", "guide", "contact",
    "device-center", "glossary", "checklist",
)


def test_no_old_payment_provider_claims_in_current_content():
    obsolete = (
        "RollyPay при доступной кассе",
        "Platega пока не включена",
        "Platega находится на этапе подготовки",
        "Подключение Platega не заявляется",
        "Оно не включает Platega",
        "не подтверждает, что Platega подключена",
        "от 25 ₽ за 2 дня",
        "Защищённое оформление через RollyPay при подтверждённой",
    )
    for name in CURRENT_PAGES:
        html = (SITE / f"{name}.html").read_text(encoding="utf-8")
        for phrase in obsolete:
            assert phrase not in html, f"{name}: {phrase}"


def test_current_checkout_and_privacy_refer_to_real_two_gateway_flow():
    checkout = (SITE / "checkout.html").read_text(encoding="utf-8")
    privacy = (SITE / "privacy.html").read_text(encoding="utf-8")
    terms = (SITE / "terms.html").read_text(encoding="utf-8")
    oferta = (SITE / "oferta.html").read_text(encoding="utf-8")
    refund = (SITE / "refund.html").read_text(encoding="utf-8")
    assert 'name="shop-gateway" value="rollypay"' in checkout
    assert 'name="shop-gateway" value="platega"' in checkout
    assert "RollyPay</strong> или <strong>Platega" in privacy
    assert "не считает заказ оплаченным только по факту открытия" in privacy
    assert "Доступность конкретного способа оплаты определяется сервером" in terms
    assert "Подтверждение оплаты и выдача доступа" in oferta
    assert "юридической проверки" in refund
    for page in (privacy, terms, oferta, refund):
        assert "account.html" in page or "support-center.html" in page


def test_archived_concepts_are_not_promoted_as_current_offers():
    plans = (SITE / "plans.html").read_text(encoding="utf-8")
    release = (SITE / "whats-new.html").read_text(encoding="utf-8")
    hub = (SITE / "command-hub.html").read_text(encoding="utf-8")
    assert '<details class="container vx-concept-archive">' in plans
    assert plans.index('id="catalog"') < plans.index(
        '<details class="container vx-concept-archive">'
    )
    assert '<details class="super-archive">' in release
    assert release.index('id="vx-mega-20261118"') < release.index(
        '<details class="super-archive">'
    )
    assert "Избранное и сравнение" in hub
    assert "12 новых вариантов" not in hub


def test_current_copy_preserves_payment_safety_distinctions():
    pages = {
        name: (SITE / f"{name}.html").read_text(encoding="utf-8")
        for name in ("index", "plans", "about", "help", "trial", "status")
    }
    assert "data-checkout-readiness" in pages["plans"]
    assert "не списывает деньги" in pages["index"]
    assert "RollyPay или Platega" in pages["about"]
    assert "RollyPay или Platega" in pages["help"]
    assert "Актуальные цены загружаются с сервера" in pages["trial"]
    assert "не подтверждает отдельный платёж" in pages["status"]
