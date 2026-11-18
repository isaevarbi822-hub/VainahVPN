"""Offline checks for customer-facing legal documents and payment footer."""

from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "storefront"
BASE = "https://vainahvpn.onrender.com"
DOCS = (
    ("oferta.html", "Публичная оферта"),
    ("terms.html", "Пользовательское соглашение"),
    ("privacy.html", "Политика конфиденциальности"),
    ("refund.html", "Условия возврата"),
)


def test_checkout_contains_four_independent_links_below_payment_button():
    html = (STORE / "checkout.html").read_text(encoding="utf-8")
    assert html.count('data-checkout-documents') == 1
    start = html.index('id="shop-buy"')
    end = html.index("</nav>", start)
    documents = html[start:end]
    assert documents.count('<li><a href="') == 4
    for filename, name in DOCS:
        assert f'href="{BASE}/{filename}"' in documents
        assert name in documents
    assert html.index('id="shop-buy"') < html.index("data-checkout-documents")


def test_all_documents_are_public_html_with_canonical_urls():
    with TestClient(app) as client:
        for filename, title in DOCS:
            response = client.get(f"/{filename}")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert title in response.text
            assert f'<link rel="canonical" href="{BASE}/{filename}">' in response.text


def test_offer_and_refund_do_not_falsely_claim_approved_business():
    for filename in ("oferta.html", "refund.html"):
        html = (STORE / filename).read_text(encoding="utf-8")
        assert 'content="noindex, follow"' in html
        assert "необходимо указать реальные сведения о поставщике услуги" in html
        assert "не подтверждает" in html or "не заявляется" in html


def test_site_documents_discoverable_on_home_plans_privacy_terms():
    for filename in ("index.html", "plans.html", "privacy.html", "terms.html"):
        html = (STORE / filename).read_text(encoding="utf-8")
        for doc, _ in DOCS:
            assert f'href="{BASE}/{doc}"' in html
        assert "legal-link-strip.css?v=1" in html


def test_provider_choices_start_disabled_and_documents_have_no_payment_controls():
    html = (STORE / "checkout.html").read_text(encoding="utf-8")
    assert 'id="shop-gateway-platega" value="platega" disabled' in html
    assert 'id="shop-gateway-rollypay" value="rollypay" checked disabled' in html
    assert 'id="shop-buy"' in html
    assert "RollyPay" in html
    # All new legal documents are static and contain no hidden payment controls.
    for filename in ("oferta.html", "refund.html"):
        page = (STORE / filename).read_text(encoding="utf-8")
        assert "/api/shop/checkout" not in page
        assert "X-Secret" not in page
