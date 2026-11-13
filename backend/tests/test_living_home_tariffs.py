"""Homepage shows only verified real tariff prices and safe checkout URLs."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from vainah.tariff_catalog import public_tariff_catalog

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_home_featured_prices_are_live_server_rows_and_refreshable():
    data = public_tariff_catalog()
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class N {
 constructor(tag='div'){
  this.tagName=tag.toUpperCase();this.children=[];this.events={};
  this.textContent='';this.className='';this.href='';this.disabled=false;
  this.attributes={};
 }
 append(...children){this.children.push(...children);}
 replaceChildren(...children){
  this.children=children.flatMap(c=>c.tagName==='#FRAGMENT'?c.children:[c]);
 }
 addEventListener(name,cb){this.events[name]=cb;}
 setAttribute(name,value){this.attributes[name]=value;}
}
const root=new N(),message=new N(),refresh=new N('button');
const lookup={
 '[data-live-plan-picks]':root,
 '[data-live-plan-message]':message,
 '[data-live-plan-refresh]':refresh
};
global.document={
 querySelector:key=>lookup[key]||null,
 createElement:tag=>new N(tag),
 createDocumentFragment:()=>new N('#fragment')
};
const data=__DATA__;
let fetches=0, tamper=false;
global.fetch=async(url,opts)=>{
 assert.equal(url,'/api/site/tariffs');
 assert.equal(opts.method,'GET');
 assert.equal(opts.credentials,'omit');
 fetches++;
 if(!tamper)return {ok:true,json:async()=>data};
 const invalid=JSON.parse(JSON.stringify(data));
 const p=invalid.plans.find(x=>x.id==='mini-3d');
 p.checkout_path='https://evil.example/pay';
 return {ok:true,json:async()=>invalid};
};
const tick=()=>new Promise(done=>setImmediate(done));
const deep=node=>[node,...node.children.flatMap(deep)];
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await tick();await tick();
 assert.equal(fetches,1);
 assert.equal(root.children.length,6);
 const links=deep(root).filter(n=>n.tagName==='A');
 assert.equal(links.length,6);
 assert.ok(links.every(n=>n.href.startsWith('/checkout.html?plan=')));
 assert.ok(links.some(n=>n.href.endsWith('pulse-2d')));
 assert.ok(message.textContent.includes('Цены получены'));
 assert.equal(refresh.disabled,false);
 tamper=true;refresh.events.click();
 await tick();await tick();
 assert.equal(fetches,2);
 assert.equal(root.children.length,1);
 const fallbackLinks=deep(root).filter(n=>n.tagName==='A');
 assert.equal(fallbackLinks.length,1);
 assert.equal(fallbackLinks[0].href,'plans.html');
 assert.ok(!deep(root).some(n=>n.className==='vx-pick-price'));
 assert.ok(message.textContent.includes('недоступна'));
 assert.equal(refresh.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    harness = harness.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / "live-plan-picks.js")],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_home_live_widget_safe_by_construction():
    js = (SITE / "live-plan-picks.js").read_text(encoding="utf-8")
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "data-live-plan-picks" in html
    assert "data-live-plan-refresh" in html
    assert "live-plan-picks.js" in html
    assert "/api/site/tariffs" in js
    assert "/api/shop/checkout" not in js
    assert "innerHTML" not in js
    assert "localStorage" not in js
    result = subprocess.run(
        ["node", "--check", str(SITE / "live-plan-picks.js")],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
