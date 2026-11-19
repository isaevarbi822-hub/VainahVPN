"""Single-use QR transfer requires verified paid account and a matching owner."""
from __future__ import annotations

from fastapi.testclient import TestClient

from vainah import email_auth, qr_handoff
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SECRET = "qr-handoff-test-signing-key-987654321012345678901"


def client(email=None):
    c = TestClient(app, base_url=ORIGIN)
    if email:
        c.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                      email_auth._sign_session(email))
    return c


def test_handoff_requires_paid_owner_and_same_origin(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    async def paid(_request):
        return {"subscription_url": "https://subscription.example.test/private-key"}
    monkeypatch.setattr(qr_handoff, "access", paid)
    monkeypatch.setattr(qr_handoff, "_issue", lambda owner: "A" * 32)
    with client() as guest:
        assert guest.post("/api/account/handoff/qr",
                          headers={"Origin": ORIGIN}).status_code == 401
    with client("alice@example.com") as owner:
        assert owner.post("/api/account/handoff/qr").status_code == 403
        response = owner.post("/api/account/handoff/qr",
                              headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert "image/svg+xml" in response.headers["content-type"]
        assert "no-store" in response.headers["cache-control"]
        assert b"private-key" not in response.content
        assert b"vless://" not in response.content


def test_redemption_checks_same_account_and_consumes_once(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    async def paid(_request):
        return {"subscription_url": "https://subscription.example.test/private-key"}
    monkeypatch.setattr(qr_handoff, "access", paid)
    saved_owner = qr_handoff._owner("alice@example.com")
    consumed = set()
    def use(owner, token):
        if owner != saved_owner or token in consumed:
            return False
        consumed.add(token)
        return True
    monkeypatch.setattr(qr_handoff, "_consume", use)
    url = "/api/account/handoff/redeem"
    with client("bob@example.com") as bob:
        response = bob.post(url, headers={"Origin": ORIGIN},
                            json={"token": "A" * 32})
        assert response.status_code == 404
    with client("alice@example.com") as alice:
        data = alice.post(url, headers={"Origin": ORIGIN},
                          json={"token": "A" * 32})
        assert data.status_code == 200
        assert data.json()["redeemed"] is True
        assert "private-key" in data.json()["subscription_url"]
        assert alice.post(url, headers={"Origin": ORIGIN},
                          json={"token": "A" * 32}).status_code == 404


def test_token_that_expires_mid_transaction_is_rejected(monkeypatch, postgres_url):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    owner = "a" * 64
    token = qr_handoff._issue(owner)
    schema = qr_handoff._schema

    def expire_during_request(cur):
        schema(cur)
        cur.execute("""
            UPDATE vainah_qr_handoffs SET expires_at=now()+interval '100 milliseconds'
            WHERE token_hash=%s
        """, (qr_handoff._digest(token),))
        cur.execute("SELECT pg_sleep(0.2)")

    monkeypatch.setattr(qr_handoff, "_schema", expire_during_request)
    assert qr_handoff._consume(owner, token) is False
    monkeypatch.setattr(qr_handoff, "_schema", schema)
    assert qr_handoff._consume(owner, token) is False


def test_invalid_qr_origin_preserves_issuance_quota(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SECRET)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", "https://[invalid")
    monkeypatch.setattr(qr_handoff, "require_same_origin", lambda request: None)

    def forbidden(_owner):
        raise AssertionError("Invalid QR destination must be rejected before issuing a token")

    monkeypatch.setattr(qr_handoff, "_issue", forbidden)
    with client("alice@example.com") as owner:
        response = owner.post("/api/account/handoff/qr", headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert response.json()["detail"] == "HANDOFF_PUBLIC_ORIGIN_INVALID"


def test_handoff_never_logs_token_in_path_and_removes_fragment():
    from pathlib import Path
    site = Path(__file__).resolve().parents[2] / "storefront"
    page = (site / "handoff.html").read_text(encoding="utf-8")
    script = (site / "handoff.js").read_text(encoding="utf-8")
    creator = (site / "handoff-creator.js").read_text(encoding="utf-8")
    assert 'name="referrer" content="no-referrer"' in page
    assert "history.replaceState(null,'',location.pathname)" in script
    assert "POST" in script and "/api/account/handoff/redeem" in script
    assert "innerHTML" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "POST" in creator and "/api/account/handoff/qr" in creator
