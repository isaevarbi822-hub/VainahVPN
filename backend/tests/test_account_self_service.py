"""New account self-service tools use verified H1 dates and redact support details."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_calendar_support_actions_visible_with_private_guards():
    with TestClient(app) as client:
        html = client.get("/account.html").text
        for identifier in ("account-calendar", "account-support-summary",
                           "account-calendar-status", "account-support-manual"):
            assert f'id="{identifier}"' in html
        assert 'id="account-calendar" type="button" class="btn btn-border" disabled' in html
    script = (SITE / "account-dashboard.js").read_text(encoding="utf-8")
    assert "function validExpiry(value)" in script
    assert "function downloadCalendar()" in script
    assert "function safeSupportReport()" in script
    assert "currentData?.subscription?.paid!==true" in script
    assert "lastReport" not in script
    assert "URL.revokeObjectURL(url)" in script
    assert "localStorage" not in script


def test_calendar_and_redacted_support_report_functional():
    script_path = SITE / "account-dashboard.js"
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
class Node {
  constructor(tag='div'){this.tag=tag;this.textContent='';this.value='';
    this.disabled=false;this.hidden=false;this.events={};this.children=[];this.style={};}
  addEventListener(kind,callback){this.events[kind]=callback;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  removeAttribute(attr){delete this[attr];}
  setAttribute(attr,value){this[attr]=value;}
  querySelector(){return new Node('button');}
  click(){global.saved=true;}
  focus(){this.focused=true;}
  select(){this.selected=true;}
}
const $=id=>{
  if(!nodes.has(id))nodes.set(id,new Node());
  return nodes.get(id);
};
$('account-order-filter').value='all';$('account-order-sort').value='newest';
global.document={
  getElementById:$,
  createElement(tag){return new Node(tag);},
  createTextNode(text){return {textContent:text};}
};
global.window={};
Object.defineProperty(global,'navigator',{configurable:true,
  value:{clipboard:{writeText:async(text)=>{global.copied=text;}}}});
URL.createObjectURL=blob=>{global.calendarBlob=blob;return 'blob:calendar'};
URL.revokeObjectURL=()=>{};
const reply=body=>({ok:true,json:async()=>body,status:200});
global.fetch=async path=>{
  if(path==='/api/telegram/account'||path==='/api/email-auth/account')
    return reply({authenticated:false});
  if(path==='/api/account/test-subscriptions')return reply({items:[]});
  if(path==='/api/account/overview')return reply({
    email:{verified:true,address:'email@private.example'},
    h1cloud:{status:'active',message:'H1Cloud online'},
    orders:[{order_id:'HIDDEN_ORDER_ID',title:'1 год',status:'delivered',
       created_at:'2026-01-01T00:00:00Z'}],
    subscription:{paid:true,status:'delivered',order_id:'HIDDEN_ORDER_ID',
      plan_title:'1 год',device_limit:3,expires_at:'2099-01-09T12:00:00Z'}
  });
  throw Error('unexpected request '+path);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  assert.equal($('account-calendar').disabled,true);
  window.onVainahEmailAuth({auth_method:'email',email:'email@private.example'});
  await tick();await tick();
  assert.equal($('account-calendar').disabled,false);
  assert.equal($('account-support-summary').disabled,false);
  $('account-calendar').events.click();
  const ics=await global.calendarBlob.text();
  assert.ok(ics.includes('BEGIN:VCALENDAR'));
  assert.ok(ics.includes('DTSTART:20990108T120000Z'));
  assert.ok(ics.includes('\r\nEND:VCALENDAR'));
  assert.ok(!ics.includes('HIDDEN_ORDER_ID'));
  assert.ok(!ics.includes('email@private'));
  assert.ok(!ics.includes('subscription_url'));
  await $('account-support-summary').events.click();
  assert.ok(global.copied.includes('H1Cloud: active'));
  assert.ok(!global.copied.includes('email@private'));
  assert.ok(!global.copied.includes('HIDDEN_ORDER_ID'));
  assert.ok(!global.copied.includes('https://'));
  navigator.clipboard.writeText=async()=>{throw Error('blocked')};
  await $('account-support-summary').events.click();
  assert.equal($('account-support-manual').hidden,false);
  assert.equal($('account-support-manual').selected,true);
  window.onVainahEmailAuth(null);
  assert.equal($('account-calendar').disabled,true);
  assert.equal($('account-support-summary').disabled,true);
  assert.equal($('account-support-manual').hidden,true);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script_path)],
        capture_output=True, check=False, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
