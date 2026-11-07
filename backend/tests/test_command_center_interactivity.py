"""Exercise the recovered command center with a real Node JS runtime."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "storefront/command-center.mjs"


def run(harness: str) -> None:
    process = subprocess.run(
        ["node", "-e", harness, str(SCRIPT)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    assert process.returncode == 0, process.stdout + process.stderr


def test_diagnostics_buttons_render_guidance_and_check_read_only_api():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
  constructor(){this.textContent='';this.children=[];this.events={};this.attrs={};
    this.dataset={};this.disabled=false;this.href='';}
  addEventListener(k,fn){this.events[k]=fn;}
  setAttribute(k,v){this.attrs[k]=v;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  focus(){}select(){}
}
const map=new Map(),get=k=>{if(!map.has(k))map.set(k,new Node());return map.get(k)};
const buttons=['connection','import','slow','account','payment','panel'].map(key=>{
  const n=new Node();n.dataset.diagProblem=key;return n;
});
const root={querySelector:get,querySelectorAll:s=>s==='[data-diag-problem]'?buttons:[]};
global.document={querySelector:s=>s==='[data-diagnostics-center]'?root:null,
  createElement:()=>new Node()};
global.window={addEventListener(){}};
Object.defineProperty(global,'navigator',{configurable:true,
  value:{clipboard:{writeText:async text=>{global.report=text;}}}});
global.fetch=async path=>{
  if(path==='/api/health')return {ok:true,json:async()=>({ok:true})};
  if(path==='/api/site/services')return {ok:true,json:async()=>({
    services:{database:{status:'ok'},h1:{status:'ok'},rollypay:{status:'ok'},
      webhook:{status:'configured'}}
  })};
  throw Error('Unexpected path '+path);
};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
assert.equal(get('[data-diag-title]').textContent,'VPN не подключается');
buttons[4].events.click();
assert.equal(get('[data-diag-title]').textContent,'Оплата или заказ');
assert.equal(get('[data-diag-list]').children.length,3);
assert.equal(get('[data-diag-link]').href,'account.html');
(async()=>{
  await get('[data-diag-check]').events.click();
  assert.equal(get('[data-diag-check-results]').children.length,5);
  assert.equal(get('[data-diag-copy]').disabled,false);
  await get('[data-diag-copy]').events.click();
  assert.ok(global.report.includes('RollyPay API: API отвечает'));
  assert.ok(!global.report.includes('subscription_url'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run(harness)


def test_hub_verified_data_and_missing_expiry_are_safe():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
  constructor(){this.textContent='';this.children=[];this.events={};this.dataset={};
    this.disabled=false;}
  addEventListener(k,fn){this.events[k]=fn;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
}
const values=new Map(),get=k=>{
  if(!values.has(k))values.set(k,new Node());return values.get(k);
};
const checks=Object.fromEntries(['database','h1','rollypay','webhook'].map(
  k=>[k,{querySelector:s=>get(k+s)}]));
const root={querySelector:s=>{
  const match=s.match(/^\[data-hub-check="([^"]+)"\]$/);
  return match?checks[match[1]]:get(s);
},querySelectorAll:s=>s==='[data-hub-check]'?Object.values(checks):[]};
global.document={querySelector:s=>s==='[data-control-hub]'?root:null,
  createElement:()=>new Node()};
global.window={addEventListener(){}};
global.fetch=async path=>{
  if(path==='/api/account/overview')return {ok:true,json:async()=>({
    authenticated:true,orders:[{order_id:'SECRET_ORDER'}],
    subscription:{paid:true,status:'delivered',plan_title:'1 месяц',
      device_limit:3,expires_at:null,
      subscription_url:'https://private.example/TOKEN'}
  })};
  if(path==='/api/site/services')return {ok:true,json:async()=>({
    services:{database:{status:'ok'},h1:{status:'ok'},rollypay:{status:'ok'},
      webhook:{status:'configured'}}
  })};
  if(path==='/api/shop/plans')return {ok:true,json:async()=>({
    items:[{title:'1 месяц',days:30,devices:3,kopeks:9900}]
  })};
  throw Error('Unexpected path '+path);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();await tick();
  assert.equal(get('[data-hub-plan]').textContent,'1 месяц');
  assert.equal(get('[data-hub-devices]').textContent,'3');
  assert.equal(get('[data-hub-orders]').textContent,'1');
  assert.equal(get('[data-hub-expires]').textContent,'Не указана');
  assert.equal(get('[data-hub-plans]').children.length,1);
  const visible=[...values.values()].map(n=>n.textContent).join(' ');
  assert.ok(!visible.includes('SECRET_ORDER'));
  assert.ok(!visible.includes('TOKEN'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run(harness)
