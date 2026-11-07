"""Tariff showcase must never accidentally activate new RollyPay/H1 plans."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.billing import CATALOG, DISCOUNT_PILOT_PLAN, get_plan, price_rub
from vainah.main import app
from vainah.tariff_catalog import ORDER, UPCOMING, public_tariff_catalog

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SITE = Path(__file__).resolve().parents[2] / "storefront"
LEGACY = {"30", "60", "90", "180", "365", "365-family"}
UPCOMING_IDS = {"7", "14", "45", "120", "30-family"}


def test_twelve_options_have_unique_ids_and_no_payment_secrets():
    data = public_tariff_catalog()
    assert data["total"] == 12
    assert data["existing_paid_count"] == 6
    assert data["upcoming_count"] == 5
    assert data["trial_count"] == 1
    plans = data["plans"]
    assert len(plans) == len({p["id"] for p in plans}) == 12
    assert tuple(p["id"] for p in plans) == ORDER
    assert set(p["id"] for p in plans) == LEGACY | UPCOMING_IDS | {"trial-free"}
    assert DISCOUNT_PILOT_PLAN["id"] not in {p["id"] for p in plans}
    assert plans[0]["status"] == "trial"
    assert plans[0]["price_rub"] == "0.00"
    assert plans[0]["devices"] == 2
    assert plans[0]["traffic_gb"] == 10
    assert all("secret" not in str(p).lower() and "vless://" not in str(p)
               for p in plans)


def test_old_tariff_prices_are_untouched_and_paid_links_allowlisted():
    data = public_tariff_catalog()
    actual = {p["id"]: p for p in CATALOG}
    assert set(actual) == LEGACY
    for plan in data["plans"]:
        if plan["id"] not in LEGACY:
            continue
        before = actual[plan["id"]]
        assert plan["price_rub"] == price_rub(before)
        assert plan["devices"] == before["devices"]
        assert plan["days"] == before["days"]
        assert plan["checkout_supported"] is True
        assert plan["checkout_path"] == "/checkout.html?plan=" + plan["id"]


def test_upcoming_prices_visible_but_not_in_live_or_gift_checkout():
    marketing = public_tariff_catalog()
    for plan in marketing["plans"]:
        if plan["id"] not in UPCOMING_IDS:
            continue
        assert plan["status"] == "upcoming"
        assert plan["checkout_supported"] is False
        assert plan["checkout_path"] is None
        assert get_plan(plan["id"]) is None
        assert 1 <= plan["devices"] <= 6
        assert plan["days"] >= 7
        assert plan["price_rub"].endswith(".00")
    from vainah.gift_cards import ALLOWED_GIFT_PLANS
    assert UPCOMING_IDS.isdisjoint(ALLOWED_GIFT_PLANS)
    assert set(p["id"] for p in UPCOMING) == UPCOMING_IDS


def test_public_api_returns_catalog_without_authentication():
    with TestClient(app, base_url=ORIGIN) as client:
        reply = client.get("/api/site/tariffs")
    assert reply.status_code == 200
    assert reply.json() == public_tariff_catalog()
    assert "Set-Cookie" not in reply.headers


def test_plans_page_has_progressive_legacy_fallback():
    html = (SITE / "plans.html").read_text(encoding="utf-8")
    js = (SITE / "tariff-catalog.js").read_text(encoding="utf-8")
    assert 'data-tariff-catalog' in html
    assert 'id="tariff-catalog-status"' in html
    assert 'href="trial.html"' in html
    assert "tariff-catalog.js" in html
    assert "public_plans" not in js
    assert "/api/site/tariffs" in js
    assert "/checkout.html?plan=" in js
    assert "innerHTML" not in js and "localStorage" not in js
    for name in ("tariff-catalog.js",):
        output = subprocess.run(
            ["node", "--check", str(SITE / name)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        assert output.returncode == 0, output.stderr


def test_preview_never_gets_a_checkout_link_in_browser():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class El {
 constructor(tag='div') {
   this.tag=tag;this.textContent='';this.children=[];this.attributes={};
   this.className='';this.disabled=false;this.href='';this.type='';
   this.classList={add:()=>{}};
 }
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(key,v){this.attributes[key]=v;}
}
const root=new El(),status=new El(),counter=new El();
global.document={
 querySelector:selector=>selector==='[data-tariff-catalog]'?root:null,
 getElementById:id=>id==='tariff-catalog-status'?status:
   id==='tariff-compare-label'?counter:null,
 createElement:t=>new El(t),
 createDocumentFragment:()=>new El('fragment')
};
const plans=[
 ['trial-free','trial',1,0,2],
 ['7','upcoming',7,39,3],['14','upcoming',14,65,3],
 ['30','existing',30,99,3],['45','upcoming',45,139,3],
 ['60','existing',60,160,3],['90','existing',90,219,3],
 ['120','upcoming',120,279,3],['180','existing',180,339,3],
 ['365','existing',365,700,3],['30-family','upcoming',30,189,6],
 ['365-family','existing',365,1000,6],
].map(([id,mode,days,rub,devices])=>({
 id,title:'Тариф '+id,status:mode,days,devices,
 price_rub:rub.toFixed(2),checkout_supported:mode==='existing',
 checkout_path:mode==='existing'?'/checkout.html?plan='+id:null
}));
global.fetch=async()=>({ok:true,json:async()=>({total:12,plans})});
function all(el){return [el,...el.children.flatMap(all)]}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await tick();await tick();
 const items=all(root).filter(x=>x.tag==='article');
 assert.equal(items.length,11);
 const links=all(root).filter(x=>x.tag==='a');
 const upcoming=items.filter(x=>all(x).some(n=>n.textContent==='В подготовке'));
 assert.equal(links.length,6);
 assert.equal(upcoming.length,5);
 assert.ok(links.every(x=>/^\/checkout\.html\?plan=(30|60|90|180|365|365-family)$/.test(x.href)));
 assert.ok(!links.some(x=>x.href.includes('30-family')));
 assert.ok(status.textContent.includes('12 вариантов'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / "tariff-catalog.js")],
        capture_output=True, text=True, check=False, timeout=15,
    )
    assert result.returncode == 0, result.stderr + result.stdout
