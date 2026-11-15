"""Platega bank-provided privacy and agreement template coverage without false statements."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "storefront"


def _page(name: str) -> str:
    return (STORE / name).read_text(encoding="utf-8")


def test_privacy_matches_seven_bank_sample_sections_and_date():
    html = _page("privacy.html")
    assert '<h1>Политика конфиденциальности</h1>' in html
    assert '<time datetime="2026-11-15">' in html
    for heading in (
        "1. Общие положения", "2. Сбор информации",
        "3. Использование информации", "4. Передача информации третьим лицам",
        "5. Хранение и защита данных", "6. Ответственность и права Пользователя",
        "7. Изменения в Политике",
    ):
        assert f"<h2>{heading}</h2>" in html
    for provider in ("RollyPay", "H1Cloud", "Google", "Telegram"):
        assert provider in html
    assert "Platega пока не включена" in html
    assert "срок хранения" in html.lower()
    assert 'href="contact.html"' in html


def test_terms_matches_ten_bank_sample_sections_and_actual_vpn_service():
    html = _page("terms.html")
    assert '<h1>Пользовательское соглашение</h1>' in html
    assert '<time datetime="2026-11-15">' in html
    for heading in (
        "1. Общие положения", "2. Характер услуг и цифровых продуктов",
        "3. Гарантии и ответственность сторон", "4. Законность использования",
        "5. Интеллектуальная собственность", "6. Ограничение доступа",
        "7. Платежи и возвраты", "8. Конфиденциальность",
        "9. Изменение условий", "10. Контактная информация",
    ):
        assert f"<h2>{heading}</h2>" in html
    for linked in ("oferta.html", "refund.html", "privacy.html", "contact.html"):
        assert f'href="{linked}"' in html
    assert "VPN-доступ" in html
    assert "Platega" in html
    assert "не устанавливаются универсальный запрет возврата" in html.lower()
    assert "не заменяют проверку фактического продавца" in html


def test_new_documents_do_not_fabricate_merchant_details_or_enable_payments():
    for name in ("privacy.html", "terms.html"):
        html = _page(name)
        assert "до использования" in html
        assert "/api/shop/checkout" not in html
        assert "X-Secret" not in html
    for name in ("oferta.html", "refund.html"):
        html = _page(name)
        assert "Предварительная редакция: 15 ноября 2026 года" in html
