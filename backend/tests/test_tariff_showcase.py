"""Tariff showcase must never accidentally activate new RollyPay/H1 plans."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.billing import CATALOG, DISCOUNT_PILOT_PLAN, get_plan, price_rub
from vainah.main import app
from vainah.tariff_catalog import NEW_PLAN_IDS, ORDER, UPCOMING_IDS, public_tariff_catalog

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SITE = Path(__file__).resolve().parents[2] / "storefront"
LEGACY = {"30", "60", "90", "180", "365", "365-family"}
NEW_IDS = {"7", "14", "45", "120", "30-family"}
PREVIEW_IDS = {"mini-3d", "sprint-5d", "start-plus-21d", "balance-75d", "comfort-150d", "max-270d", "legend-730d", "family-plus-90d", "family-pro-180d", "family-max-730d"}


def test_twenty_two_options_have_unique_ids_and_no_payment_secrets():
    data = public_tariff_catalog()
    assert data["total"] == 22
    assert data["existing_paid_count"] == 11
    assert data["upcoming_count"] == 10
    assert data["newly_launched_count"] == 5
    assert data["trial_count"] == 1
    plans = data["plans"]
    assert len(plans) == len({p["id"] for p in plans}) == 22
    assert tuple(p["id"] for p in plans) == ORDER
    assert {p["id"] for p in plans} == LEGACY | NEW_IDS | PREVIEW_IDS | {"trial-free"}
    assert DISCOUNT_PILOT_PLAN["id"] not in {p["id"] for p in plans}
    assert plans[0]["status"] == "trial"
    assert plans[0]["price_rub"] == "0.00"
    assert plans[0]["devices"] == 2
    assert plans[0]["traffic_gb"] == 10
    assert all("secret" not in str(p).lower() and "vless://" not in str(p)
               for p in plans)


def test_existing_tariffs_repriced_and_paid_links_allowlisted():
    data = public_tariff_catalog()
    actual = {p["id"]: p for p in CATALOG}
    assert set(actual) == LEGACY | NEW_IDS
    expected_prices = {
        "7": "59.00", "14": "99.00", "30": "149.00",
        "45": "209.00", "60": "239.00", "90": "329.00",
        "120": "419.00", "180": "509.00", "365": "1050.00",
        "30-family": "289.00", "365-family": "1499.00",
    }
    assert {pid: price_rub(plan) for pid, plan in actual.items()} == expected_prices
    for plan in data["plans"]:
        if plan["id"] not in LEGACY:
            continue
        before = actual[plan["id"]]
        assert plan["price_rub"] == price_rub(before)
        assert plan["devices"] == before["devices"]
        assert plan["days"] == before["days"]
        assert plan["checkout_supported"] is True
        assert plan["checkout_path"] == "/checkout.html?plan=" + plan["id"]


def test_new_prices_allowed_in_paid_checkout_not_added_to_gift_cards():
    marketing = public_tariff_catalog()
    for plan in marketing["plans"]:
        if plan["id"] not in NEW_IDS:
            continue
        assert plan["status"] == "existing"
        assert plan["checkout_supported"] is True
        assert plan["checkout_path"] == "/checkout.html?plan=" + plan["id"]
        assert get_plan(plan["id"]) is not None
        assert 1 <= plan["devices"] <= 6
        assert plan["days"] >= 7
        assert plan["price_rub"].endswith(".00")
    from vainah.gift_cards import ALLOWED_GIFT_PLANS
    assert NEW_IDS.isdisjoint(ALLOWED_GIFT_PLANS)
    assert NEW_PLAN_IDS == NEW_IDS
    assert UPCOMING_IDS == PREVIEW_IDS


def test_pending_tariffs_have_exact_prices_and_no_payment_path():
    data = public_tariff_catalog()
    future = {p["id"]: p for p in data["plans"] if p["status"] == "upcoming"}
    assert set(future) == PREVIEW_IDS
    expected = {
        "mini-3d": ("29.00", 3, 3),
        "sprint-5d": ("45.00", 5, 3),
        "start-plus-21d": ("119.00", 21, 3),
        "balance-75d": ("289.00", 75, 3),
        "comfort-150d": ("469.00", 150, 3),
        "max-270d": ("749.00", 270, 3),
        "legend-730d": ("1790.00", 730, 3),
        "family-plus-90d": ("599.00", 90, 6),
        "family-pro-180d": ("979.00", 180, 6),
        "family-max-730d": ("2690.00", 730, 6),
    }
    for plan_id, (price, days, devices) in expected.items():
        plan = future[plan_id]
        assert (plan["price_rub"], plan["days"], plan["devices"]) == (
            price, days, devices
        )
        assert plan["checkout_supported"] is False
        assert plan["checkout_path"] is None
        assert get_plan(plan_id) is None


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


def test_new_paid_tariffs_have_browser_checkout_links():
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
  ['mini-3d','upcoming',3,29,3],['sprint-5d','upcoming',5,45,3],
 ['start-plus-21d','upcoming',21,119,3],['balance-75d','upcoming',75,289,3],
 ['comfort-150d','upcoming',150,469,3],['max-270d','upcoming',270,749,3],
 ['legend-730d','upcoming',730,1790,3],
 ['family-plus-90d','upcoming',90,599,6],
 ['family-pro-180d','upcoming',180,979,6],
 ['family-max-730d','upcoming',730,2690,6],
 ['7','existing',7,39,3],['14','existing',14,65,3],
 ['30','existing',30,99,3],['45','existing',45,139,3],
 ['60','existing',60,160,3],['90','existing',90,219,3],
 ['120','existing',120,279,3],['180','existing',180,339,3],
 ['365','existing',365,700,3],['30-family','existing',30,189,6],
 ['365-family','existing',365,1000,6],
].map(([id,mode,days,rub,devices])=>({
 id,title:'Тариф '+id,status:mode,days,devices,
 price_rub:rub.toFixed(2),checkout_supported:mode==='existing',
 checkout_path:mode==='existing'?'/checkout.html?plan='+id:null
}));
global.fetch=async()=>({ok:true,json:async()=>({total:22,plans})});
function all(el){return [el,...el.children.flatMap(all)]}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
 await tick();await tick();
 const items=all(root).filter(x=>x.tag==='article');
 assert.equal(items.length,21);
 const links=all(root).filter(x=>x.tag==='a');
 const upcoming=items.filter(x=>all(x).some(n=>n.textContent==='В подготовке'));
 assert.equal(links.length,11);
 assert.equal(upcoming.length,10);
 assert.equal(all(root).filter(x=>x.tag==='button'&&x.disabled).length,10);
 assert.ok(links.every(x=>/^\/checkout\.html\?plan=(7|14|30|45|60|90|120|180|365|30-family|365-family)$/.test(x.href)));
 assert.ok(links.some(x=>x.href.includes('30-family')));
 assert.ok(status.textContent.includes('22 варианта'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / "tariff-catalog.js")],
        capture_output=True, text=True, check=False, timeout=15,
    )
    assert result.returncode == 0, result.stderr + result.stdout
