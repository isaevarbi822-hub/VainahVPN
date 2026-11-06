"""Customer feedback is validated, owner-bound and operator-gated."""
from fastapi.testclient import TestClient
from vainah import email_auth, support_rating
from vainah.main import app

ORIGIN="https://vainahvpn-python-preview.onrender.com"
SECRET="rating-test-session-secret-at-least-32-characters"
OPERATOR="rating-test-operator-secret-at-least-forty-characters-long"


def client(email=None):
    c=TestClient(app, base_url=ORIGIN)
    if email:
        c.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                      email_auth._sign_session(email))
    return c


def test_rating_login_origin_and_valid_bounds(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("VAINAH_SUPPORT_OPERATOR_KEY", OPERATOR)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    seen=[]
    monkeypatch.setattr(support_rating, "_save",
                        lambda owner, tid, rating: seen.append((owner,tid,rating)))
    path="/api/support/tickets/"+"t"*24+"/rating"
    with client() as guest:
        assert guest.post(path, headers={"Origin":ORIGIN}, json={"rating":5}).status_code==401
    with client("member@example.com") as member:
        assert member.post(path,json={"rating":5}).status_code==403
        for bad in (0,6,-1):
            assert member.post(path,headers={"Origin":ORIGIN},
                               json={"rating":bad}).status_code==422
        good=member.post(path,headers={"Origin":ORIGIN},json={"rating":5})
        assert good.status_code==200
        assert good.json()=={"saved":True,"rating":5}
        assert len(seen)==1 and len(seen[0][0])==64


def test_operator_rating_requires_key(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("VAINAH_SUPPORT_OPERATOR_KEY", OPERATOR)
    monkeypatch.setattr(support_rating, "_read", lambda owner, tid: 4)
    path="/api/support/operator/tickets/"+"r"*24+"/rating"
    with client("member@example.com") as member:
        assert member.get(path).status_code==403
        assert member.get(path,headers={"X-Vainah-Support-Key":OPERATOR}).json()=={"rating":4}


def test_rating_ui_has_no_unsafe_html():
    from pathlib import Path
    folder=Path(__file__).resolve().parents[2]/"storefront"
    for name in ("support-center.js","support-operator.js"):
        content=(folder/name).read_text(encoding="utf-8")
        assert "/rating" in content
        assert "innerHTML" not in content
        assert "localStorage" not in content
