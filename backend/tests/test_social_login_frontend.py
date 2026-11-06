"""Google + Telegram OIDC tabs and graceful fallback in the browser UI."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_three_login_methods_are_present_and_clear():
    with TestClient(app) as client:
        account = client.get("/account.html")
        assert account.status_code == 200
        page = account.text
        for name in ("telegram", "email", "google"):
            assert f'data-auth-tab="{name}"' in page
            assert f'data-auth-pane="{name}"' in page
        assert 'href="/api/google/start"' in page
        assert 'href="/api/telegram-oidc/start"' in page
        assert 'id="account-google-status"' in page
        assert 'id="account-telegram-legacy"' in page
        assert "account-login.js?v=" in page


def test_google_and_modern_telegram_login_buttons_load_only_when_configured():
    script = SITE / "account-login.js"
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
class Node{
  constructor(data={}){this.dataset=data;this.events={};this.attributes={};
    this.hidden=true;this.disabled=false;this.textContent='';this.value='';}
  addEventListener(event,fn){this.events[event]=fn;}
  setAttribute(k,v){this.attributes[k]=v;}
  querySelector(s){return s==='button[type="submit"]'?this.submitButton:null;}
  focus(){}
}
const tabs=['telegram','email','google'].map(v=>new Node({authTab:v}));
const panes=['telegram','email','google'].map(v=>new Node({authPane:v}));
const ids={};
for(const id of ['account-google-start','account-google-status',
 'account-telegram-oidc-start','account-telegram-legacy','account-widget',
 'account-auth-status','account-telegram-retry','auth-email-input',
 'auth-email-code'])ids['#'+id]=new Node();
ids['[data-auth-form="email"]']=new Node();
ids['[data-auth-form="email"]'].submitButton=new Node();
ids['[data-auth-verify="email"]']=new Node();
ids['[data-auth-verify="email"]'].submitButton=new Node();
ids['[data-auth-message="email"]']=new Node();
ids['[data-auth-availability]']=new Node();
const root={
  querySelector:k=>ids[k]||null,
  querySelectorAll:k=>k==='[data-auth-tab]'?tabs:k==='[data-auth-pane]'?panes:[]
};
global.document={getElementById:k=>k==='account-auth-panel'?root:null};
const scenario=process.argv[2];
let legacyCalls=0,oidcCalls=0,legacyWidgetCalls=0;
global.window={
  location:{search:'?login=google'},
  VainahTelegramWidget:{mount(){legacyWidgetCalls++;}}
};
global.fetch=async path=>{
  if(path==='/api/email-auth/config')
    return {ok:true,json:async()=>({available:true})};
  if(path==='/api/google/config')
    return {ok:true,json:async()=>({available:scenario==='ready'})};
  if(path==='/api/telegram-oidc/config'){
    oidcCalls++;
    return {ok:true,json:async()=>({available:scenario==='ready'})};
  }
  if(path==='/api/telegram/config'){
    legacyCalls++;
    return {ok:true,json:async()=>({
      available:scenario==='legacy',bot_username:'VainahVPNbot'
    })};
  }
  throw Error('unexpected '+path);
};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();await tick();
  assert.equal(panes[2].hidden,false);
  assert.equal(panes[1].hidden,true);
  assert.equal(ids['#account-google-start'].hidden,scenario!=='ready');
  tabs[0].events.click();await tick();await tick();
  assert.equal(oidcCalls,1);
  if(scenario==='ready'){
    assert.equal(ids['#account-telegram-oidc-start'].hidden,false);
    assert.equal(ids['#account-telegram-legacy'].hidden,true);
    assert.equal(legacyCalls,0);
    assert.equal(legacyWidgetCalls,0);
  }else if(scenario==='legacy'){
    assert.equal(ids['#account-telegram-oidc-start'].hidden,true);
    assert.equal(legacyCalls,1);
    assert.equal(legacyWidgetCalls,1);
    assert.equal(ids['#account-telegram-legacy'].hidden,false);
  }else{
    assert.equal(ids['#account-telegram-oidc-start'].hidden,true);
    assert.equal(legacyCalls,1);
    assert.equal(legacyWidgetCalls,0);
    assert.equal(ids['#account-telegram-retry'].disabled,false);
    assert.ok(ids['#account-auth-status'].textContent.includes('BotFather'));
  }
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    for scenario in ("ready", "legacy", "disabled"):
        result = subprocess.run(
            ["node", "-e", harness, str(script), scenario],
            capture_output=True, check=False, text=True, timeout=12,
        )
        assert result.returncode == 0, scenario + "\n" + result.stdout + result.stderr
