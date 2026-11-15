"""Regression coverage for the Nov 15 customer-reported false errors.

Only browser mocks and read-only local TestClient requests are used here.
No payments, auth tokens, subscriptions, or VPN keys are touched.
"""
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def _node(script_name: str, harness: str) -> None:
    p = subprocess.run(
        ["node", "-e", harness, str(SITE / script_name)],
        text=True, capture_output=True, check=False, timeout=20,
    )
    assert p.returncode == 0, p.stdout + p.stderr


def test_static_vainah_check_redirects_before_false_api_checks():
    html = (SITE / "connection-check.html").read_text(encoding="utf-8")
    shell = (SITE / "site-shell.js").read_text(encoding="utf-8")
    assert 'connection-check.js?v=20261115-routing2' in html
    assert "'/connection-check.html'" in shell
    with TestClient(app) as client:
        assert client.get("/connection-check.html").status_code == 200
        assert client.get("/connection-check.js").status_code == 200
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let target=null,fetches=0;
global.window={location:{
 origin:'https://vainahvpn.onrender.com',
 href:'https://vainahvpn.onrender.com/connection-check.html?mode=safe#details',
 replace:url=>{target=url}
}};
global.fetch=()=>{fetches++;throw Error('Should not call static API')};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
assert.equal(target,'https://vainahvpn-python-preview.onrender.com/connection-check.html?mode=safe#details');
assert.equal(fetches,0);
"""
    _node("connection-check.js", harness)


def test_public_control_checks_only_cors_allowed_catalog_not_checkout():
    script=(SITE/"command-hub.js").read_text(encoding="utf-8")
    assert "isPublicSite?'/api/site/tariffs':'/api/health'" in script
    assert "if(isPublicSite){" in script
    assert "Проверка доступна на странице оформления" in script
    assert "src=\"command-hub.js?v=20261115-reliable2\"" in (SITE/"command-hub.html").read_text(encoding="utf-8")
    harness=r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(){this.events={};this.dataset={};this.textContent='';this.disabled=false;this.value='';}
 addEventListener(n,f){this.events[n]=f}
}
const ids=['#vx-browser-status','#vx-api-status','#vx-checkout-status','#vx-hub-status-note','#vx-hub-check'];
const nodes=Object.fromEntries(ids.map(x=>[x,new El()]));
global.document={querySelector:k=>nodes[k]||null,querySelectorAll:()=>[]};
global.window={location:{origin:'https://vainahvpn.onrender.com'},addEventListener(){}};
Object.defineProperty(global,'navigator',{configurable:true,value:{onLine:true}});
let called=[];
global.fetch=async(url,opt)=>{
 called.push(url);
 assert.equal(opt.method,'GET');
 assert.equal(opt.credentials,'omit');
 if(url.endsWith('/api/site/tariffs'))
   return {ok:true,json:async()=>({total:76,plans:Array(76).fill({})})};
 throw Error('Forbidden cross-origin call: '+url);
};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 nodes['#vx-hub-check'].events.click();
 for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(called,['https://vainahvpn-python-preview.onrender.com/api/site/tariffs']);
 assert.equal(nodes['#vx-api-status'].dataset.state,'ok');
 assert.equal(nodes['#vx-checkout-status'].dataset.state,'unknown');
 assert.ok(nodes['#vx-checkout-status'].textContent.includes('странице оформления'));
 assert.equal(nodes['#vx-hub-check'].disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    _node("command-hub.js", harness)


def test_picker_rejects_irrelevant_terms_even_when_within_budget():
    assert "vanah" not in (SITE/"vainah-next.js").read_text(encoding="utf-8")[:40]
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(tag='div'){this.tag=tag;this.events={};this.attributes={};this.dataset={};this.children=[];this.href='';this.textContent='';}
 append(...nodes){this.children.push(...nodes)}
 replaceChildren(...nodes){this.children=nodes}
 setAttribute(k,v){this.attributes[k]=v}
 getAttribute(k){return this.attributes[k]||null}
 addEventListener(k,v){this.events[k]=v}
}
const status=new El(),results=new El(),guide=new El(),all=new El();
const choices=[
 ['platform','android'],['devices','3'],['days','30'],['days','7'],['days','365'],
 ['budget','all'],['budget','250']
].map(([key,value])=>{const b=new El('button');b.dataset.vxNextChoice=key;b.dataset.value=value;return b});
const root={
 querySelector:k=>({
 '[data-vx-next-status]':status,'[data-vx-next-results]':results,
 '[data-vx-next-guide]':guide,'[data-vx-next-all]':all
 })[k]||null,
 querySelectorAll:k=>k==='[data-vx-next-choice]'?choices:[]
};
global.document={querySelector:k=>k==='[data-vx-next-journey]'?root:null,createElement:k=>new El(k)};
global.window={location:{origin:'https://vainahvpn.onrender.com',href:'https://vainahvpn.onrender.com/index.html'}};
const plans=Array.from({length:75},(_,i)=>({
 id:'plan-'+i,title:'Тариф '+i,days:7,devices:3,price_rub:'100.00',
 category:'personal',status:'existing',checkout_supported:true,
 checkout_path:'/checkout.html?plan=plan-'+i
}));
plans.push({id:'trial-free',status:'trial'});
global.fetch=async()=>({ok:true,json:async()=>({total:76,plans})});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));
 const click=(k,v)=>choices.find(x=>x.dataset.vxNextChoice===k&&x.dataset.value===v).events.click();
 click('days','365');click('budget','250');
 assert.equal(results.children.length,0,'7-day offers are not a match for a year');
 assert.ok(status.textContent.includes('подходящих тарифов нет'));
 click('days','7');
 assert.equal(results.children.length,3,'near-term recommendations are shown');
 assert.ok(status.textContent.includes('3 варианта'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    _node("vainah-next.js", harness)
