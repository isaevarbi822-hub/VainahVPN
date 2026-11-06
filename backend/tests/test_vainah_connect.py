"""Vainah Connect UI is functional, device-specific and does not touch keys."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_connect_page_static_assets_and_navigation():
    with TestClient(app) as client:
        page = client.get("/connect.html")
        assert page.status_code == 200
        assert "Vainah Connect" in page.text
        for value in ("android", "ios", "windows", "macos", "linux"):
            assert f'data-vc-platform="{value}"' in page.text
        for path in ("/connect.js", "/connect.css"):
            response = client.get(path)
            assert response.status_code == 200
    shell=(SITE / "site-shell.js").read_text(encoding="utf-8")
    tools=(SITE / "tools.html").read_text(encoding="utf-8")
    assert "['connect.html','Vainah Connect'" in shell
    assert 'href="connect.html"' in tools
    assert "connect.html" in (SITE / "sitemap.xml").read_text(encoding="utf-8")


def test_connect_checklist_changes_platform_copy_fallback_and_reset():
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(dataset={}){
    this.dataset=dataset;this.events={};this.children=[];
    this.style={};this.attributes={};this.hidden=false;this.checked=false;
    this.value='';this.textContent='';
  }
  addEventListener(name,fn){this.events[name]=fn;}
  replaceChildren(...nodes){this.children=[...nodes];}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(name,value){this.attributes[name]=value;}
  focus(){this.focused=true;}
  select(){this.selected=true;}
}
const nodes=new Map(),tabs=['android','ios','windows','macos','linux']
  .map(name=>new Element({vcPlatform:name}));
const $=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
global.document={
  getElementById:$,
  createElement:()=>new Element(),
  querySelectorAll:selector=>selector==='[data-vc-platform]'?tabs:[]
};
Object.defineProperty(global,'navigator',{configurable:true,
 value:{clipboard:{writeText:async text=>{global.copied=text}}}});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
  assert.equal($('vc-steps').children.length,4);
  assert.equal($('vc-progress').attributes['aria-valuenow'],'0');
  const first=$('vc-steps').children[0].children[0];
  first.checked=true;first.events.change();
  assert.equal($('vc-progress').attributes['aria-valuenow'],'1');
  tabs[2].events.click();
  assert.equal($('vc-selected-title').textContent,'2. Подготовь подключение на Windows');
  assert.equal($('vc-progress').attributes['aria-valuenow'],'0');
  await $('vc-copy').events.click();
  assert.ok(global.copied.includes('Windows'));
  assert.ok(global.copied.includes('Vainah Connect'));
  assert.ok(!global.copied.includes('vless://'));
  navigator.clipboard.writeText=async()=>{throw Error('denied')};
  await $('vc-copy').events.click();
  assert.equal($('vc-manual').hidden,false);
  assert.equal($('vc-manual').selected,true);
  $('vc-reset').events.click();
  assert.equal($('vc-manual').hidden,true);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result=subprocess.run(
        ["node", "-e", harness, str(SITE / "connect.js")],
        text=True, capture_output=True, check=False, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_connect_excludes_unsafe_data_persistence_and_fake_vpn_stats():
    script=(SITE / "connect.js").read_text(encoding="utf-8")
    assert "fetch(" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "innerHTML" not in script
    assert "VPN" in (SITE / "connect.html").read_text(encoding="utf-8")
