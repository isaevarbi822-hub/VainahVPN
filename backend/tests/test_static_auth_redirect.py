"""Static-site API pages must redirect to the same-origin Python backend.

These checks never contact payment providers or access account credentials.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "storefront"
PAGES = ["trial.html","my-devices.html","notifications.html","gifts.html","referrals.html","rewards.html","handoff.html","operator-grants.html","operator-pilot.html","operations.html","support-operator.html"]


def test_every_private_page_loads_backend_redirect_first():
    for name in PAGES:
        content = (ROOT / name).read_text(encoding="utf-8")
        head = content.split("<head", 1)[1]
        assert 'src="/static-auth-redirect.js?v=20261119-audit"' in head
        assert content.index('src="/static-auth-redirect.js') < content.index("</head>")


def test_redirect_preserves_valid_query_and_fragment_without_open_redirect():
    js = ROOT / "static-auth-redirect.js"
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const redirect=require('node:path').resolve(process.argv[1]);
const code=fs.readFileSync(redirect,'utf8');
const cases=[
 ['https://vainahvpn.onrender.com','/trial.html','?client=incy','#token',
  'https://vainahvpn-python-preview.onrender.com/trial.html?client=incy#token'],
 ['https://vainahvpn.onrender.com','/operator-grants.html','','',
  'https://vainahvpn-python-preview.onrender.com/operator-grants.html'],
 ['https://vainahvpn.onrender.com','/account.html','?client=incy','#subscription',
  'https://vainahvpn-python-preview.onrender.com/account.html?client=incy#subscription'],
 ['https://vainahvpn-python-preview.onrender.com','/trial.html','','',null],
 ['https://vainahvpn.onrender.com','/index.html','','',null],
 ['https://attacker.example','/trial.html','','',null]
];
for(const [origin,pathname,search,hash,expected] of cases){
 let actual=null;
 global.window={location:{origin,pathname,search,hash,replace(url){actual=url;}}};
 vm.runInThisContext(code);
 assert.equal(actual,expected);
}
""";
    r = subprocess.run(
        ["node", "-e", harness, str(js)],
        capture_output=True, text=True, timeout=12, check=False,
    )
    assert r.returncode == 0, r.stderr


def test_custom_domain_redirects_only_if_it_is_the_static_host():
    js = ROOT / "static-auth-redirect.js"
    harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 for(const backend of [false,true]){
  let actual=null;
  global.window={location:{origin:'https://vainahvpn.online',
    pathname:'/operator-grants.html',search:'?id=1',hash:'#details',
    replace(url){actual=url;}}};
  global.fetch=async()=>({ok:backend,headers:{get:()=>backend?'application/json':'text/html'},
    json:async()=>({service:'vainahvpn-api'})});
  vm.runInThisContext(source);
  await tick();
  assert.equal(actual,backend?null:
    'https://vainahvpn-python-preview.onrender.com/operator-grants.html?id=1#details');
 }
})().catch(e=>{console.error(e);process.exitCode=1});
""";
    r = subprocess.run(
        ["node", "-e", harness, str(js)],
        capture_output=True, text=True, timeout=12, check=False,
    )
    assert r.returncode == 0, r.stderr


def test_shared_shell_delegates_read_only_probe_to_small_module():
    shell = (ROOT / "site-shell.js").read_text(encoding="utf-8")
    probe = (ROOT / "custom-origin-probe.mjs").read_text(encoding="utf-8")
    assert "import('./custom-origin-probe.mjs')" in shell
    assert "fetch(" not in shell
    assert "credentials:'omit'" in probe
    assert "method:'GET'" in probe
    assert "method:'POST'" not in probe


def test_account_page_redirects_before_loading_login_and_keeps_query():
    html = (ROOT / "account.html").read_text(encoding="utf-8")
    assert 'src="/static-auth-redirect.js?v=20261119-stay-login1"' in html
    assert html.index('src="/static-auth-redirect.js') < html.index('src="account-dashboard.js')
    assert "После входа" in html
    assert "до 30 дней" in html


def test_dashboard_does_not_treat_network_failure_as_logout():
    js = (ROOT / "account-dashboard.js").read_text(encoding="utf-8")
    assert "let verificationUnavailable=false;" in js
    assert "if(verificationUnavailable){" in js
    assert "if(restoringSession||user)return;" in js
    assert "if(sessionEpoch===session)showSession(null);" in js
    assert js.index("await api('/api/email-auth/logout'") < js.index(
        "if(sessionEpoch===session)showSession(null);"
    )
