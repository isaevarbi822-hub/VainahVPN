"""Browser regressions for all paid tariffs in comparison and advisor."""
from __future__ import annotations

import subprocess
from pathlib import Path

from vainah.billing import CATALOG, get_plan
from vainah.tariff_catalog import (
    ADDED_PLAN_IDS,
    NEW_PLAN_IDS,
    UPCOMING_IDS,
    public_tariff_catalog,
)

SITE = Path(__file__).resolve().parents[2] / "storefront"
NEW_IDS = {"7", "14", "45", "120", "30-family"}
ADDED_IDS = {"mini-3d", "sprint-5d", "start-plus-21d", "balance-75d", "comfort-150d", "max-270d", "legend-730d", "family-plus-90d", "family-pro-180d", "family-max-730d"}


def _node(source: str, filename: str) -> None:
    result = subprocess.run(
        ["node", "-e", source, str(SITE / filename)],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_comparison_browser_renders_all_paid_checkout_links():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
  constructor(tag='div',dataset={}) {
    this.tagName=tag.toUpperCase();this.dataset=dataset;this.children=[];
    this.hidden=false;this.value='all';this.textContent='';this.href='';
    this.events={};this.disabled=false;this.className='';
  }
  append(...nodes) {for(const n of nodes) {
    this.children=this.children.filter(c=>c!==n);
    this.children.push(n);
  }}
  replaceChildren(...nodes){this.children=nodes;}
  addEventListener(name,fn){this.events[name]=fn;}
  setAttribute(){}
  querySelector(){return null;}
  querySelectorAll(selector){
    if(selector==='[data-plan-days][data-plan-kopeks][data-plan-devices]')
      return this.children.filter(n=>n.dataset.planDays);
    return [];
  }
}
const grid=new El('div'),table=new El('tbody'),count=new El('strong'),
  empty=new El('p'),loading=new El('p');
