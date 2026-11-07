"""Monitor UI and reliability tests without creating payments or VPN accounts."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_connection_monitor_page_is_available_and_indexable():
    with TestClient(app) as client:
        page = client.get("/connection-monitor.html")
        js = client.get("/connection-monitor.js")
        assert page.status_code == 200
        assert js.status_code == 200
        assert 'src="connection-monitor.js"' in page.text
        assert ('<link rel="canonical" href="'
                'https://vainahvpn-python-preview.onrender.com/connection-monitor.html">'
                ) in page.text
        for element in ("monitor-start", "monitor-stop", "monitor-copy",
                        "monitor-average", "monitor-failures", "monitor-chart"):
            assert f'id="{element}"' in page.text


def test_connection_monitor_is_findable_and_bounded():
    script = (SITE / "connection-monitor.js").read_text(encoding="utf-8")
    shell = (SITE / "site-shell.js").read_text(encoding="utf-8")
    tools = (SITE / "tools.html").read_text(encoding="utf-8")
    sitemap = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    assert "SAMPLE_COUNT=7" in script
    assert "INTERVAL_MS=4000" in script
    assert "REQUEST_TIMEOUT_MS=3000" in script
    assert "/api/health?monitor=" in script
    assert "pagehide" in script and "visibilitychange" in script
    assert "connection-monitor.html" in shell
    assert 'href="connection-monitor.html"' in tools
    assert "/connection-monitor.html" in sitemap
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_connection_monitor_real_js_success_error_and_clipboard_fallback():
    script_path = SITE / "connection-monitor.js"
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
class Node {
  constructor(id=''){
    this.id=id;this.textContent='';this.disabled=false;this.hidden=false;
    this.value='';this.events={};this.style={};this.children=[];
  }
  addEventListener(type,handler){this.events[type]=handler;}
  setAttribute(key,value){this[key]=value;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  focus(){this.focused=true;}
  select(){this.selected=true;}
}
const $=id=>{
  if(!nodes.has(id))nodes.set(id,new Node(id));
  return nodes.get(id);
};
global.document={
  getElementById:$,createElement:()=>new Node(),addEventListener(){},hidden:false
};
global.window={addEventListener(){}};
Object.defineProperty(global,'navigator',{
  configurable:true,
  value:{clipboard:{writeText:async(value)=>{global.copied=value;}}}
});
let ticks=0,requestCount=0,failAt=-1;
global.performance={now:()=>{ticks+=10;return ticks;}};
global.fetch=async(url,options)=>{
  assert.ok(String(url).startsWith('/api/health?monitor='));
  assert.equal(options.credentials,'omit');
  assert.equal(options.cache,'no-store');
  requestCount++;
  if(requestCount===failAt)throw Error('network unavailable');
  return {ok:true,json:async()=>({ok:true})};
};
(async()=>{
  const code=fs.readFileSync(process.argv[1],'utf8')
    .replace('INTERVAL_MS=4000','INTERVAL_MS=0');
  vm.runInThisContext(code);
  await $('monitor-start').events.click();
  assert.equal(requestCount,7);
  assert.equal($('monitor-count').textContent,'7 / 7');
  assert.equal($('monitor-success').textContent,'7');
  assert.equal($('monitor-failures').textContent,'0');
  assert.equal($('monitor-chart').children.length,7);
  assert.equal($('monitor-stop').disabled,true);
  await $('monitor-copy').events.click();
  assert.ok(global.copied.includes('Успешно: 7'));
  assert.ok(!global.copied.includes('subscription_url'));
  requestCount=0;failAt=3;
  await $('monitor-start').events.click();
  assert.equal(requestCount,7);
  assert.equal($('monitor-success').textContent,'6');
  assert.equal($('monitor-failures').textContent,'1');
  navigator.clipboard.writeText=async()=>{throw Error('denied')};
  await $('monitor-copy').events.click();
  assert.equal($('monitor-manual').hidden,false);
  assert.equal($('monitor-manual').selected,true);
  assert.ok($('monitor-manual').value.includes('Ошибок: 1'));
  assert.equal($('monitor-start').disabled,false);
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script_path)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
