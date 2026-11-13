"""Exercise device label CRUD and subscription alerts in actual browser JS."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_device_registry_browser_create_and_delete_without_real_vpn_control():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{
  constructor(){this.events={};this.children=[];this.className='';this.hidden=false;
    this.textContent='';this.value='';this.href='';this.disabled=false;}
  addEventListener(kind,cb){this.events[kind]=cb;}
  replaceChildren(...values){this.children=[...values];}
  append(...values){this.children.push(...values);}
}
const elements=new Map();
const $=id=>{if(!elements.has(id))elements.set(id,new Node());return elements.get(id)};
global.document={getElementById:$,createElement:()=>new Node()};
global.window={confirm:()=>true};
$('vd-platform').value='android';
let registered=[];
const secret='user-private-key-NOT-FOR-DEVICE-REGISTRY';
const requests=[];
global.fetch=async(url,options={})=>{
  requests.push({url,options});
  if(url==='/api/account/devices'&&options.method==='POST'){
    const body=JSON.parse(options.body);
    assert.deepEqual(body,{name:'Мой Samsung',platform:'android'});
    assert.ok(!options.body.includes(secret));
    registered.push({id:'a'.repeat(24),...body});
    return {ok:true,json:async()=>({id:'a'.repeat(24)})};
  }
  if(url==='/api/account/devices'&&options.method==='GET')
    return {ok:true,json:async()=>({items:[...registered],source:'customer_managed_labels',
      live_sessions_available:false})};
  if(url==='/api/account/devices/'+'a'.repeat(24)&&options.method==='DELETE'){
    registered=[];return {ok:true,json:async()=>({removed:true,vpn_disconnected:false})};
  }
  throw Error('Unknown request '+url+' '+options.method);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();await tick();
  assert.equal($('vd-add').disabled,false);
  assert.equal($('vd-list').children.length,1);
  $('vd-name').value='Мой Samsung';
  await $('vd-form').events.submit({preventDefault(){}});
  assert.equal($('vd-name').value,'');
  assert.equal($('vd-list').children.length,1);
  assert.equal($('vd-list').children[0].children[0].children[0].textContent,
    'Мой Samsung');
  const row=$('vd-list').children[0];
  const del=row.children[1];
  await del.events.click();
  assert.equal(registered.length,0);
  assert.equal($('vd-list').children[0].textContent,'Устройства ещё не добавлены.');
  assert.ok($('vd-status').textContent.includes('не изменено'));
  assert.equal(requests.filter(r=>r.options.method==='DELETE').length,1);
  assert.equal(requests.filter(r=>r.url.includes('/api/create')).length,0);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result=subprocess.run(["node", "-e", harness, str(SITE / "my-devices.js")],
                          text=True, capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_dashboard_alerts_use_only_paid_delivery_and_provider_data():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{
  constructor(tag='div'){this.tag=tag;this.events={};this.children=[];this.style={};
    this.textContent='';this.value='';this.className='';this.hidden=false;
    this.disabled=false;this.href='';}
  addEventListener(kind,cb){this.events[kind]=cb;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];}
  removeAttribute(name){delete this[name];}
  setAttribute(name,value){this[name]=value;}
  querySelector(){return new Node('button');}
  focus(){}
  select(){}
}
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id)};
global.document={getElementById:$,createElement:tag=>new Node(tag),
  createTextNode:text=>({textContent:text})};
global.window={addEventListener(){}};
Object.defineProperty(global,'navigator',{configurable:true,value:{clipboard:{}}});
$('account-order-filter').value='all';$('account-order-sort').value='newest';
const kind=process.argv[2];
const expiring=new Date(Date.now()+48*3600000).toISOString();
const longExpiry=new Date(Date.now()+30*86400000).toISOString();
global.fetch=async(path)=>{
  if(path==='/api/telegram/account'||path==='/api/email-auth/account')
    return {ok:true,json:async()=>({authenticated:false})};
  if(path==='/api/account/test-subscriptions')
    return {ok:true,json:async()=>({items:[]})};
  if(path==='/api/account/overview'){
    const ready=kind!=='unavailable';
    const reply={
      authenticated:true,email:{verified:true,address:'owner@example.com'},
      h1cloud:{status:ready?'active':'unavailable',message:'H1Cloud status'},
      orders:ready?[]:[{paid:true,delivered:true,status:'delivered'}],
      subscription:ready?{paid:true,status:'delivered',plan_title:'1 месяц',
        expires_at:kind==='expiring'?expiring:longExpiry,
        traffic:kind==='expiring'?{used_bytes:93,limit_bytes:100}:null,
        device_limit:3}:null
    };
    return {ok:true,json:async()=>reply};
  }
  throw Error('Unexpected fetch '+path);
};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();
  window.onVainahEmailAuth({auth_method:'email',email:'owner@example.com'});
  await tick();await tick();await tick();await tick();
  const alerts=$('account-alert-list').children;
  assert.ok(alerts.length>0,'Subscription warnings should render after verified API data');
  const titles=alerts.map(x=>x.children[0]?.textContent||'');
  if(kind==='expiring'){
    assert.ok(titles.some(s=>s.includes('трёх дней')),titles);
    assert.ok(titles.some(s=>s.includes('90%')),titles);
  }else if(kind==='unavailable'){
    assert.ok(titles.some(s=>s.includes('не подтверждено')),titles);
    assert.ok(!titles.some(s=>s.includes('Использовано')),titles);
  }else{
    assert.ok(titles.some(s=>s.includes('Срочных предупреждений')),titles);
    assert.ok(!titles.some(s=>s.includes('90%')),titles);
  }
  window.onVainahEmailAuth(null);
  assert.equal($('account-alert-list').children.length,1);
  assert.ok($('account-alert-list').children[0].textContent.includes('после входа'));
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    for kind in ("expiring", "unavailable", "normal"):
        result=subprocess.run(
            ["node", "-e", harness, str(SITE / "account-dashboard.js"), kind],
            text=True, capture_output=True, check=False, timeout=15,
        )
        assert result.returncode == 0, kind + "\n" + result.stdout + result.stderr


def test_account_advisory_page_is_private_and_navigable():
    with TestClient(app) as client:
        page=client.get("/account.html")
        assert page.status_code == 200
        assert 'id="account-alert-list"' in page.text
        assert 'href="my-devices.html"' in page.text
        device=client.get("/my-devices.html")
        assert device.status_code == 200
        assert "noindex" in device.headers["x-robots-tag"]
