"""Website gift cards, smart renewals and public server directory regressions."""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from vainah import account_feed, email_auth, gift_cards, reminder_preferences
from vainah.billing import get_plan
from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"
ORIGIN = "https://vainahvpn-python-preview.onrender.com"


def _node(script: str, *paths: Path) -> None:
    outcome = subprocess.run(
        ["node", "-e", script, *(str(p) for p in paths)],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert outcome.returncode == 0, outcome.stderr + outcome.stdout


def test_gift_catalog_uses_verified_plan_prices_not_frontend_copies(monkeypatch):
    monkeypatch.delenv("VAINAH_GIFT_CARDS_ENABLED", raising=False)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/account/gift-cards/status")
        assert response.status_code == 200
        catalog = response.json()["plans"]
        assert response.json()["purchase_enabled"] is False
        assert len(catalog) == 6
        for item in catalog:
            actual = get_plan(item["id"])
            assert item["title"] == actual["title"]
            assert item["days"] == actual["days"]
            assert item["devices"] == actual["devices"]
            assert item["price_rub"] == f'{actual["kopeks"] / 100:.2f}'
            assert "secret" not in str(item).lower()
        assert "pilot-1d" not in [p["id"] for p in catalog]


def test_verified_reminder_status_changes_only_with_scheduled_delivery(monkeypatch):
    monkeypatch.setenv(
        "SESSION_SIGNING_KEY",
        "website-reminder-test-long-enough-0123456789abcdefgh",
    )
    monkeypatch.setattr(reminder_preferences, "_read", lambda _: True)
    monkeypatch.setattr(reminder_preferences, "_write", lambda *_: None)
    monkeypatch.setattr(reminder_preferences, "delivery_active", lambda: False)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                           email_auth._sign_session("member@example.com"))
        ordinary = client.get("/api/account/reminder-preference").json()
        assert ordinary["enabled"] is True
        assert ordinary["delivery_active"] is False

        monkeypatch.setattr(reminder_preferences, "delivery_active", lambda: True)
        enabled = client.get("/api/account/reminder-preference").json()
        assert enabled["enabled"] is True
        assert enabled["delivery_active"] is True
        changed = client.post(
            "/api/account/reminder-preference",
            headers={"Origin": ORIGIN}, json={"enabled": False},
        )
        assert changed.status_code == 200
        assert changed.json()["delivery_active"] is True
        assert changed.json()["enabled"] is False


