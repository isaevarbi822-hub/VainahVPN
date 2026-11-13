"""Front-end account UX regression checks. No external providers are contacted."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = (ROOT / "storefront/account.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "storefront/account-dashboard.js").read_text(encoding="utf-8")
STYLES = (ROOT / "storefront/account-dashboard.css").read_text(encoding="utf-8")


def test_email_is_default_and_account_has_customer_shortcuts():
    assert 'data-auth-tab="email"' in PAGE
    assert 'aria-selected="true" data-auth-tab="email"' in PAGE
    assert 'data-auth-pane="email"' in PAGE
    assert 'id="account-pane-email" class="account-auth-method" role="tabpanel" data-auth-pane="email">' in PAGE
    assert 'class="account-quick-nav"' in PAGE
    for target in (
        '#account-sub-heading', '#account-device-heading',
        '#account-history-heading', 'trial.html', 'contact.html',
    ):
        assert f'href="{target}"' in PAGE
    assert 'Реальная оплата пока закрыта' not in PAGE


def test_orders_are_rendered_without_html_injection_or_fabricated_amounts():
    assert 'function renderOrders(orders)' in SCRIPT
    assert "title.textContent=safeString(order.title)" in SCRIPT
    assert 'amount.textContent=\'—\'' in SCRIPT
    assert "row.append(title,date,amount,state)" in SCRIPT
    assert "formatDate(delivery.expires_at)" in SCRIPT
    assert "vx-no-fake-traffic" not in SCRIPT
    assert 'account-quick-nav' in STYLES


def test_private_access_not_written_to_order_markup():
    assert "api('/api/account/access')" in SCRIPT
    assert "const url=new URL(response.subscription_url)" in SCRIPT
    assert "url.protocol!=='https:'" in SCRIPT
    assert "subscriptionUrl=url.href" in SCRIPT
