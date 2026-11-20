"""The account round trip preserves a public plan and the last successful OTP recipient."""
import subprocess
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "storefront"


def run_node(script, harness):
    result = subprocess.run(
        ["node", "-e", harness, str(SITE / script)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_resume_after_oauth_and_handle_invalid_or_expired_selection():
    run_node("account-checkout-return.js", r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const code=fs.readFileSync(process.argv[1],'utf8'), values=new Map();
const store={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
function visit(search, storage=store){
  const panel={hidden:true},link={addEventListener:(event,fn)=>{link[event]=fn;}};
  vm.runInNewContext(code,{document:{getElementById:id=>id.endsWith('resume')?panel:link},
    location:{search},sessionStorage:storage,URLSearchParams,Date});
  return {panel,link};
}
const dest='checkout.html?plan=30-family#shop-payment-panel';
assert.equal(visit('?checkout_plan=30-family').link.href,dest);
assert.equal(visit('').link.href,dest);
visit('').link.click();
assert.equal(visit('').panel.hidden,true);
assert.equal(visit('?checkout_plan=https%3A%2F%2Fother.test').panel.hidden,true);
store.setItem('vainah.checkout.return-plan',JSON.stringify({plan:'30-family',until:Date.now()-1}));
assert.equal(visit('').panel.hidden,true);
assert.equal(visit('?checkout_plan=30-family',null).link.href,dest);
""")


def test_failed_resend_does_not_change_the_recipient_or_lose_a_valid_code():
    run_node("account-login.js", r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const node=()=>({addEventListener(e,fn){this[e]=fn;},focus(){}});
const email=node(),code=node(),recipient=node(),form=node(),verify=node();
const sendButton=node(),verifyButton=node();
form.querySelector=()=>sendButton;verify.querySelector=()=>verifyButton;
const fields=new Map([['#auth-email-input',email],['#auth-email-code',code],
  ['[data-auth-form="email"]',form],['[data-auth-verify="email"]',verify],
  ['[data-auth-recipient]',recipient]]);
const root={querySelectorAll:()=>[],querySelector:k=>fields.get(k)};
const event={preventDefault(){}};
let blockSend, verified;
const fetch=async (path,options)=>{
  if(path==='/api/email-auth/config')return {ok:true,json:async()=>({available:true})};
  const body=JSON.parse(options.body);
  if(path.endsWith('/request')){
    if(body.email==='b@example.com')await new Promise(resolve=>{blockSend=resolve;});
    return {ok:body.email!=='b@example.com',json:async()=>({detail:'EMAIL_LOGIN_COOLDOWN'})};
  }
  assert.equal(path,'/api/email-auth/verify'); verified=body;
  return {ok:true,json:async()=>({authenticated:true,user:{}})};
};
(async()=>{
  vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{document:{getElementById:()=>root},
    window:{location:{search:''},onVainahEmailAuth(){}},fetch,URLSearchParams});
  await new Promise(resolve=>setImmediate(resolve));
  email.value='a@example.com';await form.submit(event);
  code.value='123456';email.value='b@example.com';
  const pending=form.submit(event);await verify.submit(event);
  assert.equal(verified,undefined);blockSend();await pending;
  assert.equal(recipient.textContent,'a@example.com');assert.equal(code.value,'123456');
  await verify.submit(event);
  assert.deepEqual(verified,{email:'a@example.com',code:'123456'});
  code.value='654321';email.value='c@example.com';await form.submit(event);
  assert.equal(code.value,'');assert.equal(recipient.textContent,'c@example.com');
})().catch(error=>{console.error(error);process.exitCode=1;});
""")
