"""MEGA UPDATE: live catalog, safe shopping controls and quick account routes."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app
from vainah.tariff_catalog import public_tariff_catalog

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_mega_routes_and_catalog_stay_server_authoritative():
    with TestClient(app) as client:
        data = client.get("/api/site/tariffs").json()
        rows = client.get("/api/shop/plans").json()["items"]
    assert data["total"] == 76
    assert len(rows) == data["existing_paid_count"] == 75
    assert data["upcoming_count"] == 0
    for plan in data["plans"]:
        if plan["status"] == "trial":
            assert plan["checkout_supported"] is False
            continue
        assert plan["checkout_supported"] is True
        assert plan["checkout_path"] == "/checkout.html?plan=" + plan["id"]
        assert plan["price_rub"] == next(
            p["priceRub"] for p in rows if p["id"] == plan["id"]
        )


def test_mega_site_has_complete_tools_and_no_fake_purchases():
    plan = (SITE / "plans.html").read_text(encoding="utf-8")
    hub = (SITE / "hub.html").read_text(encoding="utf-8")
    index = (SITE / "site-shell.js").read_text(encoding="utf-8")
    js = (SITE / "tariff-catalog.js").read_text(encoding="utf-8")
    for token in (
        "data-tariff-search", "data-tariff-sort", "data-tariff-devices",
        "data-tariff-compare", "data-tariff-compare-clear",
        "data-tariff-reset", "data-tariff-insight", "data-tariff-empty",
    ):
        assert token in plan
    for target in (
        "notifications.html", "gifts.html", "support-center.html",
        "plans.html", "account.html",
    ):
        assert f'href="{target}"' in hub
        assert f"['{target}'" in index or target in ("plans.html", "account.html")
    assert "Срок от 2 до 730 дней" in hub
    assert "Шесть вариантов с фильтрами" not in hub
    assert "/api/site/tariffs" in js
    assert "document.createElement" in js
    assert "localStorage" not in js and "sessionStorage" not in js
    assert "innerHTML" not in js
    assert "/api/shop/checkout" not in js
    for path in ("tariff-catalog.js", "command-center.mjs", "site-shell.js"):
        result = subprocess.run(
            ["node", "--check", str(SITE / path)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_live_tariff_search_sort_and_compare_in_browser():
    catalog = public_tariff_catalog()
    assert len(catalog["plans"]) == 76
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class N {
 constructor(tag='div') {
   this.tagName=tag.toUpperCase();this.children=[];this.events={};
   this.dataset={};this.attributes={};this.className='';this.textContent='';
   this.value='';this.hidden=false;this.disabled=false;this.href='';
   this.type='';this.focus=()=>{};
 }
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){
   this.children=nodes.flatMap(n=>n.tagName==='#FRAGMENT'?n.children:[n]);
 }
 addEventListener(name,cb){this.events[name]=cb;}
 setAttribute(name,value){this.attributes[name]=value;}
}
const nodes={},idNodes={};
const create=k=>nodes[k]=new N();
const root=create('[data-tariff-catalog]');
const search=create('[data-tariff-search]');
const sort=create('[data-tariff-sort]');
const device=create('[data-tariff-devices]');
const reset=create('[data-tariff-reset]');
const more=create('[data-tariff-more]');
const budget=create('[data-tariff-budget]');
const compare=create('[data-tariff-compare]');
const compareItems=create('[data-tariff-compare-items]');
const compareClear=create('[data-tariff-compare-clear]');
const compareMessage=create('[data-tariff-compare-message]');
const insight=create('[data-tariff-insight]');
const empty=create('[data-tariff-empty]');
const status=idNodes['tariff-catalog-status']=new N();
const count=idNodes['tariff-filter-count']=new N();
const counter=idNodes['tariff-compare-label']=new N();
const buttons=['all','short','standard','long','family'].map(id=>{
 const b=new N('button');b.dataset.tariffFilter=id;return b;
});
sort.value='days';device.value='all';budget.value='all';
global.document={
 querySelector:key=>nodes[key]||null,
 querySelectorAll:key=>key==='[data-tariff-filter]'?buttons:[],
 getElementById:id=>idNodes[id]||null,
 createElement:tag=>new N(tag),
 createDocumentFragment:()=>new N('#fragment')
};
const data=__DATA__;
global.fetch=async(path)=>{
 assert.equal(path,'/api/site/tariffs');
 return {ok:true,json:async()=>data};
};
const tick=()=>new Promise(done=>setImmediate(done));
const visible=()=>root.children.filter(c=>!c.hidden);
const compareButton=card=>card.children.find(c=>c.className.includes('tariff-compare-toggle'));
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await tick();await tick();
 assert.equal(visible().length,12);
 assert.equal(root.children.length,75);
 assert.equal(more.hidden,false);
 more.events.click();
 assert.equal(visible().length,24);
 assert.ok(status.textContent.includes('75 платных'));
 // Price sorting never changes the source catalog or checkout URLs.
 sort.value='price';sort.events.change();
 assert.equal(visible()[0].children[2].textContent,'Vainah Pulse');
 search.value='730';search.events.input();
 assert.equal(visible().length,2);
 assert.ok(insight.textContent.includes('за день'));
 reset.events.click();
 assert.equal(visible().length,12);
 assert.equal(search.value,'');
 const first=visible()[0],second=visible()[1];
 compareButton(first).events.click();
 compareButton(second).events.click();
 assert.equal(compare.hidden,false);
 assert.equal(compareItems.children.length,2);
 assert.equal(compareItems.children[0].children[3].href.startsWith('/checkout.html?plan='),true);
 compareClear.events.click();
 assert.equal(compare.hidden,true);
 buttons.find(x=>x.dataset.tariffFilter==='family').events.click();
 assert.equal(visible().length,12);
 device.value='3';device.events.change();
 assert.equal(visible().length,0);
 assert.equal(empty.hidden,false);
 reset.events.click();
 assert.equal(visible().length,12);
 assert.equal(empty.hidden,true);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    harness = harness.replace("__DATA__", json.dumps(catalog, ensure_ascii=False))
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / "tariff-catalog.js")],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
