"""Browser DOM smoke: verified manual subscription must render without paid order."""
import subprocess
from pathlib import Path


def test_verified_manual_subscription_populates_cards_and_deeplinks():
    js = Path(__file__).resolve().parents[2] / "storefront/account-dashboard.js"
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.events={};
    this.hidden=false;this.disabled=false;this.style={};this.textContent='';}
  addEventListener(name,cb){this.events[name]=cb;}
  append(...items){this.children.push(...items);for(const item of items)if(item)item.parent=this;}
  replaceChildren(...items){this.children=[];this.append(...items);}
  removeAttribute(key){delete this[key];}
  setAttribute(key,val){this[key]=val;}
  querySelector(){return new Element('button');}
  click(){return this.events.click?.();}
}
global.document={
  getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},
  createElement(tag){return new Element(tag);},
  createTextNode(text){return {textContent:text};},
};
global.window={};
const reply=value=>({ok:true,status:200,headers:{get(){return 'application/json';}},
  json:async()=>value});
let active=true;
const requests=[];
global.fetch=async (path)=>{
  requests.push(path);
  if(path==='/api/telegram/account')return reply({authenticated:false});
  if(path==='/api/email-auth/account')return reply({
    authenticated:true,user:{auth_method:'email',email:'owner@example.com'}});
  if(path==='/api/account/test-subscriptions')return reply({items:[]});
  if(path==='/api/account/overview')return reply({
    orders:[],email:{verified:true,address:'owner@example.com'},
    subscription:active?{
      status:'issued',paid:false,gifted:true,source:'manual_grant',
      plan_title:'Подписка от оператора',device_limit:2,
      expires_at:'2026-12-18T00:00:00Z',
      traffic:{used_bytes:100,limit_bytes:1000},
    }:null,
    manual_grant:active?{available:true,days:30,devices:2,
      expires_at:'2026-12-18T00:00:00Z'}:{available:false},
    h1cloud:{status:active?'active':'not_found',message:'Проверка H1'},
  });
  if(path==='/api/account/manual-grant')return reply({
    available:active,subscription_url:active?'https://example.net/owner-secret':undefined});
  if(path==='/api/account/access')throw Error('Manual gift used paid-only access route');
  throw Error('unexpected '+path);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  for(let i=0;i<6;i++)await tick();
  assert.equal(nodes.get('metric-plan').textContent,'Подписка от оператора');
  assert.equal(nodes.get('metric-devices').textContent,'2');
  assert.match(nodes.get('account-plan-chip').textContent,/без оплаты/);
  assert.equal(nodes.get('account-traffic-used').textContent,'100 Б');
  assert.equal(nodes.get('account-open-vpn').href,'https://example.net/owner-secret');
  assert.match(nodes.get('account-open-happ').href,/happ:\/\/add\//);
  assert.ok(requests.includes('/api/account/manual-grant'));
  assert.ok(!requests.includes('/api/account/access'));
  active=false;
  await nodes.get('account-refresh').click();
  await tick();
  assert.equal(nodes.get('account-open-vpn').href,undefined);
  assert.equal(nodes.get('account-open-happ').href,undefined);
  assert.equal(nodes.get('account-get-vpn').disabled,true);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(js)], capture_output=True,
        text=True, timeout=12, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_static_account_uses_canonical_python_origin():
    account = (Path(__file__).resolve().parents[2] / "storefront/account.html").read_text(
        encoding="utf-8"
    )
    redirect = (Path(__file__).resolve().parents[2] / "storefront/static-auth-redirect.js").read_text(
        encoding="utf-8"
    )
    assert 'src="/static-auth-redirect.js?v=20261119-stay-login1"' in account
    assert '"/account.html"' in redirect
    assert "https://vainahvpn-python-preview.onrender.com" in redirect
