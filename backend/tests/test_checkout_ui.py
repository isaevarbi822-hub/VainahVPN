"""Checkout privacy and receipt UI checks without external operations."""
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('scenario', ['clear_link', 'deferred_receipt', 'unsigned_paid'])
def test_checkout_keeps_only_current_access_and_confirmed_receipt(scenario):
    script = Path(__file__).resolve().parents[2] / 'storefront/checkout-flow.js'
    harness = r'''
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const nodes=new Map();
class Element {
  constructor(){this.children=[];this.dataset={};this.events={};this.value='';this.hidden=true;this.textContent='';}
  addEventListener(name,handler){this.events[name]=handler;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(name,value){this[name]=value;}
  removeAttribute(name){delete this[name];}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
global.document={getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>get('shop-plans').children};
global.location={search:'',origin:'https://test.example'};
global.history={replaceState(){}};
global.window={location:{assign(){throw Error('No actual payment navigation expected');}}};
const order='vainah_test_'+'a'.repeat(32), scenario=process.argv[2];
global.fetch=async path=>{
  let body;
  if(path==='/api/shop/plans')body={items:[{id:'30',title:'Month',days:30,devices:3,priceRub:'99'},{id:'60',title:'Two months',days:60,devices:3,priceRub:'160'}]};
  else if(path==='/api/shop/config')body={checkout_ready:false,sandbox_available:true};
  else if(path==='/api/shop/sandbox/'+order)body={order_id:order,mode:'provider',status:'paid',owner_bound:true,webhook_received:true,paid_webhook_received:scenario!=='unsigned_paid',receipt_emailed:false,amount_rub:'99.00'};
  else if(path.endsWith('/email-receipt'))body={sent:false,already_sent:false,delivery_state:'failed_before_write'};
  else throw Error('Unexpected request '+path);
  return {ok:true,json:async()=>body};
};
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await new Promise(resolve=>setImmediate(resolve));
  get('shop-test-resume').value=order;
  await get('shop-test-resume-button').events.click();
  if(scenario==='clear_link'){
    get('shop-h1-issued-link').value='https://sub.example/PRIVATE_OLD_ORDER';
    get('shop-h1-issued-link').hidden=false;
    get('shop-h1-copy-link').hidden=false;
    get('shop-plans').children[1].events.click();
    assert.equal(get('shop-h1-issued-link').value,'');
    assert.equal(get('shop-h1-issued-link').hidden,true);
    assert.equal(get('shop-h1-copy-link').hidden,true);
  }else if(scenario==='deferred_receipt'){
    await get('shop-test-email').events.click();
    assert.equal(get('shop-test-email').hidden,false);
    assert.match(get('shop-test-result').textContent,/ещё не отправлена/);
    assert.ok(!get('shop-test-result').textContent.includes('квитанция отправлена'));
  }else{
    assert.equal(get('shop-test-email').hidden,true);
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', harness, str(script), scenario], check=False, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
