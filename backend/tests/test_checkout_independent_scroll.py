"""Checkout scroll regression: separate local scroll containers, never change payments."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_checkout_has_two_accessible_separate_scroll_areas():
    html = (SITE / "checkout.html").read_text(encoding="utf-8")
    assert 'id="shop-plans" class="shop-plans" role="region" tabindex="0"' in html
    assert 'id="shop-payment-panel" tabindex="0" role="region"' in html
    assert 'href="#shop-payment-panel"' in html
    assert html.index('id="shop-plans"') < html.index('id="shop-payment-panel"')
    assert "checkout-flow.css?v=20261119-purchase1" in html
    assert "checkout-flow.js?v=20261119-purchase1" in html
    assert 'name="shop-gateway" value="rollypay"' in html
    assert 'name="shop-gateway" value="platega"' in html


def test_checkout_scrolling_is_contained_and_responsive():
    css = (SITE / "checkout-flow.css").read_text(encoding="utf-8")
    assert ".checkout-next .checkout-columns .shop-plans{" in css
    assert ".checkout-next .checkout-columns .shop-summary{" in css
    assert css.count("overscroll-behavior-y:contain") >= 2
    assert css.count("overflow-y:auto") >= 2
    assert "-webkit-overflow-scrolling:touch" in css
    assert "scrollbar-gutter:stable" in css
    assert "@media(max-width:900px)" in css
    assert "@media(max-width:600px)" in css
    assert "max-height:min(62vh,650px)" in css
    assert "max-height:min(78vh,740px)" in css
    assert css.count("{") == css.count("}")
    assert "body{overflow:hidden" not in css


def test_filter_resets_just_tariff_scroll_without_payment_side_effects():
    js = (SITE / "checkout-flow.js").read_text(encoding="utf-8")
    start = js.index("function applyPlanFilter()")
    end = js.index("function draw()", start)
    filter_handler = js[start:end]
    assert "cards.scrollTop = 0;" in filter_handler
    assert "filterPlans();" in filter_handler
    assert 'addEventListener("input", applyPlanFilter)' in filter_handler
    assert 'addEventListener("change", applyPlanFilter)' in filter_handler
    assert "window.scrollTo" not in filter_handler
    assert "scrollIntoView" not in filter_handler
    assert "shop-payment-panel" not in filter_handler
    # Hosted payment and invoice handling remain server-owned, not in this UI.
    assert '"/api/shop/checkout/platega"' in js
    assert '"/api/shop/checkout"' in js


@pytest.mark.parametrize(("width", "height"), [(1280, 820), (460, 820)])
def test_real_chromium_scrolling_does_not_cross_between_regions(tmp_path, width, height):
    browser = (shutil.which("chromium") or shutil.which("chromium-browser")
               or shutil.which("google-chrome"))
    if browser is None:
        pytest.skip("Chromium is not installed on this runner")

    css = (SITE / "checkout-flow.css").read_text(encoding="utf-8")
    cards = "".join(
        '<button class="shop-plan" type="button"><strong>Тариф</strong>'
        '<small>3 устройства</small><span class="price">149 ₽</span></button>'
        for _ in range(75)
    )
    summary = "".join(
        '<p class="fineprint">Условия оформления и получения подписки.</p>'
        for _ in range(75)
    )
    fixture = """
<!doctype html><html lang="ru"><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
* {box-sizing:border-box}body {margin:0;background:#080b15;color:white}
.container {max-width:1200px;margin:auto;padding:16px}
</style><style>__STYLE__</style></head><body>
<main class="checkout-next">
<div class="container checkout-columns">
<section class="shop-panel"><div class="shop-heading"><h2>Тарифы</h2></div>
<div id="shop-plans" tabindex="0" class="shop-plans">__CARDS__</div>
</section>
<aside id="shop-payment-panel" tabindex="0" class="shop-panel shop-summary">
<div class="shop-heading"><h2>Оплата</h2></div>__SUMMARY__
</aside></div></main>
<script>
const plans=document.getElementById('shop-plans');
const pay=document.getElementById('shop-payment-panel');
const csPlans=getComputedStyle(plans);
const csPay=getComputedStyle(pay);
plans.scrollTop=130;
pay.scrollTop=110;
const initialPlans=plans.scrollTop;
const initialPay=pay.scrollTop;
plans.scrollTop=200;
const independentPlan=pay.scrollTop===initialPay && plans.scrollTop>initialPlans;
const newPlans=plans.scrollTop;
pay.scrollTop=185;
const independentPay=plans.scrollTop===newPlans && pay.scrollTop>initialPay;
const separate=csPlans.overflowY==='auto' && csPay.overflowY==='auto'
  && csPlans.overscrollBehaviorY==='contain'
  && csPay.overscrollBehaviorY==='contain'
  && plans.scrollHeight>plans.clientHeight
  && pay.scrollHeight>pay.clientHeight;
const mobile=innerWidth<=900;
const stacked=mobile
  ?getComputedStyle(pay).position!=='sticky'
  :getComputedStyle(pay).position==='sticky';
document.body.dataset.scrollTest=
  separate && independentPlan && independentPay && stacked?'ok':'failed';
</script></body></html>
"""
    fixture = fixture.replace("__STYLE__", css)
    fixture = fixture.replace("__CARDS__", cards)
    fixture = fixture.replace("__SUMMARY__", summary)
    page = tmp_path / "checkout_scroll_smoke.html"
    page.write_text(fixture, encoding="utf-8")
    outcome = subprocess.run(
        [browser, "--headless", "--no-sandbox", "--disable-gpu",
         "--disable-dev-shm-usage",
         "--user-data-dir=" + str(tmp_path / "chrome-profile"),
         "--window-size=" + str(width) + "," + str(height),
         "--dump-dom", page.as_uri()],
        capture_output=True, text=True, timeout=36, check=False,
    )
    assert outcome.returncode == 0, outcome.stderr[-1000:]
    assert 'data-scroll-test="ok"' in outcome.stdout, outcome.stdout[-1800:]
