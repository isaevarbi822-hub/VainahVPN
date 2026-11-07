"""Support followups stay owner-bound, private and secret-free."""
from fastapi.testclient import TestClient

from vainah import email_auth, support_thread
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"
SIGN = "support-thread-test-signing-key-1234567890123456789"
OP = "support-thread-operator-key-123456789012345678901"


def _client(email=None):
    client = TestClient(app, base_url=ORIGIN)
    if email:
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE,
                           email_auth._sign_session(email))
    return client


def test_followup_requires_owner_and_origin(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGN)
    monkeypatch.setenv("VAINAH_SUPPORT_OPERATOR_KEY", OP)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    identifier = "k" * 24
    seen = []
    def followup(owner, ticket_id, message):
        seen.append((owner, ticket_id, message))
    monkeypatch.setattr(support_thread, "_followup", followup)
    path = "/api/support/tickets/" + identifier + "/messages"
    with _client() as guest:
        assert guest.post(path, headers={"Origin": ORIGIN},
                          json={"message": "Any question"}).status_code == 401
    with _client("alice@example.com") as member:
        assert member.post(path, json={"message": "Any question"}).status_code == 403
        assert member.post(path, headers={"Origin": ORIGIN},
                           json={"message": "vless://PRIVATE"}).status_code == 422
        assert member.post(path, headers={"Origin": ORIGIN},
                           json={"message": "https://example.org"}).status_code == 422
        ok=member.post(path, headers={"Origin": ORIGIN},
                       json={"message": "Можно уточнить причину ошибки?"})
        assert ok.status_code == 201
        assert ok.json() == {"saved": True, "status": "open"}
    assert len(seen) == 1 and len(seen[0][0]) == 64
    assert "alice@" not in str(seen)
    assert seen[0][1] == identifier


def test_operator_history_requires_separate_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGN)
    monkeypatch.setenv("VAINAH_SUPPORT_OPERATOR_KEY", OP)
    monkeypatch.setattr(support_thread, "_history",
                        lambda identifier, owner: [{"sender": "operator", "message": "OK"}])
    path = "/api/support/operator/tickets/" + "z"*24 + "/messages"
    with _client("alice@example.com") as member:
        assert member.get(path).status_code == 403
        result=member.get(path, headers={"X-Vainah-Support-Key": OP})
        assert result.status_code == 200
        assert result.json()["items"][0]["sender"] == "operator"


def test_conversation_views_only_use_safe_dom_text():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "storefront"
    for name in ("support-center.js", "support-operator.js"):
        script = (root / name).read_text(encoding="utf-8")
        assert "/messages" in script
        assert "textContent" in script
        assert "innerHTML" not in script
        assert "localStorage" not in script
