"""Execute public website interactive modules with a tiny real Node DOM stub."""

from __future__ import annotations

import subprocess
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "storefront"


def run_node(harness: str, filename: str) -> None:
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / filename)],
        text=True, capture_output=True, check=False, timeout=16,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_knowledge_library_search_and_category_buttons():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const events={};
const cards=[
  {textContent:'Тариф на 30 дней',dataset:{category:'plans'},hidden:false},
  {textContent:'Android подключение',dataset:{category:'devices'},hidden:false}
];
const query={value:'',addEventListener(n,fn){events['query']=fn;}};
const category={value:'all',addEventListener(n,fn){events['category']=fn;}};
const count={textContent:''},empty={hidden:true};
const root={
  querySelector(s){return {'[data-library-search]':query,
    '[data-library-category]':category,'[data-library-count]':count,
    '[data-library-empty]':empty}[s]||null;},
  querySelectorAll(){return cards;}
};
global.document={
  querySelector(s){return s==='[data-knowledge-library]'?root:null;}
};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
assert.equal(count.textContent,'Найдено: 2 из 2 материалов');
query.value='Android';events.query();
assert.equal(cards[0].hidden,true);assert.equal(cards[1].hidden,false);
assert.equal(count.textContent,'Найдено: 1 из 2 материалов');
category.value='plans';events.category();
assert.equal(empty.hidden,false);
assert.equal(count.textContent,'Найдено: 0 из 2 материалов');
"""
    run_node(harness, "toolkit-ui.mjs")


def test_network_toolbox_calculates_and_clears_without_fetch():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
class Node{
  constructor(){this.events={};this.textContent='';this.value='';this.hidden=true;
    this.disabled=true;this.children=[];}
  addEventListener(type,handler){this.events[type]=handler;}
  replaceChildren(...items){this.children=[...items];}
  append(item){this.children.push(item);}
  focus(){}select(){}
}
const $=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id)};
const makeForm=(name,fields)=>{
  const listeners={},out=new Node(),detail=new Node(),title=new Node();
  title.textContent=name;
  const items=Object.fromEntries(Object.entries(fields).map(([key,value])=>
    [key,{value:String(value)}]));
  return {dataset:{calculator:name},events:listeners,inputs:items,
    addEventListener(type,handler){this.events[type]=handler;},
    querySelector(selector){
      if(selector==='h2')return title;
      if(selector==='[data-result]')return out;
      if(selector==='[data-detail]')return detail;
      const m=selector.match(/\[name="([^"]+)"\]/);
      return m?items[m[1]]:null;
    },
    reset(){},out,detail
  };
};
const forms=[
  makeForm('convert',{mbps:80}),
  makeForm('download',{size:1024,speed:100,unit:'mib'}),
  makeForm('quota',{limit:10,used:3}),
  makeForm('compare',{direct:100,vpn:82})
];
const root={
  querySelector(s){return $(s);},
  querySelectorAll(s){return s==='form[data-calculator]'?forms:[];}
};
global.document={getElementById:id=>id==='network-toolkit'?root:null,createElement:()=>new Node()};
Object.defineProperty(global,'navigator',{configurable:true,
  value:{clipboard:{writeText:async x=>{global.copied=x}}}});
global.fetch=()=>{throw Error('Network is forbidden in offline calculator')};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const submit=form=>form.events.submit({preventDefault(){}});
forms.forEach(submit);
assert.equal(forms[0].out.textContent,'10 МБ/с');
assert.equal(forms[2].out.textContent,'7 ГиБ осталось');
assert.ok(forms[3].out.textContent.includes('-18'));
assert.equal($('#nt-history').children.length,4);
(async()=>{
  await $('#nt-copy').events.click();
  assert.ok(global.copied.includes('convert'));
  $('#nt-clear').events.click();
  assert.equal($('#nt-copy').disabled,true);
  assert.equal($('#nt-history').children.length,1);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run_node(harness, "network-toolkit.js")


def test_setup_wizard_responds_to_platform_and_checklist():
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{constructor(){this.events={};this.dataset={};this.style={};this.textContent='';
  this.attrs={};this.checked=false;this.children=[];}
  addEventListener(k,fn){this.events[k]=fn;}
  setAttribute(k,v){this.attrs[k]=v;}
  replaceChildren(...items){this.children=[...items];}
  append(item){this.children.push(item);}
}
const plats=['ios','android','windows','macos'].map(x=>{
  const n=new Node();n.dataset.platformChoice=x;return n;
});
const stages=['before','link','issue'].map(x=>{
  const n=new Node();n.dataset.stageChoice=x;return n;
});
const items=Array.from({length:4},()=>new Node());
const refs=Object.fromEntries([
  '[data-setup-progress]','.tool-progress','[data-setup-complete]',
  '[data-setup-reset]','[data-wizard-title]','[data-wizard-summary]',
  '[data-wizard-steps]','[data-wizard-link]'
].map(k=>[k,new Node()]));
const root={querySelector(s){return refs[s]||null;},
  querySelectorAll(s){
    if(s==='[data-platform-choice]')return plats;
    if(s==='[data-stage-choice]')return stages;
    if(s==='[data-setup-check]')return items;
    return [];
  }};
global.document={
  querySelector(s){return s==='[data-setup-wizard]'?root:null;},
  createElement:()=>new Node()
};
const data=new Map();
global.sessionStorage={
  getItem(key){return data.get(key)||null;},
  setItem(key,value){data.set(key,value);}
};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
assert.ok(refs['[data-wizard-title]'].textContent.includes('iPhone'));
items[0].checked=true;items[0].events.change();
assert.equal(refs['.tool-progress'].attrs['aria-valuenow'],'1');
plats[1].events.click();
assert.equal(refs['.tool-progress'].attrs['aria-valuenow'],'0');
assert.ok(refs['[data-wizard-title]'].textContent.includes('Android'));
stages[1].events.click();
assert.ok(refs['[data-wizard-title]'].textContent.includes('VPN-клиент'));
plats[0].events.click();
assert.equal(refs['.tool-progress'].attrs['aria-valuenow'],'1');
"""
    run_node(harness, "toolkit-ui.mjs")
