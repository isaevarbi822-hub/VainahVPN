"""Regression checks for the November 15 incident: misleading speed probes and stale prices.

These tests only mock browser HTTP; they do NOT claim to measure live VPN speed,
charge customers, or access production accounts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "storefront"


def _run(source: str, filename: str) -> None:
    result = subprocess.run(
        ["node", "-e", source, str(SITE / filename)],
        check=False, capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_no_stale_prices_or_checkout_buttons_when_catalog_unverified():
    html = (SITE / "plans.html").read_text(encoding="utf-8")
    js = (SITE / "tariff-catalog.js").read_text(encoding="utf-8")
    start = html.index('data-tariff-catalog')
    end = html.index('class="catalog-more"', start)
    before_api = html[start:end]
    assert 'href="checkout.html?plan=' not in before_api
    assert '<article class="plan">' not in before_api
    assert "root.replaceChildren(elem('p','Подтверждаем актуальные цены…'" in js
    assert "Непроверенные цены скрыты" in js


def test_catalog_error_cannot_leave_outdated_purchase_options():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(tag='div'){
   this.tag=tag;this.children=[];this.textContent='';this.className='';
   this.href='';this.hidden=false;this.disabled=false;this.value='';
 }
 append(...items){this.children.push(...items)}
 replaceChildren(...items){this.children=items}
 addEventListener(){}
 setAttribute(){}
 focus(){}
}
const root=new El(),status=new El(),more=new El(),count=new El(),insight=new El(),compare=new El();
const selectors={
 '[data-tariff-catalog]':root,'[data-tariff-more]':more,
 '[data-tariff-insight]':insight,'[data-tariff-compare]':compare
};
global.document={
 querySelector:key=>selectors[key]||null,
 querySelectorAll:()=>[],
 getElementById:key=>key==='tariff-catalog-status'?status:
   key==='tariff-filter-count'?count:null,
 createElement:tag=>new El(tag),createDocumentFragment:()=>new El('fragment')
};
global.fetch=async()=>{throw Error('NETWORK_UNAVAILABLE')};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await tick();await tick();
 assert.ok(status.textContent.includes('Непроверенные цены скрыты'));
 assert.equal(root.children.length,1);
 const card=root.children[0];
 const links=card.children.filter(x=>x.tag==='a');
 assert.equal(links.length,1);
 assert.equal(links[0].href,'https://vainahvpn-python-preview.onrender.com/plans.html');
 assert.ok(!JSON.stringify(root).includes('checkout.html?plan='));
 assert.equal(more.hidden,true);
 assert.equal(count.textContent,'Цены не подтверждены');
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    _run(harness, "tariff-catalog.js")


def test_speed_page_distinguishes_http_from_vpn_speed():
    html = (SITE / "speed.html").read_text(encoding="utf-8")
    js = (SITE / "speed-test.js").read_text(encoding="utf-8")
    assert "Проверка HTTP-соединения с Render" in html
    assert "speed-test.js?v=20261115-accurate2" in html
    for expected in (
        "Эффективная HTTP-загрузка", "Эффективная HTTP-отправка",
        "Это не проверка скорости интернета",
        "несколько замеров не позволяют определить",
    ):
        assert expected in html
    assert "throughput(kind, rounds" in js
    assert "perRound.length<2" in js
    assert "fastest/slowest>3" in js
    assert "2,uploads:2" in js and "3,uploads:3" in js
    assert "НЕ скорость интернета, VPN-туннеля" in js


def test_speed_probe_is_an_http_diagnostic_not_fabricated_isp_measurement():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(){
  this.events={};this.textContent='';this.disabled=false;this.style={width:''};
  this.value='';this.checked=false;this.dataset={};
 }
 addEventListener(kind,fn){this.events[kind]=fn}
}
const ids=['speed-start','speed-stop','speed-status','speed-phase','speed-phase-fill',
  'speed-ping','speed-jitter','speed-download','speed-upload','speed-copy',
  'speed-options','speed-explanation','speed-network-mode','speed-previous'];
const elements=Object.fromEntries(ids.map(id=>[id,new El()]));
global.document={
 getElementById:id=>elements[id]||null,
 querySelector:selector=>selector==='input[name="speed-mode"]:checked'?{value:'eco'}:null
};
global.window={
 location:{origin:'https://vainahvpn-python-preview.onrender.com',search:'',hash:''},
 addEventListener(){}
};
let fakeTime=0;
global.performance={now(){fakeTime+=100;return fakeTime}};
let calls={ping:0,download:0,upload:0};
global.fetch=async(path,options)=>{
 if(path.includes('/ping')){calls.ping++;return{ok:true,status:204}};
 if(path.includes('/download')){
  calls.download++;
  return {
   ok:true,status:200,
   headers:{get:key=>key==='content-type'?'application/octet-stream':null},
   arrayBuffer:async()=>new Uint8Array(512*1024).buffer
  };
 }
 if(path.includes('/upload')){
  calls.upload++;
  return {ok:true,status:200,json:async()=>({received_bytes:options.body.byteLength})};
 }
 throw Error('UNEXPECTED_API_CALL');
};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 await elements['speed-start'].events.click();
 assert.equal(calls.download,2);
 assert.equal(calls.upload,2);
 assert.notEqual(elements['speed-download'].textContent,'—');
 assert.notEqual(elements['speed-upload'].textContent,'—');
 assert.ok(elements['speed-explanation'].textContent.includes('НЕ скорость'));
 assert.ok(elements['speed-status'].textContent.includes('не тест интернета или VPN'));
 assert.equal(elements['speed-copy'].disabled,false);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    _run(harness, "speed-test.js")
