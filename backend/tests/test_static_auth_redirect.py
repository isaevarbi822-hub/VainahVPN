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
