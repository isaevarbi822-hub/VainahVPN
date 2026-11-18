"""One-tap Happ/INCY import: correct registered deep links and safe fallback.

Uses Node's DOM and request mocks; never calls a real VPN provider.
"""
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["paid", "manual"])
def test_client_import_uses_correct_scheme_and_copies_secret_only_on_click(kind):
    js = Path(__file__).resolve().parents[2] / "storefront/account-dashboard.js"
    harness = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm'), fs=require('node:fs');
const nodes=new Map(),copied=[];
const sub='https://sub.example.net/private?token=abc%2Fxyz&device=2';
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.events={};
    this.hidden=false;this.disabled=false;this.style={};this.textContent='';}
  addEventListener(name,fn){this.events[name]=fn;}
  append(...items){this.children.push(...items);for(const x of items)if(x)x.parent=this;}
  replaceChildren(...items){this.children=[];this.append(...items);}
  removeAttribute(k){delete this[k];}
  getAttribute(k){return this[k]??null;}
  setAttribute(k,v){this[k]=v;}
  querySelector(){return new Element('button');}
  click(){return this.events.click?.();}
}
global.document={
 getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},
 createElement(name){return new Element(name);},
 createTextNode(text){return {textContent:text};}
};
global.window={};
global.navigator={clipboard:{writeText(text){copied.push(text);return Promise.resolve();}}};
const reply=body=>({ok:true,status:200,json:async()=>body});
let active=true;
const requests=[];
global.fetch=async path=>{
 requests.push(path);
 if(path==='/api/telegram/account')return reply({authenticated:false});
 if(path==='/api/email-auth/account')return reply({
   authenticated:true,user:{auth_method:'email',email:'owner@example.net'}});
 if(path==='/api/account/test-subscriptions')return reply({items:[]});
 if(path==='/api/account/overview')return reply({
   orders:[],email:{verified:true,address:'owner@example.net'},
   h1cloud:{status:'active',message:'Verified'},
   manual_grant:{available:active&&process.argv[2]==='manual'},
   subscription:!active?null:process.argv[2]==='paid'
     ?{status:'delivered',paid:true,order_id:'owned-id',expires_at:'2030-12-01T00:00:00Z',
        plan_title:'1 месяц',device_limit:3}
     :{status:'issued',paid:false,gifted:true,expires_at:'2030-12-01T00:00:00Z',
        plan_title:'Подписка от оператора',device_limit:2}
 });
 if(path==='/api/account/access') {
   assert.equal(process.argv[2],'paid');
   return reply({subscription_url:sub});
 }
 if(path==='/api/account/manual-grant') {
   assert.equal(process.argv[2],'manual');
   return reply({available:true,subscription_url:sub,devices:2,expires_at:'2030-12-01T00:00:00Z'});
 }
 throw Error('Unexpected '+path);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 for(let i=0;i<9;i++)await tick();
 const links=[
   ['account-open-happ','happ://add/'],
   ['account-open-incy','incy://import/'],
 ];
 if(process.argv[2]==='manual')links.push(
   ['account-manual-happ','happ://add/'],
   ['account-manual-incy','incy://import/']
 );
 assert.equal(copied.length,0,'no secret copied without a user click');
 for(const [id,prefix] of links){
   const node=nodes.get(id);
   assert.equal(node.hidden,false,id+' should be displayed for verified owner');
   assert.equal(node.href,prefix+sub,'URL and query tokens must stay unmodified');
   node.events.click();
   await tick();
   assert.equal(copied.at(-1),sub,'clipboard fallback is the raw HTTPS URL');
 }
 assert.equal(copied.length,links.length);
 active=false;
 await nodes.get('account-refresh').click();
 await tick();
 for(const [id] of links){
   assert.equal(nodes.get(id).href,undefined,'links removed on entitlement loss');
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    completed = subprocess.run(
        ["node", "-e", harness, str(js), kind],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_connect_page_navigates_to_verified_account_instead_of_fake_import():
    page = (Path(__file__).resolve().parents[2] / "storefront/connect.html").read_text(
        encoding="utf-8"
    )
    assert 'account.html?client=happ#account-sub-heading' in page
    assert 'account.html?client=incy#account-sub-heading' in page
    assert 'incy://add/' not in page
