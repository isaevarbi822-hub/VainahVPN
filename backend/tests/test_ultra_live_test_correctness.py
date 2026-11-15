"""Reproduce live Ultra speed / diagnostic false-positive bugs in actual JS.

These tests make no real network calls, do not place orders and do not touch accounts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def run_js(source: str, harness: str) -> None:
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / source)],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_speed_test_and_diagnostics_route_to_python_origin():
    shell = (SITE / "site-shell.js").read_text(encoding="utf-8")
    html = (SITE / "speed.html").read_text(encoding="utf-8")
    diagnostics = (SITE / "diagnostics.html").read_text(encoding="utf-8")
    assert "'/status.html','/speed.html','/diagnostics.html'" in shell
    assert "window.location.replace(toBackend(currentUrl))" in shell
    assert "site-shell.js?v=20261115-fixspeed1" in html
    assert "site-shell.js?v=20261115-fixspeed1" in diagnostics
    assert "speed-test.js?v=20261115-fixspeed1" in html
    assert "<small>Отклик HTTP</small>" in html
    assert "<small>Разброс задержки</small>" in html
    with TestClient(app) as client:
        for page in ("/speed.html", "/diagnostics.html"):
            result = client.get(page)
            assert result.status_code == 200
            assert "text/html" in result.headers["content-type"]
        ping = client.get("/api/speedtest/ping")
        assert ping.status_code == 204
        download = client.get("/api/speedtest/download")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("application/octet-stream")
        assert len(download.content) == 512 * 1024


def test_static_speed_page_redirects_without_fake_measurement():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const items=new Map();
class Node {
 constructor() {this.textContent='—';this.disabled=false;this.style={width:''};this.events={}}
 addEventListener(kind,fn){this.events[kind]=fn}
}
const get=id=>{if(!items.has(id))items.set(id,new Node());return items.get(id)};
let redirect='',calls=0;
global.document={getElementById:get,querySelector:()=>({value:'eco'})};
global.window={
 location:{origin:'https://vainahvpn.onrender.com',search:'?mode=eco',hash:'#run',
   assign:url=>{redirect=url}},
 addEventListener(){}
};
global.fetch=async()=>{calls++;throw Error('No API call allowed on static CDN')};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 await get('speed-start').events.click();
 assert.equal(calls,0);
 assert.equal(redirect,'https://vainahvpn-python-preview.onrender.com/speed.html?mode=eco#run');
 assert.ok(get('speed-status').textContent.includes('переносится'));
 assert.equal(get('speed-download').textContent,'—');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run_js("speed-test.js", harness)


def test_invalid_http_probe_never_reports_partial_success():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
class Node {
 constructor() {this.textContent='—';this.disabled=false;this.style={width:''};this.events={}}
 addEventListener(kind,fn){this.events[kind]=fn}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id)};
global.document={getElementById:get,querySelector:()=>({value:'eco'})};
global.window={location:{origin:'https://vainahvpn-python-preview.onrender.com'},addEventListener(){}};
global.fetch=async()=>({ok:true,status:200,headers:{get:()=> 'text/html'}});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 await get('speed-start').events.click();
 for(const id of ['speed-ping','speed-jitter','speed-download','speed-upload'])
   assert.equal(get(id).textContent,'—',id);
 assert.equal(get('speed-copy').disabled,true);
 assert.ok(get('speed-status').textContent.includes('ожидаемый ответ'));
 assert.equal(get('speed-phase').textContent,'Тест не завершён');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run_js("speed-test.js", harness)


def test_incomplete_download_clears_already_measured_ping():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
class Node {
 constructor() {this.textContent='—';this.disabled=false;this.style={width:''};this.events={}}
 addEventListener(kind,fn){this.events[kind]=fn}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id)};
global.document={getElementById:get,querySelector:()=>({value:'eco'})};
global.window={location:{origin:'https://vainahvpn-python-preview.onrender.com'},addEventListener(){}};
global.fetch=async url=>String(url).includes('/ping')
  ?{ok:true,status:204}
  :{ok:true,status:200,headers:{get:()=> 'text/html'},arrayBuffer:async()=>new ArrayBuffer(512*1024)};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 await get('speed-start').events.click();
 for(const id of ['speed-ping','speed-jitter','speed-download','speed-upload'])
   assert.equal(get(id).textContent,'—',id);
 assert.equal(get('speed-copy').disabled,true);
 assert.ok(get('speed-status').textContent.includes('не тестовые данные'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run_js("speed-test.js", harness)


def test_diagnostics_badge_is_not_green_when_api_unknown():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
 constructor() {this.textContent='';this.children=[];this.events={};this.attrs={};
   this.dataset={};this.disabled=false;this.href=''}
 addEventListener(name,fn){this.events[name]=fn}
 setAttribute(name,val){this.attrs[name]=val}
 append(...items){this.children.push(...items)}
 replaceChildren(...items){this.children=[...items]}
 focus(){}select(){}
}
const nodes=new Map(),get=k=>{if(!nodes.has(k))nodes.set(k,new Node());return nodes.get(k)};
const root={querySelector:get,querySelectorAll:()=>[]};
global.document={querySelector:k=>k==='[data-diagnostics-center]'?root:null,
 createElement:()=>new Node()};
global.window={addEventListener(){}};
global.fetch=async path=>{
 if(path==='/api/health')throw Error('No confirmation');
 if(path==='/api/site/services')return {ok:true,json:async()=>({
  services:{database:{status:'ok'},h1:{status:'ok'},rollypay:{status:'ok'},
    webhook:{status:'configured'}}
 })};
 throw Error('Unexpected GET: '+path);
};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 await get('[data-diag-check]').events.click();
 const badge=get('[data-diag-check-badge]');
 assert.equal(badge.dataset.level,'neutral');
 assert.ok(badge.textContent.includes('без подтверждения'));
 assert.equal(get('[data-diag-copy]').disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run_js("command-center.mjs", harness)


def test_invoice_creation_status_is_not_a_claim_that_payment_succeeded():
    script = (SITE / "network-check.js").read_text(encoding="utf-8")
    assert "Создание счёта разрешено" in script
    assert "Это не проверка успешной оплаты" in script
    assert "Оплата доступна" not in script
