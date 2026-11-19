"""Browser checks against real storefront routes and a disposable order ledger."""
import hashlib
import hmac
import json
import shutil
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from vainah import customer_portal, email_auth, live_checkout, platega
from vainah.billing import get_plan, price_rub
from vainah.main import app

SITE = "https://vainahvpn.onrender.com"
BACKEND = "https://vainahvpn-python-preview.onrender.com"
EMAIL = "browser-buyer@example.com"
SUBSCRIPTION = "https://sub.example.com/test-only-customer-access"
SIGNING = "test-only-browser-webhook-key"
MERCHANT = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
PLATEGA_SECRET = "test-only-browser-platega-secret"
PLAN = "30-family"


@pytest.fixture
def purchase_browser(monkeypatch, postgres_url):
    playwright = pytest.importorskip("playwright.sync_api")
    binary = shutil.which("chromium") or shutil.which("google-chrome")
    if binary is None:
        pytest.skip("Chromium is required for the purchase journey")

    for name, value in {
        "PUBLIC_SITE_ORIGIN": SITE,
        "DATABASE_URL": postgres_url,
        "SESSION_SIGNING_KEY": "test-only-browser-session-key-" + "x" * 40,
        "VAINAH_LIVE_CUSTOMER_ACCESS_ENABLED": "enabled",
        "ROLLYPAY_API_KEY": "test-only-browser-rollypay-key",
        "ROLLYPAY_SIGNING_SECRET": SIGNING,
        "PLATEGA_MERCHANT_ID": MERCHANT,
        "PLATEGA_SECRET": PLATEGA_SECRET,
        "PLATEGA_ENABLED": "enabled",
        "PLATEGA_WEBHOOK_CONFIRMED": "enabled",
        "RESEND_API_KEY": "re_test_only_browser_key",
        "VAINAH_EMAIL_FROM": "hello@example.com",
    }.items():
        monkeypatch.setenv(name, value)

    invoices = []
    deliveries = []
    codes = {}

    monkeypatch.setattr(live_checkout, "live_ready", lambda: True)
    monkeypatch.setattr(platega, "live_ready", lambda: True)

    async def send_code(email, code):
        codes[email] = code

    async def rollypay_invoice(*, order_id, plan_id, **_):
        amount = price_rub(get_plan(plan_id))
        invoices.append((order_id, "pay_mockbrowser1234", amount))
        return SimpleNamespace(
            payment_id=invoices[-1][1], pay_url="https://pay.rollypay.io/pay/browserfixture",
        )

    async def platega_invoice(*, order_id, amount_rub, **_):
        payment = "3fa85f64-5717-4562-b3fc-2c963f66afa7"
        invoices.append((order_id, payment, f"{amount_rub:.2f}"))
        return payment, "https://pay.platega.io?fixture=browser"

    async def platega_status(payment_id):
        order, payment, amount = invoices[-1]
        assert payment_id == payment
        return {"payload": order, "status": "CONFIRMED",
                "paymentDetails": {"amount": amount, "currency": "RUB"}}

    async def fulfill(*, ledger, order_id, **_):
        claim = ledger.claim_delivery_once(order_id)
        assert claim is not None and claim.plan_id == PLAN
        assert ledger.mark_delivered(order_id=order_id, subscription_url=SUBSCRIPTION,
                                     panel_confirmed=True)
        deliveries.append(order_id)
        return {"status": "delivered", "vpn_delivered": True}

    async def receipt(**_):
        return None

    async def h1_state(email):
        assert email == EMAIL
        return {"status": "active" if deliveries else "not_found",
                "message": "Тестовый профиль", "expires_at": "2030-01-01T00:00:00Z"}

    monkeypatch.setattr(email_auth, "send_verification_code", send_code)
    monkeypatch.setattr(live_checkout, "create_hosted_live_invoice", rollypay_invoice)
    monkeypatch.setattr(platega, "_new_invoice", platega_invoice)
    monkeypatch.setattr(platega, "_provider_transaction", platega_status)
    monkeypatch.setattr(customer_portal, "h1_email_customer_state", h1_state)
    for gateway in (live_checkout, platega):
        monkeypatch.setattr(gateway, "fulfill_paid_order_once", fulfill)
        monkeypatch.setattr(gateway, "send_paid_access_receipt_once", receipt)

    with playwright.sync_playwright() as session, TestClient(app, base_url=BACKEND) as client:
        browser = session.chromium.launch(executable_path=binary, args=["--no-sandbox"])
        try:
            yield browser, client, codes, invoices, deliveries
        finally:
            browser.close()


