"""Realistic local diagnosis without VPN keys, fabricated RTT or private reports."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"
BASE = "https://vainahvpn-python-preview.onrender.com"


def _node(js: str, *files: Path) -> None:
    result = subprocess.run(
        ["node", "-e", js, *(str(p) for p in files)],
        check=False, timeout=20, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_diagnostic_rules_for_account_states_and_platforms():
    source = SITE / "diagnostic-rules.js"
    js = r"""
const assert=require('node:assert/strict');
const r=require(process.argv[1]);
assert.equal(r.SYMPTOMS.length,6);
assert.equal(r.PLATFORMS.length,5);
const paid=r.evaluate({symptom:'cannot_connect',platform:'android',
  account:'paid_profile_active',infra:'control_plane_checks_ok',
  site:{median:45,samples:3},online:true});
assert.equal(paid.tunnel_verified,false);
assert.equal(paid.server_recommendation,null);
assert.ok(paid.facts.join(' ').includes('НЕ пинг VPN-сервера'));
assert.ok(paid.steps.join(' ').includes('Android'));
assert.ok(paid.facts.join(' ').includes('H1Cloud'));
const failed=r.evaluate({symptom:'payment',platform:'windows',
  account:'paid_profile_not_active',infra:'attention',online:true});
assert.equal(failed.priority,'attention');
assert.ok(failed.steps.join(' ').includes('Не оплачивай повторно'));
assert.ok(failed.steps.join(' ').includes('номер заказа'));
const unknown=r.evaluate({symptom:'slow',platform:'macos',
  account:'provider_unverified',infra:'partial',online:true});
assert.ok(unknown.steps.join(' ').includes('не означает завершение срока'));
assert.equal(unknown.server_recommendation,null);
const offline=r.evaluate({symptom:'no_internet',platform:'ios',
  account:'not_checked',infra:'unknown',online:false});
assert.equal(offline.priority,'attention');
assert.ok(offline.steps.join(' ').includes('Wi-Fi'));
assert.ok(offline.steps.join(' ').includes('iOS'));
assert.throws(()=>r.evaluate({symptom:'attack',platform:'android'}));
assert.throws(()=>r.evaluate({symptom:'slow',platform:'android/other'}));
for(const symptom of r.SYMPTOMS){
  for(const platform of r.PLATFORMS){
    const d=r.evaluate({symptom,platform,account:'unavailable',infra:'unknown'});
    assert.ok(d.steps.length>0);
    assert.equal(d.tunnel_verified,false);
    assert.equal(d.server_recommendation,null);
  }
}
"""
    _node(js, source)


def test_diagnostic_browser_uses_verified_status_and_sanitized_copy():
    rules = SITE / "diagnostic-rules.js"
    advisor = SITE / "diagnostic-advisor.js"
    js = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const rules=require(process.argv[1]);
class Node {
  constructor(tag='div'){this.tag=tag;this.textContent='';this.value='';
    this.children=[];this.events={};this.disabled=false;this.className='';}
  append(...x){this.children.push(...x);}
  replaceChildren(...x){this.children=x;}
  addEventListener(type,callback){this.events[type]=callback;}
}
const elements={};
for(const id of ['advisor-run','advisor-copy','advisor-result',
                 'advisor-progress','advisor-symptom','advisor-platform'])
  elements[id]=new Node();
elements['advisor-symptom'].value='cannot_connect';
elements['advisor-platform'].value='android';
global.window={VainahDiagnosticRules:rules};
global.document={getElementById:id=>elements[id]||null,
                 createElement:tag=>new Node(tag)};
let copied=null,clock=0;
Object.defineProperty(global,'navigator',{
  configurable:true,value:{onLine:true,clipboard:{writeText:async s=>{copied=s;}}}
});
global.performance={now:()=>{clock+=42;return clock;}};
global.AbortSignal={timeout:()=>null};
const calls=[];
global.fetch=async(path,options)=>{
  calls.push([path,options.credentials]);
  if(path==='/api/site/check/summary')
    return {ok:true,json:async()=>({summary:'partial'})};
  if(path==='/api/account/connection-check')
    return {ok:true,json:async()=>({
      result:'paid_profile_active',
      subscription_url:'https://secret.example/subscriber/private-id',
      email:'secret-buyer@example.com',
      order_id:'do-not-copy'
    })};
  if(path==='/api/speedtest/ping')return {status:204};
  throw Error('Unexpected path: '+path);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const content=root=>[root,...root.children.flatMap(x=>collect(x))]
  .map(n=>n.textContent).join(' ');
function collect(n){return [n,...n.children.flatMap(collect)];}
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[2],'utf8'));
  elements['advisor-run'].events.click();
  for(let i=0;i<8;i++)await tick();
  assert.equal(elements['advisor-run'].disabled,false);
  assert.equal(elements['advisor-copy'].disabled,false);
  const output=content(elements['advisor-result']);
  assert.ok(output.includes('Android'));
  assert.ok(output.includes('Render'));
  assert.ok(output.includes('VPN'));
  assert.equal(calls.filter(x=>x[0]==='/api/speedtest/ping').length,3);
  assert.deepEqual(calls.find(x=>x[0]==='/api/account/connection-check'),
                   ['/api/account/connection-check','same-origin']);
  assert.ok(calls.filter(x=>x[0]==='/api/speedtest/ping').every(x=>x[1]==='omit'));
  await elements['advisor-copy'].events.click();
  assert.ok(copied.includes('Вainah') || copied.includes('Vainah Check'));
  assert.ok(copied.includes('VPN-туннель: не проверялся'));
  assert.ok(!copied.includes('secret.example'));
  assert.ok(!copied.includes('secret-buyer@example.com'));
  assert.ok(!copied.includes('do-not-copy'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    _node(js, rules, advisor)


def test_diagnostic_frontend_syntax_and_security_headers():
    html = (SITE / "connection-check.html").read_text(encoding="utf-8")
    source = (SITE / "diagnostic-advisor.js").read_text(encoding="utf-8")
    rules = (SITE / "diagnostic-rules.js").read_text(encoding="utf-8")
    assert 'id="advisor-run"' in html
    assert 'id="advisor-copy"' in html
    assert "diagnostic-rules.js" in html
    assert "diagnostic-advisor.js" in html
    assert html.index("diagnostic-rules.js") < html.index("diagnostic-advisor.js")
    assert "localStorage" not in source and "sessionStorage" not in source
    assert "localStorage" not in rules and "sessionStorage" not in rules
    assert "innerHTML" not in source and "innerHTML" not in rules
    assert "navigator.clipboard.writeText" in source
    for name in ("diagnostic-rules.js", "diagnostic-advisor.js"):
        _node("", SITE / name)
        r = subprocess.run(
            ["node", "--check", str(SITE / name)],
            check=False, capture_output=True, text=True, timeout=15,
        )
        assert r.returncode == 0, r.stderr
    with TestClient(app, base_url=BASE) as client:
        page = client.get("/connection-check.html")
        js = client.get("/diagnostic-advisor.js")
        rule_js = client.get("/diagnostic-rules.js")
    for response in (page, js, rule_js):
        assert response.status_code == 200
        assert "no-store" in response.headers.get("cache-control", "")
        assert "unsafe-inline" not in response.headers.get("content-security-policy", "")
        assert "noindex" in response.headers.get("x-robots-tag", "")
