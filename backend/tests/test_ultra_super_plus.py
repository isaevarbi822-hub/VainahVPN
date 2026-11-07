"""ULTRA site UX: strict browser checks without real payments or panel writes."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def node(code: str, file: str) -> None:
    outcome = subprocess.run(
        ["node", "-e", code, str(SITE / file)],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert outcome.returncode == 0, outcome.stderr + outcome.stdout


def test_ultra_assets_available_and_checkout_contract_unchanged():
    with TestClient(app) as client:
        for name in ("ultra-experience.js", "ultra-experience.css"):
            asset = client.get("/" + name)
            assert asset.status_code == 200
            assert len(asset.content) > 2000
        plans = client.get("/api/shop/plans")
        assert plans.status_code == 200
        assert len(plans.json()["items"]) == 50
        assert client.get("/api/site/tariffs").json()["total"] == 51
    shell = (SITE / "site-shell.js").read_text("utf-8")
    for asset in ("ultra-experience.js", "ultra-experience.css"):
        assert asset in shell
    for page in ("notifications.html", "gifts.html", "referrals.html", "rewards.html"):
        html = (SITE / page).read_text("utf-8")
        assert "ultra-experience.css" in html
        assert "ultra-experience.js" in html
    account = (SITE / "account.html").read_text("utf-8")
    assert 'data-vx-account-actions' in account
    assert 'href="support-center.html"' in account
    checkout = (SITE / "checkout.html").read_text("utf-8")
    assert 'id="shop-plan-search"' in checkout
    assert 'id="shop-plan-kind"' in checkout
    assert 'id="shop-plan-results"' in checkout
    for asset in ("ultra-experience.js", "site-shell.js", "checkout-flow.js"):
        proc = subprocess.run(
            ["node", "--check", str(SITE / asset)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        assert proc.returncode == 0, proc.stderr


def test_ultra_theme_settings_and_conservative_diagnostics_browser():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(tag='div') {
  this.tagName=tag.toUpperCase();this.children=[];this.events={};this.dataset={};
  this.attrs={};this.style={};this.value='';this.textContent='';
  this.checked=false;this.hidden=false;this.open=false;this.disabled=false;
 }
 append(...nodes){this.children.push(...nodes);}
 prepend(...nodes){this.children.unshift(...nodes);}
 after(node){this.afterNode=node;}
 replaceChildren(...nodes){this.children=[...nodes];}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,cb){this.events[k]=cb;}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
const header=new El('header'),meta=new El('meta'),body=new El('body');
const root=new El('html');
const all=[];
global.document={
 body,documentElement:root,
 getElementById:()=>null,
 createElement:t=>{const e=new El(t);all.push(e);return e;},
 querySelector:q=>q==='body > header, body > .site-header'?header:
   q==='meta[name="theme-color"]'?meta:null,
 addEventListener:(k,cb)=>{document.events??={};document.events[k]=cb;},
};
global.location={pathname:'/plans.html'};
let stored=null;
global.localStorage={
 getItem:()=>stored,
 setItem:(_,v)=>{stored=v;},
};
let networkCalls=0;
global.fetch=async path=>{
 networkCalls++;
 assert.equal(path,'/api/site/services');
 return {ok:true,json:async()=>({services:{
   database:{status:'ok'},h1:{status:'unavailable'},
   rollypay:{status:'ok'},webhook:{status:'configured'}
 }})};
};
const deep=n=>[n,...n.children.flatMap(deep)];
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 assert.equal(root.dataset.vxTheme,'aurora');
 assert.equal(root.dataset.vxDensity,'normal');
 assert.equal(networkCalls,0); // no background access
 const ribbon=all.find(x=>x.id==='vx-ultra-ribbon');
 assert.ok(ribbon);
 const settingsButton=all.find(x=>x.attrs['aria-label']==='Настроить оформление Vainah VPN');
 settingsButton.events.click();
 const dialog=all.find(x=>x.tagName==='DIALOG');
 assert.equal(dialog.open,true);
 const ocean=all.find(x=>x.dataset.theme==='ocean');
 ocean.events.click();
 assert.equal(root.dataset.vxTheme,'ocean');
 assert.equal(JSON.parse(stored).theme,'ocean');
 assert.equal(meta.attrs.content,'#081e34');
 const compact=all.find(x=>x.tagName==='INPUT'&&x.type==='checkbox');
 compact.checked=true;compact.events.change();
 assert.equal(root.dataset.vxDensity,'compact');
 assert.equal(JSON.parse(stored).density,'compact');
 const check=all.find(x=>x.textContent==='Проверить сейчас');
 await check.events.click();
 assert.equal(networkCalls,1);
 assert.equal(check.disabled,false);
 const report=all.find(x=>x.className==='vx-ultra-health-results');
 assert.equal(report.children.length,4);
 const text=report.children.map(x=>x.textContent).join(' | ');
 assert.ok(text.includes('H1Cloud API: Нет подтверждения'));
 assert.ok(text.includes('RollyPay API: API отвечает'));
 assert.ok(text.includes('доставку платежей не проверяли'));
 assert.ok(!text.includes('VPN подключён')&&!text.includes('деньги приняты'));
 assert.ok(!stored.includes('subscription')&&!stored.includes('secret'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    node(harness, "ultra-experience.js")


def test_checkout_search_does_not_change_selected_plan_or_create_a_charge():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(tag='div'){
  this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.events={};
  this.value='';this.textContent='';this.hidden=true;this.disabled=false;this.attrs={};
 }
 addEventListener(k,fn){this.events[k]=fn;}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=[...items];}
 setAttribute(k,v){this.attrs[k]=v;}
 removeAttribute(k){delete this.attrs[k];}
}
const nodes=new Map(),get=k=>{
 if(!nodes.has(k))nodes.set(k,new El());return nodes.get(k);
};
global.document={
 getElementById:get,createElement:t=>new El(t),
 querySelectorAll:()=>get('shop-plans').children
};
global.location={search:'?plan=family-max-730d',origin:'https://test.example'};
global.history={replaceState(){}};
global.window={location:{assign(){throw Error('Unexpected payment redirect');}}};
let charges=0;
global.fetch=async path=>{
 if(path==='/api/shop/plans')return {ok:true,json:async()=>({items:[
  {id:'30',title:'1 месяц',days:30,devices:3,priceRub:'149.00'},
  {id:'family-max-730d',title:'Family Max',days:730,devices:6,priceRub:'2690.00'},
  {id:'mini-3d',title:'Mini',days:3,devices:3,priceRub:'29.00'}
 ]})};
 if(path==='/api/shop/config')return {ok:true,json:async()=>({checkout_ready:false,sandbox_available:false})};
 charges++;throw Error('Unexpected checkout API '+path);
};
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await new Promise(done=>setImmediate(done));
 const cards=get('shop-plans');
 assert.equal(cards.children.length,3);
 assert.equal(get('shop-selected-title').textContent,'Family Max');
 const search=get('shop-plan-search'),kind=get('shop-plan-kind');
 search.value='mini';search.events.input();
 assert.equal(cards.children.filter(x=>x.hidden!==true).length,1);
 assert.equal(get('shop-selected-title').textContent,'Family Max');
 kind.value='family';kind.events.change();
 assert.equal(cards.children.filter(x=>x.hidden!==true).length,0);
 assert.ok(get('shop-plan-results').textContent.includes('Ранее выбранный тариф'));
 search.value='';search.events.input();
 assert.equal(cards.children.filter(x=>x.hidden!==true).length,1);
 assert.equal(cards.children[1].dataset.plan,'family-max-730d');
 assert.equal(get('shop-buy').disabled,true);
 assert.equal(charges,0);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    node(harness, "checkout-flow.js")
