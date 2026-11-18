"""Regression tests for the task-first homepage and validated, local-only catalog tools."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_home_start_actions_are_real_links():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'class="container vx5-start"' in html
    assert 'id="vx5-start-title"' in html
    for destination in ("trial.html", "plans.html", "connect.html", "ultra-repair.html"):
        assert f'class="vx5-start-card" href="{destination}"' in html
        assert (SITE / destination).is_file()
    assert 'class="vx5-start-account"' in html


def test_catalog_actions_are_complete_and_accessible():
    html = (SITE / "plans.html").read_text(encoding="utf-8")
    for action in (
        "data-tariff-favorites-only", "data-tariff-favorite-count",
        "data-tariff-share", "data-tariff-retry", "data-tariff-feedback",
    ):
        assert action in html
    assert 'data-tariff-favorites-only aria-pressed="false"' in html
    assert 'data-tariff-retry hidden' in html
    assert 'data-tariff-feedback role="status" aria-live="polite"' in html
    assert "RollyPay и Platega" in html


def test_catalog_uses_only_verified_server_amounts_for_checkout():
    js = (SITE / "tariff-catalog.js").read_text(encoding="utf-8")
    for required in (
        "new Set(plans.map(p=>p.id)).size!==76",
        "plans.every(safe)", "plan.checkout_path",
        "const publicFavoriteKey=", "storage()?.setItem",
        "favoritesOnly&&!favorites.has(plan.id)",
        "if(favorites.size<8)", "updateCompare();",
        "navigator.clipboard.writeText", "initial.get('compare')",
        "data.checkout_ready?'RollyPay':null",
        "data.platega_ready?'Platega':null",
        "retryButton?.addEventListener",
        "new AbortController()", "clearTimeout(timer);",
    ):
        assert required in js, required
    # The catalog must never create an invoice or send a customer's data.
    for forbidden in (
        "method:'POST'", 'method:"POST"', "/api/shop/checkout/platega",
        "ROLLYPAY_API_KEY", "PLATEGA_SECRET", "sessionStorage",
        "fetch('/api/shop/checkout",
    ):
        assert forbidden not in js, forbidden


def test_v5_layout_respects_mobile_and_reduced_motion():
    css = (SITE / "experience-v5.css").read_text(encoding="utf-8")
    shell = (SITE / "site-shell.js").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}")
    for query in ("max-width:1200px", "max-width:780px", "max-width:540px",
                  "prefers-reduced-motion:reduce", "prefers-reduced-data:reduce"):
        assert query in css
    assert "experience-v5.css?v=20261118-mega1" in shell
    assert "fetch(" not in shell
    for page in ("index", "plans", "checkout", "account", "devices", "help"):
        html = (SITE / f"{page}.html").read_text(encoding="utf-8")
        assert ("site-shell.js?v=20261118-mega1" in html or
                "site-shell.js?v=20261118-ultra6" in html)


def _catalog_fixture() -> str:
    js = (SITE / "tariff-catalog.js").read_text(encoding="utf-8")
    match = re.search(r"const paidIds=new Set\(\[(.*?)\]\);", js, re.DOTALL)
    assert match
    ids = re.findall(r"'([a-z0-9-]+)'", match.group(1))
    assert len(ids) == 75
    items = [
        {
            "id": plan_id, "title": "Тариф " + plan_id,
            "days": 30, "devices": 6 if "family" in plan_id else 3,
            "price_rub": "149.00", "status": "existing",
            "checkout_supported": True,
            "checkout_path": "/checkout.html?plan=" + plan_id,
            "segment": "family" if "family" in plan_id else "standard",
        }
        for plan_id in ids
    ]
    items.append({
        "id": "trial-free", "title": "Пробный день", "days": 1,
        "devices": 2, "price_rub": "0.00", "status": "trial",
        "traffic_gb": 10, "checkout_supported": False, "segment": "short",
    })
    payload = json.dumps({"total": 76, "plans": items}, ensure_ascii=False)
    document = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    </head><body>
    <div data-tariff-catalog></div><p id="tariff-catalog-status"></p>
    <input data-tariff-search>
    <select data-tariff-sort><option value="days">Срок</option><option value="price">Цена</option></select>
    <select data-tariff-devices><option value="all">Все</option><option value="3">Личные</option></select>
    <select data-tariff-budget><option value="all">Любой</option></select>
    <button data-tariff-reset>Сброс</button>
    <button data-tariff-more hidden>Ещё</button>
    <button data-tariff-favorites-only aria-pressed="false">Избранное</button>
    <span data-tariff-favorite-count>0</span>
    <button data-tariff-share>Поделиться</button>
    <button data-tariff-retry hidden>Повторить</button>
    <p data-tariff-feedback></p>
    <p id="tariff-filter-count"></p><p data-tariff-insight></p>
    <p data-checkout-readiness></p><p data-tariff-empty hidden></p>
    <section data-tariff-compare hidden>
      <div data-tariff-compare-items></div><p data-tariff-compare-message></p>
      <button data-tariff-compare-clear>Очистить</button>
    </section>
    <script>
    const fakeData=__FAKE_DATA__;
    let catalogRequests=0;
    window.fetch=async (url,options)=>{
      if(options?.method==='POST')throw Error('Unexpected POST');
      if(String(url).includes('/api/shop/config'))
        return {ok:true,json:async()=>({checkout_ready:true,platega_ready:true})};
      if(String(url).includes('/api/site/tariffs')){
        catalogRequests++;
        if(catalogRequests===1)throw Error('Simulated first network failure');
        return {ok:true,json:async()=>fakeData};
      }
      throw Error('Unexpected route: '+url);
    };
    </script><script>__CATALOG_SCRIPT__</script>
    <script>
    setTimeout(()=>{
      const retry=document.querySelector('[data-tariff-retry]');
      const wasHiddenPrice=document.querySelector('.tariff-unavailable')!==null &&
        document.querySelectorAll('.tariff-card').length===0;
      const retryVisible=retry.hidden===false;
      retry.click();
      setTimeout(()=>{
        const cards=document.querySelectorAll('.tariff-card');
        const first=cards[0];
        const favorite=first?.querySelector('.vx5-favorite-toggle');
        const compare=first?.querySelector('.tariff-compare-toggle');
        favorite?.click();
        document.querySelector('[data-tariff-favorites-only]').click();
        const filterOk=document.getElementById('tariff-filter-count').textContent.includes('Найдено 1');
        compare?.click();
        const comparison=document.querySelector('[data-tariff-compare]');
        const good=wasHiddenPrice&&retryVisible&&cards.length===75 &&
          favorite?.getAttribute('aria-pressed')==='true'&&
          document.querySelector('[data-tariff-favorite-count]').textContent==='1'&&
          filterOk&&comparison.hidden===false&&
          document.querySelector('[data-checkout-readiness]').textContent.includes('RollyPay и Platega') &&
          catalogRequests===2;
        document.body.dataset.megaTest=good?'ok':'failed';
      },220);
    },220);
    </script></body></html>
    """
    return document.replace("__FAKE_DATA__", payload).replace("__CATALOG_SCRIPT__", js)


def test_browser_catalog_retry_favorites_and_compare(tmp_path):
    binary = (
        shutil.which("chromium") or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
    )
    if binary is None:
        pytest.skip("Chromium not installed; structural and JS syntax checks still run")
    page = tmp_path / "mega-v5-browser.html"
    page.write_text(_catalog_fixture(), encoding="utf-8")
    args = [
        binary, "--headless", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage", "--no-first-run",
        "--user-data-dir=" + str(tmp_path / "chromium-profile"),
        "--window-size=1000,750", "--virtual-time-budget=1800",
        "--dump-dom", page.as_uri(),
    ]
    result = subprocess.run(args, capture_output=True, text=True,
                            timeout=38, check=False)
    assert result.returncode == 0, result.stderr[-1200:]
    assert 'data-mega-test="ok"' in result.stdout, result.stdout[-2100:]
