"""Protect production caching and browser diagnostics against regressions."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "storefront"


def test_public_asset_revalidation_and_private_routes_never_cached():
    with TestClient(app) as client:
        for asset in ("/site-shell.js", "/site-shell.css", "/network-check.js"):
            result = client.get(asset)
            assert result.status_code == 200, asset
            assert result.headers["cache-control"] == (
                "public, max-age=0, must-revalidate"
            )
        for private in ("/account.html", "/account-dashboard.js",
                        "/api/health"):
            result = client.get(private)
            assert result.status_code == 200, private
            assert "no-store" in result.headers["cache-control"]


def test_offline_notice_is_passive_and_never_leaks_credentials():
    script = (SITE / "site-shell.js").read_text(encoding="utf-8")
    css = (SITE / "site-shell.css").read_text(encoding="utf-8")
    assert "vainah-offline-notice" in script
    assert "navigator.onLine===false" in script
    assert "addEventListener('offline'" in script
    assert "addEventListener('online'" in script
    assert "vx-offline-notice[hidden]" in css


def test_diagnostic_report_has_copy_fallback_and_does_not_leak_secrets():
    script = (SITE / "network-check.js").read_text(encoding="utf-8")
    html = (SITE / "network-check.html").read_text(encoding="utf-8")
    assert 'id="network-copy"' in html
    assert 'id="network-report"' in html
    assert "navigator.clipboard.writeText(lastReport)" in script
    assert "reportBox.select()" in script
    assert "Не завершено" in script
    assert "localStorage" not in script


def test_network_diagnostic_report_actual_copy_and_fallback():
    js_file = SITE / "network-check.js"
    harness = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes=new Map();
class Element {
  constructor(id=''){
    this.id=id; this.textContent='';this.dataset={};this.disabled=false;
    this.hidden=true;this.value='';this.events={};
    this.badge={textContent:'Не проверено',dataset:{}};
    this.detail={textContent:''};
  }
  addEventListener(name,fn){this.events[name]=fn;}
  querySelector(query){
    if(query==='[data-result]')return this.badge;
    if(query==='[data-detail]')return this.detail;
    return null;
  }
  focus(){this.focused=true;}
  select(){this.selected=true;}
}
const $=id=>{
  if(!nodes.has(id))nodes.set(id,new Element(id));
  return nodes.get(id);
};
global.document={getElementById:$};
global.window={
  location:{protocol:'https:'},addEventListener(){}
};
Object.defineProperty(global,'navigator',{
  configurable:true,
  value:{onLine:true,clipboard:{writeText:async(value)=>{global.copied=value;}}}
});
global.performance={now:()=>100};
global.fetch=async(url)=>{
  if(String(url).startsWith('/api/health'))
    return {ok:true,json:async()=>({ok:true})};
  if(url==='/api/email-auth/config')
    return {ok:true,json:async()=>({available:true})};
  if(url==='/api/shop/config')
    return {ok:true,json:async()=>({checkout_ready:true})};
  throw Error('unexpected URL '+url);
};
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  assert.equal($('network-copy').disabled,true);
  await $('network-run').events.click();
  assert.equal($('network-copy').disabled,false);
  await $('network-copy').events.click();
  assert.ok(global.copied.includes('Ответ сервера Vainah VPN: Доступен'));
  assert.ok(global.copied.includes('Состояние оформления заказов: Оплата доступна'));
  assert.ok(global.copied.includes('\n'));
  assert.ok(!global.copied.includes('subscription_url'));
  navigator.clipboard.writeText=async()=>{throw Error('denied')};
  await $('network-copy').events.click();
  assert.equal($('network-report').hidden,false);
  assert.equal($('network-report').value,global.copied);
  assert.equal($('network-report').selected,true);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(js_file)],
        check=False, timeout=15, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
