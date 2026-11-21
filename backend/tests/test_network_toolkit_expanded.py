"""New network calculations work locally with validated inputs and no API writes."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_twelve_network_calculators_are_public_and_searchable():
    with TestClient(app) as client:
        page = client.get("/network-toolkit.html")
        script = client.get("/network-toolkit.js")
        assert page.status_code == 200
        assert script.status_code == 200
        for name in ("convert", "download", "upload", "stream", "quota",
                     "daily", "compare", "latency", "monthly", "lifespan",
                     "devices", "backup"):
            assert f'data-calculator="{name}"' in page.text
        assert '12 сетевых инструментов' in page.text
        assert 'fetch(' not in script.text
        assert 'innerHTML' not in script.text


def test_network_calculators_monthly_device_backup_and_validation():
    script_path = SITE / "network-toolkit.js"
    harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(){this.textContent='';this.value='';this.events={};this.hidden=false;this.disabled=false;this.children=[];}
  addEventListener(type,fn){this.events[type]=fn;}
  replaceChildren(...a){this.children=[...a];}
  append(...a){this.children.push(...a);}
  focus(){}
  select(){}
}
function form(name,fields){
  const element=new Element();
  element.dataset={calculator:name};
  element.fields=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:String(v)}]));
  element.out=new Element();element.detail=new Element();
  element.heading=new Element();element.heading.textContent=name;
  element.querySelector=selector=>{
    const match=selector.match(/\[name="([^"]+)"\]/);
    if(match)return element.fields[match[1]];
    if(selector==='h2')return element.heading;
    if(selector==='[data-result]')return element.out;
    if(selector==='[data-detail]')return element.detail;
    return null;
  };
  element.reset=()=>{};
  return element;
}
const forms=[
  form('monthly',{daily:1.5,days:30}),
  form('lifespan',{remaining:8,daily:1}),
  form('devices',{limit:10,devices:2}),
  form('backup',{size:5,speed:20,limit:10})
];
const root={querySelectorAll:()=>forms,querySelector(selector){
  const map={'#nt-history':global.history,'#nt-copy':global.copy,
             '#nt-clear':global.clear,'#nt-manual':global.manual,
             '#nt-notice':global.notice};
  return map[selector];
}};
for(const key of ['history','copy','clear','manual','notice'])global[key]=new Element();
global.document={getElementById:()=>root,createElement:()=>new Element()};
Object.defineProperty(global,'navigator',{configurable:true,value:{
  clipboard:{writeText:async t=>{global.copied=t;}}
}});
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  for(const f of forms)f.events.submit({preventDefault(){}});
  assert.ok(forms[0].out.textContent.includes('45'));
  assert.ok(forms[1].out.textContent.includes('8'));
  assert.ok(forms[2].out.textContent.includes('5'));
  assert.ok(forms[3].detail.textContent.includes('50%'));
  assert.equal(history.children.length,4);
  await copy.events.click();
  assert.ok(global.copied.includes('monthly'));
  forms[2].fields.devices.value='1.5';
  forms[2].events.submit({preventDefault(){}});
  assert.equal(forms[2].out.textContent,'—');
  assert.ok(forms[2].detail.textContent.includes('целое'));
  assert.equal(history.children.length,3);
  clear.events.click();
  assert.equal(history.children.length,1);
  assert.equal(copy.disabled,true);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(script_path)],
        capture_output=True, check=False, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
