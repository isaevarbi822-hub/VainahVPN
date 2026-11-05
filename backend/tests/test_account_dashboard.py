"""Exercise dashboard async privacy behavior with Node's DOM/network stubs."""
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["live", "sandbox"])
@pytest.mark.parametrize("scenario", [
    "account_switch", "same_object_reauthentication", "revoked_refresh",
    "delivered_then_revoked", "pending_logout", "out_of_order_refresh",
    "stale_session_restore",
])
def test_private_access_is_cleared_when_identity_or_entitlement_changes(kind, scenario):
    script = Path(__file__).resolve().parents[2] / "storefront/account-dashboard.js"
    harness = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const created = [];
class Element {
  constructor(tag='div') { this.tagName=tag;this.children=[];this.events={};this.hidden=false; }
  addEventListener(name, callback) { this.events[name]=callback; }
  append(...children) { this.children.push(...children);for(const c of children)if(c)c.parent=this; }
  replaceChildren(...children) { this.children=[];this.append(...children); }
  replaceWith(next) { const p=this.parent;if(p)p.children=p.children.map(c=>c===this?next:c); }
  removeAttribute(name) { delete this[name]; }
  querySelector() { return new Element('button'); }
}
global.document = {
  getElementById(id) { if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id); },
  createElement(tag) { const element=new Element(tag);created.push(element);return element; },
  createTextNode(text) { return {textContent:text}; },
};
global.window = {};
const reply = body => ({ok:true,status:200,json:async()=>body});
let resolveAccess;
let resolveLogout;
let active=true;
let delayRefresh=false;
let resolveOverview;
let resolveSandbox;
let resolveResume;
global.fetch = async path => {
  if(path==='/api/telegram/account'&&process.argv[3]==='stale_session_restore') {
    return new Promise(resolve=>{resolveResume=resolve;});
  }
  if(path==='/api/telegram/account'||path==='/api/email-auth/account')return reply({authenticated:false});
  if(path==='/api/account/overview') {
    const body={orders:[],h1cloud:{},subscription:active?{status:'delivered',paid:true,order_id:'live_order'}:null};
    if(delayRefresh)return new Promise(resolve=>{resolveOverview=()=>resolve(reply(body));});
    return reply(body);
  }
  if(path==='/api/account/test-subscriptions') {
    const body={items:active?[{
      order_id:'vainah_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',title:'30 days',
      device_limit:3,sandbox_only:true,test_payment:true,vpn_delivered:true,
    }]:[]};
    if(delayRefresh)return new Promise(resolve=>{resolveSandbox=()=>resolve(reply(body));});
    return reply(body);
  }
  if(path==='/api/email-auth/logout')return new Promise(resolve=>{resolveLogout=resolve;});
  if(path==='/api/account/access'||path.endsWith('/vpn-access')) {
    return new Promise(resolve=>{resolveAccess=resolve;});
  }
  throw Error('Unexpected request: '+path);
};
const tick = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();
  const principal={email:'owner@example.com',auth_method:'email'};
  window.onVainahEmailAuth(principal);
  await tick();
  if(process.argv[3]==='stale_session_restore') {
    resolveResume(reply({authenticated:false}));
    await tick();
    assert.equal(nodes.get('account-user').textContent,'owner@example.com');
    assert.equal(nodes.get('account-get-vpn').disabled,false);
    return;
  }
  let pending;
  if(process.argv[2]==='live') {
    pending=nodes.get('account-get-vpn').events.click();
  } else {
    const row=nodes.get('account-test-vpn-list').children[0];
    const button=row.children.find(child=>child.tagName==='button');
    assert.ok(button,'issued sandbox order must offer private access');
    pending=button.events.click();
  }
  assert.equal(typeof resolveAccess,'function');
  const scenario=process.argv[3];
  if(scenario==='delivered_then_revoked'||scenario==='pending_logout') {
    resolveAccess(reply({subscription_url:'https://sub.example/PRIVATE_OWNER_SECRET'}));
    await pending;
    assert.ok(process.argv[2]==='live'
      ?nodes.get('account-open-vpn').href.includes('PRIVATE_OWNER_SECRET')
      :nodes.get('account-test-vpn-list').children[0].children.some(c=>String(c.href).includes('PRIVATE_OWNER_SECRET')));
  }
  if(scenario==='account_switch') {
    window.onVainahEmailAuth({email:'other@example.com',auth_method:'email'});
  } else if(scenario==='same_object_reauthentication') {
    window.onVainahEmailAuth(principal);
  } else if(scenario==='pending_logout') {
    void nodes.get('account-exit').events.click();
    assert.equal(typeof resolveLogout,'function');
    assert.equal(nodes.get('account-open-vpn').href,undefined);
    assert.equal(nodes.get('account-test-vpn-list').children.length,0);
    resolveLogout(reply({ok:true}));
  } else if(scenario==='out_of_order_refresh') {
    delayRefresh=true;
    const older=nodes.get('account-refresh').events.click();
    delayRefresh=false;active=false;
    await nodes.get('account-refresh').events.click();
    resolveOverview();resolveSandbox();
    await older;
  } else {
    active=false;
    await nodes.get('account-refresh').events.click();
  }
  if(scenario!=='delivered_then_revoked'&&scenario!=='pending_logout') {
    resolveAccess(reply({subscription_url:'https://sub.example/PRIVATE_OWNER_SECRET'}));
    await pending;
  }
  await tick();
  assert.equal(nodes.get('account-open-vpn').href,undefined);
  assert.ok(!nodes.get('account-test-vpn-list').children.some(row=>
    row.children.some(child=>String(child.href||'').includes('PRIVATE_OWNER_SECRET'))));
  if(['revoked_refresh','delivered_then_revoked','out_of_order_refresh'].includes(scenario)) {
    assert.equal(nodes.get('account-get-vpn').disabled,true);
    assert.equal(nodes.get('account-copy-vpn').disabled,true);
    assert.equal(nodes.get('metric-plan').textContent,'Нет подтверждённых покупок');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script), kind, scenario],
        check=False, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
