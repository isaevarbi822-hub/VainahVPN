"""Official Telegram widget reloads after network failures and uses signed callbacks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_official_login_widget_is_served_and_uses_signed_auth_callback():
    with TestClient(app) as client:
        page = client.get("/account.html")
        widget = client.get("/telegram-login-widget.js")
        assert page.status_code == 200
        assert widget.status_code == 200
        assert "https://telegram.org/js/telegram-widget.js?22" in widget.text
        assert "data-onauth" in widget.text
        assert "onVainahAccountAuth(user)" in page.text or (
            "onVainahAccountAuth(user)" in
            (SITE / "account-login.js").read_text(encoding="utf-8")
        )


def test_telegram_external_script_retry_and_error_timer_cleanup():
    script_path = SITE / "telegram-login-widget.js"
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const events={};let scripts=[],scheduled=[],cleared=[];
class Script {
  constructor(){this.attributes={};this.async=false;}
  setAttribute(name,value){this.attributes[name]=value;}
}
const container={
  last:null,replaceChildren(){this.last=null;},
  append(script){this.last=script;scripts.push(script);},
  querySelector(selector){return selector==='iframe'&&global.hasIframe?{}:null;}
};
const retry={
  disabled:false,textContent:'',
  addEventListener(name,cb){events[name]=cb;}
};
const status={textContent:''};
global.document={createElement:tag=>{assert.equal(tag,'script');return new Script();}};
global.window={};
global.setTimeout=(callback)=>{scheduled.push(callback);return scheduled.length;};
global.clearTimeout=id=>{cleared.push(id);};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
window.VainahTelegramWidget.mount({
  container,status,retry,callback:'onVainahAccountAuth(user)',botUsername:'VainahVPNbot'
});
assert.equal(scripts.length,1);
assert.equal(retry.disabled,true);
assert.equal(scripts[0].attributes['data-telegram-login'],'VainahVPNbot');
assert.equal(scripts[0].attributes['data-onauth'],'onVainahAccountAuth(user)');
assert.ok(scripts[0].src.startsWith('https://telegram.org/'));
scripts[0].onerror();
assert.equal(retry.disabled,false);
assert.ok(status.textContent.includes('не загрузился'));
assert.deepEqual(cleared,[1]);
events.click();
assert.equal(scripts.length,2);
assert.equal(retry.disabled,true);
global.hasIframe=true;
scheduled[1]();
assert.equal(retry.disabled,false);
assert.ok(status.textContent.includes('подтверди вход'));
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script_path)],
        text=True, capture_output=True, check=False, timeout=12,
    )
    assert result.returncode == 0, result.stdout + result.stderr
