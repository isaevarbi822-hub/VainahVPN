"""Resilient customer dashboard browser behavior without real account credentials."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_email_session_preferred_and_bfcache_clears_owner_link():
    script = ROOT / "storefront/account-dashboard.js"
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodeMap=new Map(),windowEvents={},requests=[];
class Element{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.events={};
   this.hidden=false;this.disabled=false;this.style={};this.attributes={};
   this.classList={toggle:(name,on)=>{this.attributes[name]=on}};
 }
 addEventListener(name,cb){this.events[name]=cb;}
 append(...items){this.children.push(...items);for(const x of items)if(x)x.parent=this;}
 replaceChildren(...items){this.children=[];this.append(...items);}
 removeAttribute(k){delete this[k];}
 setAttribute(k,v){this.attributes[k]=v;}
 getAttribute(k){return this[k]||null;}
 querySelector(){return new Element('button');}
 click(){return this.events.click?.();}
}
global.document={
 getElementById(id){if(!nodeMap.has(id))nodeMap.set(id,new Element());return nodeMap.get(id);},
 createElement(tag){return new Element(tag);},
 createTextNode(s){return {textContent:s};}
};
global.window={
 location:{search:'?client=incy'},
 addEventListener(name,cb){(windowEvents[name]??=[]).push(cb);}
};
Object.defineProperty(globalThis,'navigator',{configurable:true,
 value:{onLine:true,clipboard:{writeText:()=>Promise.resolve()}}});
const reply=body=>({ok:true,status:200,json:async()=>body});
global.fetch=async path=>{
 requests.push(path);
 if(path==='/api/email-auth/account')return reply({authenticated:true,user:{
   email:'owner@example.com',auth_method:'email'}});
 if(path==='/api/telegram/account')return reply({authenticated:true,user:{
   telegram_id:'999999999',auth_method:'telegram',first_name:'Stale'}});
 if(path==='/api/account/test-subscriptions')return reply({items:[]});
 if(path==='/api/account/overview')return reply({
   h1cloud:{status:'active',message:'Verified H1Cloud'},
   email:{verified:true,address:'owner@example.com'},
   orders:[],subscription:{paid:true,status:'delivered',order_id:'paid123',
     plan_title:'1 месяц',device_limit:3,expires_at:'2030-12-01T00:00:00Z'}
 });
 if(path==='/api/account/access')return reply({
   subscription_url:'https://vpn.example.com/sub/OWNER_ONLY_TOKEN'});
 throw Error('Unexpected request '+path);
};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 for(let i=0;i<10;i++)await tick();
 assert.equal(requests[0],'/api/email-auth/account','verified email first');
 assert.ok(!requests.includes('/api/telegram/account'),'do not switch to stale Telegram');
 assert.equal(nodeMap.get('account-user').textContent,'owner@example.com');
 assert.match(nodeMap.get('account-dashboard-health').textContent,/проверены/i);
 assert.equal(nodeMap.get('account-dashboard-health').attributes['data-state'],'verified');
 assert.equal(nodeMap.get('account-import-intent').hidden,false);
 assert.match(nodeMap.get('account-import-intent').textContent,/INCY/);
 assert.equal(nodeMap.get('account-open-incy').attributes['account-client-preferred'],true);
 const first=nodeMap.get('account-open-vpn').href;
 assert.ok(first.includes('OWNER_ONLY_TOKEN'));
 assert.equal(windowEvents.pagehide.length,1);
 windowEvents.pagehide[0]();
 assert.equal(nodeMap.get('account-open-vpn').href,undefined);
 assert.equal(nodeMap.get('account-open-incy').href,undefined);
 windowEvents.pageshow[0]({persisted:true});
 for(let i=0;i<10;i++)await tick();
 assert.equal(nodeMap.get('account-open-vpn').href,first);
 assert.equal(nodeMap.get('account-dashboard-health').attributes['data-state'],'verified');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run = subprocess.run(
        ["node", "-e", harness, str(script)], capture_output=True, text=True,
        timeout=12, check=False,
    )
    assert run.returncode == 0, run.stderr


def test_static_login_uses_single_canonical_auth_origin():
    content = (ROOT / "storefront/account.html").read_text(encoding="utf-8")
    redirect = (ROOT / "storefront/static-auth-redirect.js").read_text(encoding="utf-8")
    assert 'src="/static-auth-redirect.js?v=20261119-stay-login1"' in content
    assert '"/account.html"' in redirect
    assert 'apiOrigin+window.location.pathname+window.location.search+window.location.hash' in redirect
    assert "window.location.hash" in redirect
    assert "account-import-intent" in content
    assert "account-dashboard-health" in content


def test_connection_wizard_detects_device_without_network_or_storage():
    script = ROOT / "storefront/connect.js"
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class E {
 constructor(){this.style={};this.events={};this.dataset={};this.children=[];this.hidden=false;}
 setAttribute(k,v){this[k]=v;}
 addEventListener(k,v){this.events[k]=v;}
 replaceChildren(...a){this.children=a;}
 append(...a){this.children.push(...a);}
}
const nodes=new Map(),tabs=['android','ios','windows','macos','linux'].map(name=>{
 const tab=new E();tab.dataset.vcPlatform=name;return tab;
});
global.document={getElementById(id){if(!nodes.has(id))nodes.set(id,new E());return nodes.get(id);},
 querySelectorAll(){return tabs;},createElement(){return new E();}};
global.window={location:{search:''}};
Object.defineProperty(globalThis,'navigator',{configurable:true,
 value:{userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
 maxTouchPoints:5}});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
assert.match(nodes.get('vc-selected-title').textContent,/iPhone \/ iPad/);
assert.equal(tabs[1].getAttribute?.('aria-selected')||tabs[1]['aria-selected'],'true');
"""
    run = subprocess.run(["node", "-e", harness, str(script)], capture_output=True,
                         text=True, timeout=12, check=False)
    assert run.returncode == 0, run.stderr
