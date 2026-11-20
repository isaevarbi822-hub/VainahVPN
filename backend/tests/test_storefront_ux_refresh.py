"""Smoke checks for the customer-facing storefront refresh.

These checks intentionally do not create payments, orders or VPN profiles.
"""
from __future__ import annotations

import subprocess
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
    assert "Онлайн-оформление доступно после подтверждения email" in js


def test_home_reports_each_available_gateway_without_creating_an_order():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const script=fs.readFileSync(process.argv[1],'utf8');
(async()=>{
  for(const [rolly,platega] of [[false,false],[true,false],[false,true],[true,true]]){
    const status={};
    const document={querySelector:key=>key==='[data-checkout-message]'?status:null};
    const fetch=async (path,options)=>{
      assert.equal(path,'/api/shop/config');assert.equal(options.method||'GET','GET');
      return {ok:true,json:async()=>({checkout_ready:rolly,platega_ready:platega})};
    };
    vm.runInNewContext(script,{document,fetch});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(status.textContent.includes('RollyPay'),rolly);
    assert.equal(status.textContent.includes('Platega'),platega);
    assert.equal(status.textContent.includes('недоступны'),!rolly&&!platega);
  }
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    subprocess.run(
        ["node", "-e", harness, str(STOREFRONT / "experience.js")],
        check=True, timeout=10,
    )
