"""Vainah Ultra 360: behavioral tests of the privacy-preserving repair wizard.

No real VPN, logins, payments or network access are performed by these tests.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def read(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def test_ultra_repair_is_public_and_accessible():
    page = read("ultra-repair.html")
    assert 'data-ultra-repair' in page
    assert '<h1 id="ultra-repair-title">' in page
    assert page.count('data-ultra-platform="') == 5
    assert page.count('data-ultra-problem="') == 6
    assert 'data-ultra-progress' in page
    assert 'data-ultra-copy' in page
    assert 'data-ultra-manual' in page
    assert 'data-ultra-copy-status role="status" aria-live="polite"' in page
    assert 'ultra-repair.js?v=20261115-u360' in page
    assert 'ultra-360.css?v=20261115-u360' in page
    with TestClient(app) as client:
        response = client.get("/ultra-repair.html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_ultra_repair_is_local_only_and_keeps_secrets_out():
    source = read("ultra-repair.js")
    for forbidden in (
        "fetch(", "XMLHttpRequest", "localStorage", "sessionStorage",
        "/api/shop/checkout", "ROLLYPAY_API_KEY", "password",
        "WebSocket", "sendBeacon",
    ):
        assert forbidden not in source
    for problem in ("connect", "import", "slow", "account", "payment", "switch"):
        assert f"    {problem}:{{" in source
    for platform in ("android", "ios", "windows", "macos", "linux"):
        assert f"{platform}:" in source
    assert "navigator.clipboard.writeText(text)" in source
    assert "Не передавай" in source or "Не сообщай" in source


def test_ultra_repair_browser_flow_and_clipboard():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(tag='div') {
  this.tag=tag;this.children=[];this.events={};this.dataset={};this.attributes={};
  this.textContent='';this.value='';this.checked=false;this.hidden=false;
  this.href='';this.max=4;this.type='';this.focus=()=>{};this.select=()=>{};
 }
 append(...nodes){this.children.push(...nodes)}
 replaceChildren(...nodes){this.children=nodes}
 setAttribute(k,v){this.attributes[k]=v}
 addEventListener(k,cb){this.events[k]=cb}
}
const keys=[
 '[data-ultra-title]','[data-ultra-summary]','[data-ultra-steps]',
 '[data-ultra-count]','[data-ultra-progress]','[data-ultra-copy-status]',
 '[data-ultra-help]','[data-ultra-manual]','[data-ultra-manual-input]',
 '[data-ultra-reset]','[data-ultra-copy]'
];
const parts=Object.fromEntries(keys.map(k=>[k,new El()]));
const platforms=['android','ios','windows','macos','linux'].map(code=>{
 const b=new El('button');b.dataset.ultraPlatform=code;return b;
});
const problems=['connect','import','slow','account','payment','switch'].map(code=>{
 const b=new El('button');b.dataset.ultraProblem=code;return b;
});
const root={
 querySelector:key=>parts[key]||null,
 querySelectorAll:key=>key==='[data-ultra-platform]'?platforms:
   key==='[data-ultra-problem]'?problems:[]
};
global.document={
 querySelector:key=>key==='[data-ultra-repair]'?root:null,
 createElement:tag=>new El(tag)
};
let copied='';
Object.defineProperty(global,'navigator',{configurable:true,value:{clipboard:{writeText:async x=>{copied=x}}}});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const steps=parts['[data-ultra-steps]'];
const count=parts['[data-ultra-count]'];
const progress=parts['[data-ultra-progress]'];
assert.equal(steps.children.length,4);
assert.equal(count.textContent,'0 / 4');
assert.equal(parts['[data-ultra-help]'].href,'connect.html?device=android');
platforms[2].events.click();
assert.ok(parts['[data-ultra-summary]'].textContent.includes('Windows'));
problems[4].events.click();
assert.equal(parts['[data-ultra-title]'].textContent,'Оплата или выдача заказа');
assert.ok(steps.children[0].children[0].children[1].children[1].textContent.includes('историю заказов'));
assert.equal(parts['[data-ultra-help]'].href,'https://vainahvpn-python-preview.onrender.com/account.html');
const checkbox=steps.children[0].children[0].children[0];
checkbox.checked=true;checkbox.events.change();
assert.equal(count.textContent,'1 / 4');
assert.equal(progress.value,1);
(async()=>{
 await parts['[data-ultra-copy]'].events.click();
 assert.ok(copied.includes('Устройство: Windows'));
 assert.ok(copied.includes('Оплата или выдача заказа'));
 assert.ok(copied.includes('Выполненные шаги из 4: 1'));
 assert.ok(!copied.includes('VPN-ссылку:'));
 parts['[data-ultra-reset]'].events.click();
 assert.equal(count.textContent,'0 / 4');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / "ultra-repair.js")],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_ultra_mobile_nav_respects_checkout_and_accessibility():
    shell = read("site-shell.js")
    mobile = read("ultra-mobile.css")
    assert "'ultra-repair.html','Vainah Repair Ultra'" in shell
    assert "vx-ultra-mobile-rail" in shell
    assert "'checkout.html','checkout-return.html','payment-return.html'" in shell
    assert "'account.html','account-login.html'" in shell
    assert "document.body.append(rail)" in shell
    assert "fetch(" not in shell
    assert "localStorage" not in shell
    assert "sessionStorage" not in shell
    assert "max-width:700px" in mobile
    assert "env(safe-area-inset-bottom)" in mobile
    assert "prefers-reduced-motion:reduce" in mobile


def test_ultra_home_navigation_and_four_step_real_budget_picker():
    home = read("index.html")
    picker = read("vainah-next.js")
    catalog = read("tariff-catalog.js")
    for link in ("ultra-repair.html", "device-center.html", "command-hub.html"):
        assert link in home
    assert 'id="ultra-center"' in home
    assert 'data-vx-next-choice="budget"' in home
    assert home.count('data-vx-next-choice="budget"') == 4
    assert "chooser.budget='all'" in picker or "budget:'all'" in picker
    assert "Number(p.price_rub)<=ceiling" in picker
    assert "target.searchParams.set('budget',chooser.budget)" in picker
    assert "['100','250','500','1000','2000'].includes(initial.get('budget'))" in catalog
    assert "method:'POST'" not in picker


def test_related_pages_and_search_index_include_ultra_repair():
    for filename in ("index.html", "command-hub.html", "diagnostics.html", "whats-new.html"):
        assert 'ultra-repair.html' in read(filename)
    sitemap = read("sitemap.xml")
    assert "https://vainahvpn.onrender.com/ultra-repair.html" in sitemap
    css = read("ultra-360.css")
    assert "@media(max-width:650px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert css.count("{") == css.count("}")
