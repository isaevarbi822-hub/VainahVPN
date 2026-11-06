"""Telegram Login widget only loads when visible and can recover from errors."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

ROOT = Path(__file__).resolve().parents[2] / "storefront"


def test_telegram_login_still_has_signed_backend_and_visible_tab():
    with TestClient(app) as client:
        page = client.get("/account.html")
        script = client.get("/account-login.js")
        assert page.status_code == 200
        assert script.status_code == 200
        assert 'data-auth-tab="telegram"' in page.text
        assert 'id="account-telegram-retry"' in page.text
        assert 'id="account-widget"' in page.text
        assert "onVainahAccountAuth(user)" in script.text
        assert "if(method==='telegram')void initTelegram()" in script.text
        assert "requestedTelegram?'telegram':'email'" in script.text


def test_lazy_telegram_mount_retry_and_direct_tab_link():
    script_path = ROOT / "account-login.js"
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
class Node {
  constructor(dataset={}){this.dataset=dataset;this.events={};
    this.disabled=false;this.hidden=false;this.textContent='';
    this.value='';this.attributes={};this.tabIndex=0;}
  addEventListener(event,fn){this.events[event]=fn;}
  setAttribute(k,v){this.attributes[k]=v;}
  focus(){this.focused=true;}
  querySelector(selector){
    if(selector==='button[type="submit"]')return this.button;
    return null;
  }
}
const tabs=[new Node({authTab:'telegram'}),new Node({authTab:'email'})];
const panes=[new Node({authPane:'telegram'}),new Node({authPane:'email'})];
const emailForm=new Node(),verifyForm=new Node();
emailForm.button=new Node();verifyForm.button=new Node();
const retry=new Node(),status=new Node(),widget=new Node(),availability=new Node();
const emailInput=new Node(),codeInput=new Node(),emailMessage=new Node();
const map={
  '[data-auth-availability]':availability,'#account-auth-status':status,
  '#account-telegram-retry':retry,
  '[data-auth-form="email"]':emailForm,
  '[data-auth-verify="email"]':verifyForm,
  '#auth-email-input':emailInput,'#auth-email-code':codeInput,
  '[data-auth-message="email"]':emailMessage,
  '#account-widget':widget,
};
const root={querySelector:selector=>map[selector]||null,
  querySelectorAll:selector=>selector==='[data-auth-tab]'?tabs:selector==='[data-auth-pane]'?panes:[]};
global.document={getElementById:id=>id==='account-auth-panel'?root:null};
const scenario=process.argv[2]||'available';
let configCalls=0,widgetsMounted=0;
global.window={
  location:{search:scenario==='direct'?'?login=telegram':''},
  VainahTelegramWidget:{mount(options){
    widgetsMounted++;
    assert.equal(options.botUsername,'VainahVPNbot');
    assert.equal(options.callback,'onVainahAccountAuth(user)');
    retry.addEventListener('click',()=>{widgetsMounted++;});
  }}
};
global.fetch=async url=>{
  if(url==='/api/telegram/config'){
    configCalls++;
    return {ok:true,json:async()=>scenario==='unavailable'?
      {available:false,message:'Not configured'}:{available:true,bot_username:'VainahVPNbot'}};
  }
  if(url==='/api/email-auth/config')
    return {ok:true,json:async()=>({available:true})};
  throw Error('Unexpected '+url);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();
  if(scenario==='direct'){
    assert.equal(configCalls,1);
    assert.equal(widgetsMounted,1);
    assert.equal(panes[0].hidden,false);
    assert.equal(tabs[0].attributes['aria-selected'],'true');
  } else {
    assert.equal(configCalls,0,'Do not load third-party Telegram while hidden');
    assert.equal(panes[0].hidden,true);
    tabs[0].events.click();
    await tick();
    assert.equal(configCalls,1);
    assert.equal(panes[0].hidden,false);
    assert.equal(panes[1].hidden,true);
    if(scenario==='unavailable'){
      assert.equal(widgetsMounted,0);
      assert.equal(retry.disabled,false);
      assert.ok(status.textContent.includes('пока не настроен'));
      retry.events.click();await tick();
      assert.equal(configCalls,2);
    } else {
      assert.equal(widgetsMounted,1);
      tabs[1].events.click();
      tabs[0].events.click();await tick();
      assert.equal(configCalls,1);
      assert.equal(widgetsMounted,1);
      retry.events.click();await tick();
      assert.equal(widgetsMounted,2);
    }
  }
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    for scenario in ("available", "unavailable", "direct"):
        result = subprocess.run(
            ["node", "-e", harness, str(script_path), scenario],
            capture_output=True, text=True, check=False, timeout=12,
        )
        assert result.returncode == 0, scenario + "\n" + result.stdout + result.stderr
