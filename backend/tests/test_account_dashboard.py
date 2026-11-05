"""Exercise dashboard async privacy behavior with Node's DOM/network stubs."""
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["live", "sandbox"])
def test_pending_private_access_does_not_render_after_account_switch(kind):
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
global.fetch = async path => {
  if(path==='/api/telegram/account'||path==='/api/email-auth/account')return reply({authenticated:false});
  if(path==='/api/account/overview')return reply({
    orders:[],h1cloud:{},subscription:{status:'delivered',paid:true,order_id:'live_order'},
  });
  if(path==='/api/account/test-subscriptions')return reply({items:[{
    order_id:'vainah_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',title:'30 days',
    device_limit:3,sandbox_only:true,test_payment:true,vpn_delivered:true,
  }]});
  if(path==='/api/account/access'||path.endsWith('/vpn-access')) {
    return new Promise(resolve=>{resolveAccess=resolve;});
  }
  throw Error('Unexpected request: '+path);
};
const tick = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();
  window.onVainahEmailAuth({email:'owner@example.com',auth_method:'email'});
  await tick();
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
  window.onVainahEmailAuth({email:'other@example.com',auth_method:'email'});
  await tick();
  resolveAccess(reply({subscription_url:'https://sub.example/PRIVATE_OWNER_SECRET'}));
  await pending;
  await tick();
  assert.equal(nodes.get('account-open-vpn').href,undefined);
  assert.ok(!created.some(node=>String(node.href||'').includes('PRIVATE_OWNER_SECRET')));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script), kind],
        check=False, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
