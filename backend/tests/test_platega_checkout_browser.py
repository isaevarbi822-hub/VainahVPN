"""Execute the public checkout controller with a fake browser and gateway."""
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["both", "platega_only", "disabled"])
def test_gateway_selection_separate_intents_and_redirect_validation(mode):
    script = Path(__file__).resolve().parents[2] / "storefront/checkout-flow.js"
    harness = r"""
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const nodes=new Map(), stored=new Map(), redirects=[], requests=[];
class Element {
 constructor(){this.children=[];this.dataset={};this.events={};this.value='';this.textContent='';}
 addEventListener(name,fn){this.events[name]=fn;}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 setAttribute(k,v){this[k]=v;} removeAttribute(k){delete this[k];}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
global.document={getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>get('shop-plans').children};
global.location={search:'?plan=30',assign:url=>redirects.push(url)};
global.history={replaceState(){}};
global.sessionStorage={getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
const mode=process.argv[2], uuid='123e4567-e89b-42d3-a456-426614174002';
let replyGateway=null, badUrl=null;
const ok=data=>({ok:true,json:async()=>data});
global.fetch=async(path,options={})=>{
 if(path==='/api/shop/plans')return ok({items:[{id:'30',title:'Month',days:30,devices:3,priceRub:'149'}]});
 if(path==='/api/shop/config')return ok({checkout_ready:mode==='both',gateways:[
  {id:'rollypay',checkout_ready:mode==='both'}, {id:'platega',checkout_ready:mode!=='disabled'}
 ]});
 if(path.startsWith('/api/shop/checkout-intent?')){
  requests.push({path,key:options.headers['Idempotency-Key']});
  return ok({found:true,payment_state:'created',renewal_ready:false});
 }
 if(path==='/api/shop/checkout'){
  const body=JSON.parse(options.body); requests.push({body,key:options.headers['Idempotency-Key']});
  return ok({gateway:replyGateway||body.gateway,pay_url:badUrl||(body.gateway==='platega'
   ? 'https://pay.platega.io/?id='+uuid+'&mh='+uuid : 'https://pay.rollypay.io/pay/abcdef123')});
 }
 throw Error('Unexpected request '+path);
};
(async()=>{
 stored.set('vainah-live-checkout-intent-v1-30','old-rolly-key');
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await new Promise(resolve=>setImmediate(resolve));
 const buy=get('shop-buy');
 if(mode==='disabled'){
  assert.equal(buy.disabled,true); await buy.events.click();
  assert.equal(requests.length,0); return;
 }
 if(mode==='both'){
  await buy.events.click(); assert.equal(requests.at(-1).key,'old-rolly-key');
  get('shop-gateway-platega').events.change();
 }else{
  assert.equal(get('shop-gateway-platega').checked,true);
  assert.equal(get('shop-gateway-rollypay').disabled,true);
 }
 assert.match(buy.textContent,/Platega/);
 await buy.events.click();
 const first=requests.at(-1);
 assert.equal(first.body.gateway,'platega'); assert.notEqual(first.key,'old-rolly-key');
 await buy.events.click(); assert.equal(requests.at(-1).key,first.key);
 assert.ok(requests.some(r=>r.path?.includes('gateway=platega')));
 const count=redirects.length;
 replyGateway='rollypay'; await buy.events.click(); assert.equal(redirects.length,count);
 replyGateway=null;
 for(const bad of [
  'https://evil.example/?id='+uuid+'&mh='+uuid,
  'https://pay.platega.io/?id='+uuid+'&mh='+uuid+'&redirect=https://evil.example',
  'https://pay.platega.io/?id='+uuid+'&mh='+uuid+'#evil',
  'https://pay.rollypay.io/pay/abcdef123'
 ]){badUrl=bad;await buy.events.click();assert.equal(redirects.length,count);}
 assert.equal(stored.get('vainah-live-checkout-intent-v1-30'),'old-rolly-key');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script), mode], capture_output=True,
        text=True, check=False, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
