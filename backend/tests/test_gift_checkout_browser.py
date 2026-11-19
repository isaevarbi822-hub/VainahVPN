"""Guard against browser checkout links that differ from the API allowlist."""
from __future__ import annotations

import subprocess
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_gift_checkout_host_and_nonce_in_browser():
    script = SITE / "gift-cards.js"
    harness = r"""
const assert = require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
class N {
 constructor(tag='div'){this.tag=tag;this.children=[];this.events={};this.textContent='';
 this.id='';this.value='';this.hidden=false;this.disabled=false;}
 get options(){return this.children;}
 append(...x){this.children.push(...x);}
 replaceChildren(...x){this.children=x;}
 addEventListener(t,f){this.events[t]=f;}
 setAttribute(){}
}
const root=new N(), status=new N();
global.document={getElementById:id=>id==='gift-paid-content'?root:id==='gift-paid-status'?status:
 all(root).find(node=>node.id===id),
 createElement:tag=>new N(tag)};
const requested=[], redirects=[];
let pay='https://pay.rollypay.io/pay/abc123456', uuidCalls=0, receivedOk=true;
global.window={location:{assign:url=>redirects.push(url)},
 crypto:{randomUUID:()=>('123e4567-e89b-42d3-a456-'+String(++uuidCalls).padStart(12,'0'))}};
const ok=data=>({ok:true,status:200,json:async()=>data});
global.fetch=async(p,o)=>{
 if(p.endsWith('/status'))return ok({purchase_enabled:true,redemption_available:true,plans:[
  {id:'30',title:'Месяц',price_rub:'149.00'}, {id:'60',title:'Два месяца',price_rub:'249.00'}
 ]});
 if(p.endsWith('/mine'))return ok({items:[]});
 if(p.endsWith('/received'))return receivedOk?ok({items:[]}):{ok:false,status:503};
 if(p.endsWith('/checkout')){requested.push(o);return ok({pay_url:pay});}
 throw Error('Unexpected fetch: '+p);
};
function all(el){return [el,...el.children.flatMap(all)];}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await tick();await tick();
 const btn=all(root).find(x=>x.tag==='button'&&x.textContent.includes('безопасной оплате'));
 const select=all(root).find(x=>x.tag==='select');
 assert.ok(btn);
 assert.equal(btn.disabled,false);
 assert.equal(select.options[0].textContent,'Месяц · 149.00 ₽');
 select.value='30';
 await btn.events.click();assert.deepEqual(redirects,[pay]);
 await btn.events.click();
 assert.equal(requested[0].headers['Idempotency-Key'],requested[1].headers['Idempotency-Key']);
 assert.equal(uuidCalls,1);
 select.value='60';await btn.events.click();
 select.value='30';await btn.events.click();
 assert.notEqual(requested[0].headers['Idempotency-Key'],requested[2].headers['Idempotency-Key']);
 assert.equal(requested[0].headers['Idempotency-Key'],requested[3].headers['Idempotency-Key']);
 assert.equal(uuidCalls,2);
 for(const bad of [
 'https://rollypay.io/pay/abc123456',
 'https://pay.rollypay.io:4444/pay/abc123456',
 'https://pay.rollypay.io/pay/abc123456?bad=1',
 'https://pay.rollypay.io/pay/abc123456#bad'
 ]){pay=bad;await btn.events.click();assert.equal(redirects.length,4);}
 receivedOk=false;
 await all(root).find(x=>x.textContent==='Обновить статусы подарков').events.click();
 assert.match(status.textContent,/Часть статусов не загрузилась/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    r = subprocess.run(
        ["node", "-e", harness, str(script)], capture_output=True,
        text=True, check=False, timeout=15,
    )
    assert r.returncode == 0, r.stdout + r.stderr
