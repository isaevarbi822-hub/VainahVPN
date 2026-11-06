"""Execute real client and operator ticket UI in Node DOM stubs."""

from __future__ import annotations

import subprocess
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_customer_support_form_history_and_unconfigured_fallback():
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(){this.events={};this.children=[];this.textContent='';
    this.value='';this.disabled=false;this.href='';this.className='';}
  addEventListener(name,handler){this.events[name]=handler;}
  replaceChildren(...children){this.children=[...children];}
  append(...children){this.children.push(...children);}
}
const nodes=new Map();
const $=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
global.document={getElementById:$,createElement:()=>new Element()};
$('vs-category').value='connection';
const scenario=process.argv[2];
const calls=[];
const reply=body=>({ok:true,json:async()=>body});
global.fetch=async(path,options={})=>{
  calls.push({path,options});
  if(path==='/api/support/config')
    return reply({available:scenario==='ready',email_notifications_available:true});
  if(path==='/api/email-auth/account')
    return reply({authenticated:true});
  if(path==='/api/telegram/account')
    return reply({authenticated:false});
  if(path.includes('/email-notifications')&&options.method==='POST')
    return reply({updated:true,email_notifications:true});
  if(path==='/api/support/tickets'&&options.method==='POST')
    return reply({id:'ticketabc',status:'open'});
  if(path==='/api/support/tickets')
    return reply({items:[{id:'ticketabc',category:'connection',
      message:'Cannot connect <script>alert(1)</script>',
      status:'answered',reply:'Please check your client version.',
      created_at:'2026-11-06T00:00:00Z'}]});
  throw Error('Unexpected request '+path);
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await tick();await tick();await tick();
  if(scenario==='ready'){
    assert.equal($('vs-submit').disabled,false);
    assert.equal($('vs-tickets').children.length,1);
    const ticket=$('vs-tickets').children[0];
    assert.ok(ticket.children.some(c=>c.textContent.includes('<script>')));
    const toggle=ticket.children.at(-1).children.at(-1);
    await toggle.events.click();
    const preferences=calls.filter(c=>c.path.includes('/email-notifications'));
    assert.equal(preferences.length,1);
    assert.equal(JSON.parse(preferences[0].options.body).enabled,true);
    $('vs-notify-email').checked=true;
    $('vs-message').value='VPN does not connect on my phone';
    $('vs-message').events.input();
    assert.ok($('vs-counter').textContent.startsWith('32 /')||
      $('vs-counter').textContent.includes('/ 1500'));
    await $('vs-form').events.submit({preventDefault(){}});
    assert.equal($('vs-message').value,'');
    const posted=calls.find(c=>c.options.method==='POST'&&c.path==='/api/support/tickets');
    assert.ok(posted);
    assert.equal(posted.path,'/api/support/tickets');
    assert.equal(posted.options.credentials,'same-origin');
    assert.equal(JSON.parse(posted.options.body).category,'connection');
    assert.equal(JSON.parse(posted.options.body).notify_email,true);
  }else{
    assert.equal($('vs-submit').disabled,true);
    assert.ok($('vs-status').textContent.includes('не настроен'));
    assert.equal(calls.filter(c=>c.options.method==='POST').length,0);
  }
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    for scenario in ("ready", "disabled"):
        result = subprocess.run(
            ["node", "-e", harness, str(SITE / "support-center.js"), scenario],
            check=False, capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, scenario + ": " + result.stdout + result.stderr


def test_operator_never_places_secret_in_url_and_can_reply():
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(){this.events={};this.children=[];this.textContent='';
    this.value='';this.disabled=false;this.className='';}
  addEventListener(name,handler){this.events[name]=handler;}
  replaceChildren(...children){this.children=[...children];}
  append(...children){this.children.push(...children);}
}
const nodes=new Map();
const $=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
global.document={getElementById:$,createElement:()=>new Element()};
global.window={addEventListener(){}};
const secret='SUPER_SECRET_OPERATOR_KEY_FOR_TESTS_12345678901234';
$('operator-key').value=secret;
const calls=[];
global.fetch=async(path,options)=>{
  calls.push({path,options});
  return {ok:true,json:async()=>(
    options.method==='POST'?{updated:true}:{items:[
      {id:'ticket12345678901234567',category:'account',
       status:'open',message:'Cannot log in',owner_reference:'dummyowner'}
    ]}
  )};
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  $('operator-load').events.click();
  await tick();await tick();
  assert.equal($('operator-key').value,'');
  assert.equal($('operator-list').children.length,1);
  assert.equal(calls[0].options.headers['X-Vainah-Support-Key'],secret);
  assert.ok(!calls[0].path.includes(secret));
  const card=$('operator-list').children[0];
  const form=card.children[card.children.length-1];
  form.children[0].value='Исправлено. Повторите вход.';
  form.children[1].value='answered';
  await form.events.submit({preventDefault(){}});
  assert.equal(calls[1].options.method,'POST');
  assert.equal(calls[1].options.credentials,'omit');
  assert.equal(calls[1].options.headers['X-Vainah-Support-Key'],secret,
    'Operator key MUST be included on reply POST; Content-Type cannot replace it');
  assert.equal(calls[1].options.headers['Content-Type'],'application/json');
  assert.equal(JSON.parse(calls[1].options.body).status,'answered');
  $('operator-lock').events.click();
  assert.equal($('operator-key').value,'');
  assert.ok($('operator-status').textContent.includes('закрыт'));
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / "support-operator.js")],
        check=False, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
