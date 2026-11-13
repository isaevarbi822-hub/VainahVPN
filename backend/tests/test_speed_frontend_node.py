"""Run the real Speed Lab JavaScript in a minimal Node DOM to assert request sizes."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "storefront/speed-test.js"


def test_speedtest_ui_executes_both_modes_with_correct_network_budgets():
    harness = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes=new Map();
class Element{
  constructor(){this.textContent='';this.disabled=false;this.hidden=false;
    this.style={width:''};this.events={};this.attributes={};}
  addEventListener(name,fn){this.events[name]=fn;}
  setAttribute(name,value){this.attributes[name]=value;}
}
const $=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
let mode='eco',now=100;
global.document={getElementById:$,querySelector:()=>({value:mode})};
global.window={addEventListener(){}};
global.navigator={clipboard:{writeText:async()=>{}}};
global.performance={now:()=>{now+=15;return now}};
global.fetch=async (url,opts={})=>{
  const path=String(url).split('?')[0];
  requests.push({path,size:opts.body?.byteLength||0});
  if(path.endsWith('/ping'))return {ok:true,status:204};
  if(path.endsWith('/download'))return {ok:true,status:200,
    arrayBuffer:async()=>new ArrayBuffer(512*1024)};
  if(path.endsWith('/upload'))return {ok:true,status:200,
    json:async()=>({received_bytes:opts.body.byteLength})};
  throw Error('Unexpected request: '+path);
};
let requests=[];
(async()=>{
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
  await $('speed-start').events.click();
  assert.equal(requests.filter(x=>x.path.endsWith('/ping')).length,3);
  assert.equal(requests.filter(x=>x.path.endsWith('/download')).length,1);
  assert.equal(requests.filter(x=>x.path.endsWith('/upload')).length,1);
  assert.equal(requests.find(x=>x.path.endsWith('/upload')).size,128*1024);
  assert.equal($('speed-options').disabled,false);
  assert.equal($('speed-copy').disabled,false);
  assert.equal($('speed-start').disabled,false);
  assert.ok($('speed-network-mode').textContent.includes('экономный'));
  requests=[];
  mode='normal';
  await $('speed-start').events.click();
  assert.equal(requests.filter(x=>x.path.endsWith('/ping')).length,5);
  assert.equal(requests.filter(x=>x.path.endsWith('/download')).length,3);
  assert.equal(requests.filter(x=>x.path.endsWith('/upload')).length,2);
  assert.equal(requests.find(x=>x.path.endsWith('/upload')).size,256*1024);
  assert.ok($('speed-previous').textContent.includes('Режим проверки изменился'));
  assert.equal($('speed-start').disabled,false);
  console.log('Speed Lab functional DOM checks passed');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", harness, str(SCRIPT)], text=True,
        capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