def test_schedule_confirmation_required_separately_from_email_flag(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "s" * 48)
    monkeypatch.setenv("VAINAH_REMINDER_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("VAINAH_REMINDER_RUNNER_KEY", "k" * 48)
    monkeypatch.setattr(
        "vainah.email_delivery.email_service_ready", lambda: True
    )
    monkeypatch.delenv("VAINAH_REMINDER_SCHEDULE_CONFIRMED", raising=False)
    assert reminder_preferences.delivery_active() is False
    monkeypatch.setenv("VAINAH_REMINDER_SCHEDULE_CONFIRMED", "confirmed")
    assert reminder_preferences.delivery_active() is True
    monkeypatch.setenv("VAINAH_REMINDER_RUNNER_KEY", "s" * 48)
    assert reminder_preferences.delivery_active() is False


def test_expiring_subscription_alerts_for_seven_three_one_days(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "x" * 48)
    owner = "a" * 64
    for hours, title in (
        (12, "менее суток"),
        (48, "3 дня"),
        (144, "7 дней"),
    ):
        future = datetime.now(UTC) + timedelta(hours=hours)
        alerts = account_feed._notifications(owner, {
            "orders": [{"paid": True, "delivered": True}],
            "subscription": {
                "paid": True, "status": "delivered",
                "expires_at": future.isoformat(),
            },
            "h1cloud": {"status": "active"},
        })
        expiry = [a for a in alerts if a["type"] == "expiry"]
        assert len(expiry) == 1
        assert title in expiry[0]["title"]
        assert expiry[0]["href"] == "/account.html"
        assert "vless://" not in str(expiry)
    false_alerts = account_feed._notifications(owner, {
        "orders": [{"paid": True, "delivered": True}],
        "subscription": {
            "paid": False, "status": "delivered",
            "expires_at": (datetime.now(UTC)+timedelta(hours=4)).isoformat(),
        },
    })
    assert not any(a["type"] == "expiry" for a in false_alerts)


def test_site_scripts_and_private_data_safety():
    gift = (SITE / "gift-cards.js").read_text(encoding="utf-8")
    public = (SITE / "public-servers.js").read_text(encoding="utf-8")
    html = (SITE / "servers.html").read_text(encoding="utf-8")
    notification_page = (SITE / "notifications.html").read_text(encoding="utf-8")
    assert "public-servers.js" in html
    assert "server-search" in html
    assert "server-only-favorites" in html
    assert "server-sort" in html
    assert "/api/site/locations" in public
    assert "localStorage" in public  # only publicly visible location names
    assert "localStorage" not in gift
    assert "innerHTML" not in public and "innerHTML" not in gift
    assert "account-reminder-optin" in notification_page
    assert "account-reminder-preference.js" in notification_page
    for filename in ("gift-cards.js", "public-servers.js",
                     "account-reminder-preference.js"):
        script = SITE / filename
        check = subprocess.run(
            ["node", "--check", str(script)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        assert check.returncode == 0, check.stderr


def test_public_directory_browser_filters_favorites_and_refreshes():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class N {
  constructor(tag='div'){
    this.tag=tag;this.children=[];this.events={};this.textContent='';
    this.value='';this.disabled=false;this.attributes={};
  }
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attributes[k]=String(v);}
  addEventListener(k,fn){this.events[k]=fn;}
}
const ids={};
for(const id of ['server-search','server-only-favorites','server-sort',
  'server-directory-status','server-refresh'])ids[id]=new N();
ids['server-sort'].value='original';
const root=new N();
global.document={querySelector:q=>q==='[data-live-locations]'?root:null,
  getElementById:id=>ids[id]||null,createElement:t=>new N(t)};
const saved={};
global.localStorage={
  getItem:k=>saved[k]||null,setItem:(k,v)=>{saved[k]=v}
};
const replies=[
 {locations:[{name:'Германия',flag:'🇩🇪'},{name:'Испания',flag:'🇪🇸'}]},
 {locations:[{name:'Германия',flag:'🇩🇪'},{name:'Испания',flag:'🇪🇸'}]}
];
let calls=0;
global.fetch=async(path,opts)=>{
  assert.equal(path,'/api/site/locations');
  assert.equal(opts.credentials,'omit');
  return {ok:true,json:async()=>replies[Math.min(calls++,1)]};
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();await tick();
  assert.equal(root.children.length,2);
  root.children[0].children[2].events.click();
  assert.ok(saved['vainah-public-location-favorites-v1'].includes('Германия'));
  ids['server-only-favorites'].events.click();
  assert.equal(root.children.length,1);
  assert.equal(root.children[0].children[1].children[0].textContent,'Германия');
  ids['server-search'].value='ИСП';
  ids['server-search'].events.input();
  assert.equal(root.children.length,1);
  assert.equal(root.children[0].tag,'p'); // no matches in favorites
  ids['server-only-favorites'].events.click();
  assert.equal(root.children.length,1);
  assert.equal(root.children[0].children[1].children[0].textContent,'Испания');
  ids['server-search'].value='';
  ids['server-search'].events.input();
  ids['server-sort'].value='alpha';ids['server-sort'].events.change();
  assert.equal(root.children.length,2);
  await ids['server-refresh'].events.click();
  await tick();
  assert.equal(root.children.length,2);
  assert.ok(calls>=2);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    _node(script, SITE / "public-servers.js")