for(const [days,rub,devices] of [[30,9900,3],[60,16000,3],[90,21900,3],
  [180,33900,3],[365,70000,3],[365,100000,6]]){
  grid.append(new El('article',{
    planDays:String(days),planKopeks:String(rub),planDevices:String(devices)
  }));
}
const device=new El('select'),duration=new El('select'),order=new El('select');
device.value='all';duration.value='all';order.value='days';
const map={
  '[data-devices-filter]':device,'[data-duration-filter]':duration,
  '[data-sort-filter]':order,'[data-compare-count]':count,
  '[data-compare-empty]':empty,'[data-compare-grid]':grid,
  '.ux-table tbody':table,'[data-compare-loading]':loading
};
const compare=new El('main');
compare.querySelector=s=>map[s]||null;
global.document={
  querySelector:s=>s==='[data-compare]'?compare:null,
  createElement:t=>new El(t),
};
const paid=new Set(['7','14','30','45','60','90','120','180','365','30-family','365-family','mini-3d','sprint-5d','start-plus-21d','balance-75d','comfort-150d','max-270d','legend-730d','family-plus-90d','family-pro-180d','family-max-730d','pulse-2d','flash-4d','weekend-9d','jump-10d','express-12d','boost-17d','start-25d','flex-35d','focus-40d','smart-50d','steady-55d','stream-65d','prime-100d','flow-135d','power-210d','advance-240d','ultra-300d','horizon-540d','family-week-7d','family-14d','family-21d','family-45d','family-60d','family-75d','family-120d','family-150d','family-240d','family-270d','family-540d']);
const data=[
  ['trial-free','trial',1,0,2],
  ['mini-3d','existing',3,29,3],['sprint-5d','existing',5,45,3],
 ['start-plus-21d','existing',21,119,3],['balance-75d','existing',75,289,3],
 ['comfort-150d','existing',150,469,3],['max-270d','existing',270,749,3],
 ['legend-730d','existing',730,1790,3],
 ['family-plus-90d','existing',90,599,6],
 ['family-pro-180d','existing',180,979,6],
 ['family-max-730d','existing',730,2690,6],
 ['7','existing',7,59,3],
  ['14','existing',14,99,3],['30','existing',30,149,3],
  ['45','existing',45,209,3],['60','existing',60,239,3],
  ['90','existing',90,329,3],['120','existing',120,419,3],
  ['180','existing',180,509,3],['365','existing',365,1050,3],
  ['30-family','existing',30,289,6],
  ['365-family','existing',365,1499,6],
  ['pulse-2d','existing',2,25,3],
  ['flash-4d','existing',4,39,3],
  ['weekend-9d','existing',9,69,3],
  ['jump-10d','existing',10,79,3],
  ['express-12d','existing',12,89,3],
  ['boost-17d','existing',17,105,3],
  ['start-25d','existing',25,129,3],
  ['flex-35d','existing',35,179,3],
  ['focus-40d','existing',40,189,3],
  ['smart-50d','existing',50,229,3],
  ['steady-55d','existing',55,234,3],
  ['stream-65d','existing',65,269,3],
  ['prime-100d','existing',100,365,3],
  ['flow-135d','existing',135,445,3],
  ['power-210d','existing',210,609,3],
  ['advance-240d','existing',240,679,3],
  ['ultra-300d','existing',300,859,3],
  ['horizon-540d','existing',540,1390,3],
  ['family-week-7d','existing',7,99,6],
  ['family-14d','existing',14,169,6],
  ['family-21d','existing',21,229,6],
  ['family-45d','existing',45,369,6],
  ['family-60d','existing',60,449,6],
  ['family-75d','existing',75,509,6],
  ['family-120d','existing',120,729,6],
  ['family-150d','existing',150,829,6],
  ['family-240d','existing',240,1129,6],
  ['family-270d','existing',270,1259,6],
  ['family-540d','existing',540,2150,6]
].map(([id,status,days,rub,devices])=>({
  id,title:'Тариф '+id,status,days,devices,price_rub:rub.toFixed(2),
  traffic_gb:status==='trial'?10:undefined,
  checkout_supported:paid.has(id),
  checkout_path:paid.has(id)?'/checkout.html?plan='+id:null
}));
global.fetch=async()=>({ok:true,json:async()=>({total:51,plans:data})});
const tick=()=>new Promise(r=>setImmediate(r));
function deep(node){return [node,...node.children.flatMap(deep)]}
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();await tick();
  assert.equal(grid.children.length,51);
  assert.equal(table.children.length,51);
  assert.equal(count.textContent,'51 из 51 вариантов');
  const links=deep(grid).filter(x=>x.tagName==='A');
  assert.equal(links.length,51); // 21 paid, 1 trial
  const paidLinks=links.filter(x=>x.href.startsWith('/checkout'));
  assert.equal(paidLinks.length,50);
  assert.ok(paidLinks.every(x=>x.href.startsWith('/checkout.html?plan=')));
  assert.ok(paidLinks.some(x=>x.href.endsWith('legend-730d')));
  assert.ok(paidLinks.some(x=>x.href.endsWith('family-max-730d')));
  assert.ok(links.some(x=>x.href.includes('30-family')));
  const disabled=deep(grid).filter(x=>x.tagName==='BUTTON'&&x.disabled);
  assert.equal(disabled.length,0);
  device.value='6';device.events.change();
  assert.equal(count.textContent,'16 из 51 вариантов');
  duration.value='short';duration.events.change();
  assert.equal(count.textContent,'8 из 51 вариантов');
  device.value='2';device.events.change();
  assert.equal(count.textContent,'1 из 51 вариантов'); // free trial only
  assert.ok(loading.textContent.includes('51 предложение'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    _node(harness, "experience.js")


def test_advisor_defaults_to_verified_paid_plan_and_opt_in_future_only():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(v=''){this.value=v;this.textContent='';this.checked=false;
   this.hidden=false;this.href='';this.events={};}
 addEventListener(e,fn){this.events[e]=fn;}
}
const days=new El('7'),devices=new El('3'),pending=new El();
const output=new El(),name=new El(),price=new El(),info=new El(),
  explanation=new El(),payment=new El(),link=new El(),label=new El();
const fields={
 '[data-wanted-days]':days,'[data-wanted-devices]':devices,
 '[data-show-upcoming]':pending,'[data-advisor-output]':output,
 '[data-advisor-name]':name,'[data-advisor-price]':price,
 '[data-advisor-explanation]':explanation,'[data-advisor-payment]':payment,
 '[data-advisor-info]':info,'[data-advisor-link]':link,
 '[data-wanted-days-label]':label
};
const advisor={
 querySelector:s=>fields[s]||null,
 querySelectorAll:()=>[]
};
global.document={querySelector:s=>s==='[data-tariff-advisor]'?advisor:null};
const paid=new Set(['7','14','30','45','60','90','120','180','365','30-family','365-family','mini-3d','sprint-5d','start-plus-21d','balance-75d','comfort-150d','max-270d','legend-730d','family-plus-90d','family-pro-180d','family-max-730d','pulse-2d','flash-4d','weekend-9d','jump-10d','express-12d','boost-17d','start-25d','flex-35d','focus-40d','smart-50d','steady-55d','stream-65d','prime-100d','flow-135d','power-210d','advance-240d','ultra-300d','horizon-540d','family-week-7d','family-14d','family-21d','family-45d','family-60d','family-75d','family-120d','family-150d','family-240d','family-270d','family-540d']);
const plans=[
 ['trial-free','trial',1,0,2],
  ['mini-3d','existing',3,29,3],['sprint-5d','existing',5,45,3],
 ['start-plus-21d','existing',21,119,3],['balance-75d','existing',75,289,3],
 ['comfort-150d','existing',150,469,3],['max-270d','existing',270,749,3],
 ['legend-730d','existing',730,1790,3],
 ['family-plus-90d','existing',90,599,6],
 ['family-pro-180d','existing',180,979,6],
 ['family-max-730d','existing',730,2690,6],
 ['7','existing',7,59,3],
 ['14','existing',14,99,3],['30','existing',30,149,3],
 ['45','existing',45,209,3],['60','existing',60,239,3],
 ['90','existing',90,329,3],['120','existing',120,419,3],
 ['180','existing',180,509,3],['365','existing',365,1050,3],
 ['30-family','existing',30,289,6],
 ['365-family','existing',365,1499,6],
  ['pulse-2d','existing',2,25,3],
  ['flash-4d','existing',4,39,3],
  ['weekend-9d','existing',9,69,3],
  ['jump-10d','existing',10,79,3],
  ['express-12d','existing',12,89,3],
  ['boost-17d','existing',17,105,3],
  ['start-25d','existing',25,129,3],
  ['flex-35d','existing',35,179,3],
  ['focus-40d','existing',40,189,3],
  ['smart-50d','existing',50,229,3],
  ['steady-55d','existing',55,234,3],
  ['stream-65d','existing',65,269,3],
  ['prime-100d','existing',100,365,3],
  ['flow-135d','existing',135,445,3],
  ['power-210d','existing',210,609,3],
  ['advance-240d','existing',240,679,3],
  ['ultra-300d','existing',300,859,3],
  ['horizon-540d','existing',540,1390,3],
  ['family-week-7d','existing',7,99,6],
  ['family-14d','existing',14,169,6],
  ['family-21d','existing',21,229,6],
  ['family-45d','existing',45,369,6],
  ['family-60d','existing',60,449,6],
  ['family-75d','existing',75,509,6],
  ['family-120d','existing',120,729,6],
  ['family-150d','existing',150,829,6],
  ['family-240d','existing',240,1129,6],
  ['family-270d','existing',270,1259,6],
  ['family-540d','existing',540,2150,6]
].map(([id,status,days,rub,devices])=>({
 id,title:'Тариф '+id,status,days,devices,
 price_rub:rub.toFixed(2),checkout_supported:paid.has(id),
 checkout_path:paid.has(id)?'/checkout.html?plan='+id:null
}));
global.fetch=async()=>({ok:true,json:async()=>({total:51,plans})});
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await tick();await tick();
 assert.equal(name.textContent,'Тариф 7');
 assert.equal(link.href,'checkout.html?plan=7');
 assert.ok(payment.textContent.includes('действующих'));
 pending.checked=true;pending.events.change();
 assert.ok(name.textContent.includes('Тариф 7'));
 assert.equal(link.href,'checkout.html?plan=7');
 assert.ok(payment.textContent.includes('действующих'));
 devices.value='6';devices.events.change();
 days.value='30';days.events.input();
 assert.ok(name.textContent.includes('30-family'));
 assert.equal(link.href,'checkout.html?plan=30-family');
 pending.checked=false;pending.events.change();
 assert.equal(name.textContent,'Тариф 30-family');
 assert.equal(link.href,'checkout.html?plan=30-family');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    _node(harness, "toolkit-ui.mjs")


def test_five_new_plans_are_in_live_checkout_contract():
    plans = {p["id"]: p for p in CATALOG}
    assert NEW_PLAN_IDS == NEW_IDS
    assert NEW_IDS.issubset(plans)
    for plan_id in NEW_IDS:
        assert get_plan(plan_id) == plans[plan_id]
    all_plans = public_tariff_catalog()["plans"]
    assert len(all_plans) == 51
    assert sum(p["checkout_supported"] for p in all_plans) == 50
    assert UPCOMING_IDS == frozenset()
    assert ADDED_PLAN_IDS == ADDED_IDS
    assert sum(p["status"] == "existing" for p in all_plans) == 50
    assert sum(p["status"] == "upcoming" for p in all_plans) == 0
    assert all(p["checkout_supported"] for p in all_plans
               if p["id"] in ADDED_IDS)


def test_cross_page_links_and_copy_match_twelve_plan_catalog():
    compare = (SITE / "compare.html").read_text(encoding="utf-8")
    assistant = (SITE / "assistant.html").read_text(encoding="utf-8")
    toolkit = (SITE / "toolkit-ui.mjs").read_text(encoding="utf-8")
    experience = (SITE / "experience.js").read_text(encoding="utf-8")
    assert 'data-compare-loading' in compare
    assert 'value="2">До 2 устройств' in compare
    assert 'value="medium"' in compare
    assert 'data-show-upcoming' not in assistant
    assert 'min="3"' in assistant
    assert "/api/site/tariffs" in experience
    assert "/api/site/tariffs" in toolkit
    assert "checkout_supported===false" in toolkit
    assert "checkout_path===null" in toolkit
    for asset in ("experience.js", "toolkit-ui.mjs"):
        check = subprocess.run(
            ["node", "--check", str(SITE / asset)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        assert check.returncode == 0, check.stderr
