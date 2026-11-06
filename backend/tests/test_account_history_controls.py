"""Account history interactions, privacy-safe CSV and expiry UI regression tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_account_history_controls_are_accessible_and_styles_responsive():
    with TestClient(app) as client:
        page = client.get("/account.html")
        assert page.status_code == 200
        html = page.text
    for identifier in (
        "account-order-search", "account-order-filter", "account-order-sort",
        "account-order-export", "account-history-match", "account-expiry-note",
    ):
        assert f'id="{identifier}"' in html
    js = (SITE / "account-dashboard.js").read_text(encoding="utf-8")
    css = (SITE / "account-dashboard.css").read_text(encoding="utf-8")
    assert "function historyView()" in js
    assert "function exportHistory()" in js
    assert "function updateExpiryNote(value)" in js
    assert "account-order-tools" in css
    assert "max-width:580px" in css


def test_account_filtered_order_export_and_session_isolation():
    script_path = SITE / "account-dashboard.js"
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),created=[];
class Node {
  constructor(tag='div') {
    this.tagName=tag;this.events={};this.children=[];this.hidden=false;
    this.disabled=false;this.textContent='';this.style={};this.value='';
  }
  addEventListener(type,callback){this.events[type]=callback;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];}
  removeAttribute(key){delete this[key];}
  setAttribute(key,value){this[key]=value;}
  querySelector(){return new Node('button');}
  click(){global.clicked=true;}
}
const $=id=>{
  if(!nodes.has(id))nodes.set(id,new Node());
  return nodes.get(id);
};
$('account-order-filter').value='all';
$('account-order-sort').value='newest';
global.document={
  getElementById:$,
  createElement(tag){const item=new Node(tag);created.push(item);return item;},
  createTextNode(text){return {textContent:text};}
};
global.window={};
global.URL.createObjectURL=blob=>{global.downloadBlob=blob;return 'blob:local';};
global.URL.revokeObjectURL=()=>{};
Object.defineProperty(global,'navigator',{
  configurable:true,value:{clipboard:{writeText:async()=>{}}}
});
const answer=body=>({ok:true,status:200,json:async()=>body});
global.fetch=async path=>{
  if(path==='/api/telegram/account'||path==='/api/email-auth/account')
    return answer({authenticated:false});
  if(path==='/api/account/test-subscriptions')return answer({items:[]});
  if(path==='/api/account/overview')return answer({
    h1cloud:{message:'VPN-профиль активен'},email:{verified:true,address:'private@example.com'},
    orders:[
      {title:'=HYPERLINK("https://example.com")',created_at:'2026-01-02T00:00:00Z',status:'delivered',order_id:'OWNER_PRIVATE_ID'},
      {title:'1 месяц',created_at:'2026-01-03T00:00:00Z',status:'pending',order_id:'OTHER_PRIVATE_ID'},
      {title:'1 год',created_at:'2026-01-04T00:00:00Z',status:'delivered',order_id:'THIRD_PRIVATE_ID'}
    ],
    subscription:{status:'delivered',paid:true,order_id:'OWNER_PRIVATE_ID',
      plan_title:'1 год',expires_at:'2099-06-12T00:00:00Z',device_limit:3}
  });
  throw Error('unexpected request: '+path);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  window.onVainahEmailAuth({email:'private@example.com',auth_method:'email'});
  await tick();await tick();
  assert.equal($('account-history-count').textContent,'3');
  assert.equal($('account-order-list').children.length,3);
  assert.equal($('account-order-export').disabled,false);
  assert.ok($('account-expiry-note').textContent.includes('H1Cloud'));
  $('account-order-filter').value='delivered';
  $('account-order-filter').events.change();
  assert.equal($('account-order-list').children.length,2);
  $('account-order-search').value='HYPERLINK';
  $('account-order-search').events.input();
  assert.equal($('account-order-list').children.length,1);
  assert.equal($('account-history-match').textContent,'Показано: 1 из 3');
  $('account-order-export').events.click();
  assert.equal(global.clicked,true);
  const csv=await global.downloadBlob.text();
  assert.ok(csv.startsWith('\uFEFF'));
  assert.ok(csv.includes('"\'=HYPERLINK('));
  assert.ok(!csv.includes('OWNER_PRIVATE_ID'));
  assert.ok(!csv.includes('private@example.com'));
  assert.ok(!csv.includes('Месяц'));
  assert.ok(!csv.includes('subscription_url'));
  $('account-order-search').value='ZZZ';
  $('account-order-search').events.input();
  assert.equal($('account-order-export').disabled,true);
  assert.equal($('account-order-list').children[0].children[0].textContent,
    'По запросу ничего не найдено');
  window.onVainahEmailAuth(null);
  assert.equal($('account-order-export').disabled,true);
  assert.equal($('account-order-search').value,'');
  assert.equal($('account-history-count').textContent,'0');
  assert.equal($('account-expiry-note').textContent,
    'Срок неизвестен: проверенные данные H1Cloud отсутствуют.');
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script_path)],
        capture_output=True, check=False, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