@pytest.mark.parametrize(("gateway", "width", "height"), [
    ("rollypay", 1440, 900),
    ("platega", 390, 844),
])
def test_purchase_from_static_catalog_to_paid_subscription(
    purchase_browser, gateway, width, height,
):
    from playwright.sync_api import expect

    browser, client, codes, invoices, deliveries = purchase_browser
    context = browser.new_context(
        viewport={"width": width, "height": height},
        is_mobile=width < 500, has_touch=width < 500,
    )
    page = context.new_page()
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    config_failure = True
    checkout_loaded = False
    dropped_invoice_reply = False
    session_expired = False
    endpoint = "/api/shop/checkout" + ("/platega" if gateway == "platega" else "")

    def serve(route):
        nonlocal config_failure, checkout_loaded, dropped_invoice_reply
        request = route.request
        url = urlsplit(request.url)
        if url.hostname in {"pay.rollypay.io", "pay.platega.io"}:
            route.fulfill(content_type="text/html; charset=utf-8", body=(
                f'<a href="{BACKEND}/account.html">Вернуться в кабинет</a>'
            ))
            return
        if url.hostname not in {urlsplit(SITE).hostname, urlsplit(BACKEND).hostname}:
            route.abort()
            return
        if url.path == "/checkout.html" and url.hostname == urlsplit(BACKEND).hostname:
            checkout_loaded = True
        if url.path == "/api/shop/config" and config_failure and checkout_loaded:
            config_failure = False
            route.fulfill(status=503, json={"detail": "Temporary fixture failure"})
            return
        if (url.path == "/api/email-auth/request"
                and request.post_data_json["email"] == "second@example.com"):
            route.fulfill(status=503, json={"detail": "EMAIL_DELIVERY_UNAVAILABLE"})
            return
        if url.path == "/api/account/overview" and session_expired:
            route.fulfill(status=401, json={"detail": "ACCOUNT_LOGIN_REQUIRED"})
            return
        # Cookies come from Chromium. TestClient must not supply its own.
        client.cookies.clear()
        response = client.request(
            request.method, request.url, headers=request.all_headers(),
            content=request.post_data_buffer,
        )
        if url.path == endpoint and response.is_success and not dropped_invoice_reply:
            dropped_invoice_reply = True
            route.abort()
            return
        headers = dict(response.headers)
        if "set-cookie" in headers:
            headers["set-cookie"] = "\n".join(response.headers.get_list("set-cookie"))
        if url.hostname == urlsplit(SITE).hostname:
            # The public hostname serves static files, without FastAPI headers.
            headers.pop("content-security-policy", None)
        route.fulfill(status=response.status_code, body=response.content,
                      headers=headers)

    page.route("**/*", serve)
    page.goto(SITE + "/plans.html")
    search = page.locator("[data-tariff-search]")
    page.locator('[data-tariff-preset="family"]').click()
    expect(page.locator("[data-tariff-devices]")).to_have_value("6")
    search.fill("30")
    expect(page.locator(".tariff-card:visible")).to_have_count(1)
    assert "q" not in parse_qs(urlsplit(page.url).query)
    page.reload()
    expect(search).to_have_value("30")
    expect(page.locator(".tariff-card:visible")).to_have_count(1)
    offer = page.locator(".tariff-card").filter(has_text="Семейный месяц")
    expect(offer).to_be_visible()
    expect(offer).to_contain_text("289 ₽")
    offer.get_by_role("link", name="Выбрать тариф").click()
    assert page.url.startswith(BACKEND + "/checkout.html")
    expect(page.locator("#shop-selected-title")).to_have_text("Семейный месяц")
    expect(page.locator("#shop-selected-days")).to_have_text("30 дней")
    expect(page.locator("#shop-selected-devices")).to_have_text("6")
    expect(page.locator("#shop-total")).to_have_text("289 ₽")
    expect(page.locator("#shop-buy")).to_be_disabled()
    page.locator("#shop-config-retry").click()
    expect(page.locator("#shop-buy")).to_be_enabled()
    if width < 500:
        page.locator("#shop-to-payment a").click()
    page.locator(f'input[value="{gateway}"]').check()
    page.locator("#shop-buy").click()
    expect(page.locator("#shop-login")).to_be_visible()
    assert not invoices
    page.locator("#shop-login").click()

    page.locator("#auth-email-input").fill(EMAIL)
    page.locator('[data-auth-form="email"] button').click()
    expect(page.locator("#auth-email-code")).to_be_visible()
    page.locator("#auth-email-input").fill("second@example.com")
    page.locator('[data-auth-form="email"] button').click()
    expect(page.locator('[data-auth-message="email"]')).to_contain_text("Последний отправленный код")
    expect(page.locator('[data-auth-message="email"]')).to_contain_text(EMAIL)
    page.locator("#auth-email-code").fill(codes[EMAIL])
    page.locator('[data-auth-verify="email"] button').click()
    page.get_by_role("link", name="Продолжить оформление").click()
    expect(page.locator("#shop-selected-title")).to_have_text("Семейный месяц")
    expect(page.locator(f'input[value="{gateway}"]')).to_be_checked()
    assert page.evaluate(
        "fetch('/api/email-auth/account').then(r => r.json()).then(data => data.authenticated)"
    ), [cookie["name"] for cookie in context.cookies(BACKEND)]
    page.locator("#shop-buy").click()
    expect(page.locator("#shop-payment-status")).to_contain_text("Не удалось открыть кассу")
    assert len(invoices) == 1
    with page.expect_response(lambda response: urlsplit(response.url).path == endpoint) as checkout:
        page.locator("#shop-buy").click()
    assert checkout.value.ok, checkout.value.text()
    page.get_by_role("link", name="Вернуться в кабинет").click()
    assert len(invoices) == 1
    order_id, payment_id, amount = invoices[0]
    assert amount == "289.00"
    expect(page.locator("#account-payment-return")).to_be_visible()
    expect(page.locator("#account-order-list")).to_contain_text("Ожидает оплаты")
    expect(page.locator("#account-order-list")).to_contain_text("289 ₽")
    expect(page.locator("#account-open-vpn")).to_be_hidden()
    assert not deliveries

    if gateway == "rollypay":
        raw = json.dumps({"event_type": "payment.paid", "status": "paid",
                          "order_id": order_id, "payment_id": payment_id,
                          "amount": amount, "currency": "RUB"}).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(SIGNING.encode(), stamp.encode() + b"." + raw,
                             hashlib.sha256).hexdigest()
        result = client.post("/api/shop/webhooks/rollypay", content=raw,
                             headers={"X-Timestamp": stamp, "X-Signature": signature})
    else:
        result = client.post("/api/shop/webhooks/platega",
                             headers={"X-MerchantId": MERCHANT, "X-Secret": PLATEGA_SECRET},
                             json={"id": payment_id, "payload": order_id,
                                   "status": "CONFIRMED", "amount": amount, "currency": "RUB"})
    assert result.status_code == 200, result.text
    assert result.json()["vpn_delivered"] is True
    page.locator("#account-refresh").click()
    expect(page.locator("#account-order-list")).to_contain_text("Оплачено · выдано")
    expect(page.locator("#account-open-vpn")).to_have_attribute("href", SUBSCRIPTION)
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    session_expired = True
    page.locator("#account-refresh").click()
    expect(page.locator("#account-session-expired")).to_be_visible()
    expect(page.locator("#account-private")).to_be_hidden()
    assert page.locator("#account-open-vpn").get_attribute("href") is None
    assert not errors, errors
    context.close()
