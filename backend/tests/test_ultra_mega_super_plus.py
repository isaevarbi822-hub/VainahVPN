"""ULTRA MEGA SUPER PLUS visual upgrades stay safe and accessible."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_superplus_shared_layers_and_critical_routes():
    files = [
        "index.html", "hub.html", "plans.html", "account.html",
        "checkout.html", "compare.html", "assistant.html",
        "servers.html", "support-center.html", "gifts.html",
        "notifications.html", "whats-new.html",
    ]
    with TestClient(app) as client:
        for filename in files:
            response = client.get("/" + filename)
            assert response.status_code == 200, filename
            assert "Vainah" in response.text or "VAINAH" in response.text
    for filename in files[:9]:
        html = (SITE / filename).read_text(encoding="utf-8")
        assert "site-shell.js?v=20261107-superplus2" in html
    for filename in ("gifts.html", "notifications.html"):
        html = (SITE / filename).read_text(encoding="utf-8")
        assert "ultra-experience.js?v=20261107-superplus2" in html
    home = (SITE / "index.html").read_text(encoding="utf-8")
    assert '<h1 id="home-title">' in home
    assert "50 тариф + пробник" in home
    assert "6 тарифов + пробник" not in home
    for target in ("plans.html", "account.html", "notifications.html",
                   "gifts.html", "servers.html", "support-center.html"):
        assert f'href="{target}"' in home
    assert 'href="whats-new.html"' in home
    news = (SITE / "whats-new.html").read_text(encoding="utf-8")
    assert "ULTRA MEGA SUPER PLUS" in news
    assert "только в твоём браузере" in news
    assert '<main id="main"' in news


def test_superplus_isolated_appearance_settings_and_node_syntax():
    app_js = (SITE / "ultra-experience.js").read_text(encoding="utf-8")
    shell_js = (SITE / "site-shell.js").read_text(encoding="utf-8")
    css = (SITE / "ultra-experience.css").read_text(encoding="utf-8")
    assert "textSize" in app_js
    assert "settings.motion" in app_js
    assert "THEMES" in app_js
    assert "localStorage.setItem(storageKey, JSON.stringify(settings))" in app_js
    assert "/api/shop/checkout" not in app_js
    assert "/api/account/overview" not in app_js
    assert "innerHTML" not in app_js
    assert "whats-new.html" in shell_js
    assert "data-vx-theme=\"sunset\"" in css
    assert "data-vx-theme=\"midnight\"" in css
    assert "data-vx-text-size=\"large\"" in css
    assert "prefers-reduced-motion" in css
    for filename in ("ultra-experience.js", "site-shell.js"):
        result = subprocess.run(
            ["node", "--check", str(SITE / filename)], timeout=20,
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_superplus_theme_selection_and_reset_is_client_only():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
  constructor(tag='div') {
    this.tag=tag;this.children=[];this.events={};this.dataset={};
    this.attributes={};this.textContent='';this.className='';
    this.type='';this.checked=false;this.open=false;this.disabled=false;
  }
  append(...nodes){this.children.push(...nodes);}
  prepend(...nodes){this.children.unshift(...nodes);}
  after(...nodes){this.children.push(...nodes);}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(k,fn){this.events[k]=fn;}
  showModal(){this.open=true;}
  close(){this.open=false;}
}
const body=new El('body');
const docRoot=new El('html'),meta=new El('meta');
const nodes=[];
global.document={
 body,documentElement:docRoot,
 getElementById:()=>null,
 querySelector:s=>s==='meta[name="theme-color"]'?meta:null,
 createElement:t=>{const e=new El(t);nodes.push(e);return e;},
 addEventListener:()=>{}
};
global.location={pathname:'/plans.html'};
const saved={};const writes=[];
global.localStorage={
 getItem:k=>saved[k]||null,
 setItem:(k,v)=>{writes.push({k,v});saved[k]=v;}
};
global.fetch=()=>{throw Error('Never request network without user input');};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const find=fn=>nodes.find(fn);
const dialog=find(x=>x.tag==='dialog');
const settings=find(x=>x.className==='vx-ultra-settings');
assert.ok(dialog&&settings);
assert.equal(docRoot.dataset.vxTheme,'aurora');
settings.events.click();
assert.equal(dialog.open,true);
const sunset=find(x=>x.dataset.theme==='sunset');
assert.ok(sunset);
sunset.events.click();
assert.equal(docRoot.dataset.vxTheme,'sunset');
const accessibility=find(x=>x.className==='vx-ultra-accessibility');
const inputs=accessibility.children.filter(x=>x.className==='vx-ultra-compact')
  .map(x=>x.children[0]);
assert.equal(inputs.length,2);
inputs[0].checked=true;inputs[0].events.change();
inputs[1].checked=true;inputs[1].events.change();
assert.equal(docRoot.dataset.vxTextSize,'large');
assert.equal(docRoot.dataset.vxMotion,'reduce');
const reset=find(x=>x.className==='vx-ultra-reset');
reset.events.click();
assert.equal(docRoot.dataset.vxTheme,'aurora');
assert.equal(docRoot.dataset.vxTextSize,'standard');
assert.equal(docRoot.dataset.vxMotion,'system');
assert.ok(writes.length>=4);
const keys=Object.keys(JSON.parse(writes[writes.length-1].v)).sort();
assert.deepEqual(keys,['density','motion','textSize','theme']);
assert.ok(!JSON.stringify(writes).includes('payment_id'));
console.log('appearance states and reset passed');
"""
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / "ultra-experience.js")],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
