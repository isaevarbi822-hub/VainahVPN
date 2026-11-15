"""Android Google/Telegram PKCE handoff. Synthetic provider tokens only."""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient

from vainah import google_auth, mobile_auth, telegram_oidc
from vainah.main import app

ORIGIN = "https://vainahvpn-python-preview.onrender.com"


@pytest.fixture
def configured(monkeypatch, postgres_url):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", ORIGIN)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "mobile-only-test-secret-" + "x" * 48)
    monkeypatch.setenv(
        "GOOGLE_CLIENT_ID", "123456789-test.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "fake-google-secret")
    monkeypatch.setenv("TELEGRAM_OIDC_CLIENT_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_OIDC_CLIENT_SECRET", "fake-telegram-secret-12345")
    return postgres_url


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()


def begin(client: TestClient, provider: str, verifier: str):
    reply = client.post("/api/mobile-auth/start",
        headers={"Origin": ORIGIN},
        json={"provider": provider, "code_challenge": challenge(verifier)})
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert len(data["flow"]) == 36
    assert data["authorize_url"] == (
        ORIGIN + ("/api/google/start" if provider == "google"
                  else "/api/telegram-oidc/start") +
        "?mobile_flow=" + data["flow"]
    )
    return data


class FakeTokenResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"id_token": "opaque-test-id-token"}


class FakeGoogle:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, *args, **kwargs):
        return FakeTokenResponse()


class FakeTelegram(FakeGoogle):
    pass


def test_android_google_flow_sets_no_browser_cookie_and_is_single_use(
    configured, monkeypatch,
):
    verifier = "g" * 43
    async def verified(*args):
        return "verified@example.org"
    monkeypatch.setattr(google_auth, "_verified_email", verified)
    monkeypatch.setattr(google_auth.httpx, "AsyncClient", FakeGoogle)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/mobile-auth/config").json() == {
            "google": True, "telegram": True, "pkce": True, "enabled": True,
        }
        flow = begin(client, "google", verifier)
        start = client.get(flow["authorize_url"], follow_redirects=False)
        assert start.status_code == 302
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        assert google_auth._unpack_flow(start.cookies[google_auth.STATE_COOKIE])[
            "mobile_flow"
        ] == flow["flow"]
        done = client.get("/api/google/callback",
            params={"state": state, "code": "provider-authorization-code"},
            follow_redirects=False)
        assert done.status_code == 303
        redirect = urlsplit(done.headers["location"])
        assert redirect.scheme == "vainahvpn" and redirect.netloc == "oauth"
        callback = parse_qs(redirect.query)
        assert callback["flow"] == [flow["flow"]]
        assert client.get("/api/email-auth/account").json()["authenticated"] is False
        payload = {"flow": flow["flow"], "code": callback["code"][0],
                   "verifier": verifier}
        wrong = client.post("/api/mobile-auth/exchange",
            json={**payload, "verifier": "w" * 43}, headers={"Origin": ORIGIN})
        assert wrong.status_code == 400
        exchanged = client.post("/api/mobile-auth/exchange",
            json=payload, headers={"Origin": ORIGIN})
        assert exchanged.status_code == 200
        info = exchanged.json()
        assert info["authenticated"] is True
        assert info["cookie_name"] == "__Host-vainah_email_session"
        assert info["session"] not in done.headers["location"]
        assert client.post("/api/mobile-auth/exchange", json=payload,
            headers={"Origin": ORIGIN}).status_code == 400
        client.cookies.set(info["cookie_name"], info["session"])
        assert client.get("/api/email-auth/account").json()["user"]["email"] == (
            "verified@example.org"
        )


def test_android_telegram_flow_issues_only_verified_telegram_session(
    configured, monkeypatch,
):
    verifier = "t" * 43
    async def verified(*args):
        return {
            "telegram_id": "987654321", "username": "trialtester",
            "first_name": "Test",
        }
    monkeypatch.setattr(telegram_oidc, "_verified_user", verified)
    monkeypatch.setattr(telegram_oidc.httpx, "AsyncClient", FakeTelegram)
    with TestClient(app, base_url=ORIGIN) as client:
        flow = begin(client, "telegram", verifier)
        start = client.get(flow["authorize_url"], follow_redirects=False)
        assert start.status_code == 302
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        assert telegram_oidc._read_flow(
            start.cookies[telegram_oidc.FLOW_COOKIE])["mobile_flow"] == flow["flow"]
        done = client.get("/api/telegram-oidc/callback",
            params={"state": state, "code": "telegram-provider-code"},
            follow_redirects=False)
        assert done.status_code == 303
        uri = urlsplit(done.headers["location"])
        assert uri.scheme == "vainahvpn" and uri.netloc == "oauth"
        payload = {"flow": flow["flow"],
                   "code": parse_qs(uri.query)["code"][0],
                   "verifier": verifier}
        exchanged = client.post("/api/mobile-auth/exchange",
            json=payload, headers={"Origin": ORIGIN})
        assert exchanged.status_code == 200
        data = exchanged.json()
        assert data["cookie_name"] == "__Host-vainah_session"
        assert client.get("/api/telegram/account").json()["authenticated"] is False
        client.cookies.set(data["cookie_name"], data["session"])
        assert client.get("/api/telegram/account").json()["user"][
            "telegram_id"] == "987654321"
        assert client.get("/api/email-auth/account").json()["authenticated"] is False
        assert client.post("/api/mobile-auth/exchange",
            json=payload, headers={"Origin": ORIGIN}).status_code == 400


def test_expired_flow_and_other_provider_cannot_complete(configured):
    verifier = "k" * 43
    with TestClient(app, base_url=ORIGIN) as client:
        flow = begin(client, "google", verifier)
        assert not mobile_auth.pending(flow["flow"], "telegram")
        assert mobile_auth.complete(flow["flow"], "telegram",
            telegram_user={"telegram_id": "1"}) is None
        with psycopg.connect(configured) as conn:
            conn.execute("""
                UPDATE vainah_mobile_auth
                SET expires_at=now() - interval '1 minute'
                WHERE flow_id=%s
            """, (flow["flow"],))
        assert not mobile_auth.pending(flow["flow"], "google")
        assert mobile_auth.complete(flow["flow"], "google",
            email="nope@example.org") is None


def test_request_rejects_bad_origin_and_invalid_pkce(configured):
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post("/api/mobile-auth/start", json={
            "provider": "google", "code_challenge": "x" * 43,
        }).status_code == 403
        assert client.post("/api/mobile-auth/start",
            headers={"Origin": "https://evil.example.org"},
            json={"provider": "google",
                  "code_challenge": "x" * 43}).status_code == 403
        assert client.post("/api/mobile-auth/start",
            headers={"Origin": ORIGIN},
            json={"provider": "google", "code_challenge": "invalid"}
        ).status_code == 422
        assert client.post("/api/mobile-auth/exchange",
            headers={"Origin": ORIGIN},
            json={"flow": "unknown", "code": "x" * 43,
                  "verifier": "x" * 43}).status_code in (400, 422)


def test_native_api_host_stays_active_when_storefront_origin_is_static(
    configured, monkeypatch,
):
    # Render serves the storefront and the Python OAuth API at DISTINCT
    # origins; provider callbacks must NEVER land on a static HTML site.
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", "https://vainahvpn.onrender.com")
    assert google_auth._origin() == ORIGIN
    assert telegram_oidc._config()[2] == ORIGIN
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/mobile-auth/config").json()["enabled"] is True
        for origin in (ORIGIN, "https://vainahvpn.onrender.com"):
            response = client.post(
                "/api/mobile-auth/start",
                headers={"Origin": origin},
                json={"provider": "google", "code_challenge": challenge("x" * 43)},
            )
            assert response.status_code == 200, response.text
            assert response.json()["authorize_url"].startswith(
                ORIGIN + "/api/google/start?mobile_flow="
            )
        for invalid in ("http://vainahvpn.onrender.com",
                        "https://evil.example.org",
                        "https://vainahvpn.onrender.com.evil.org"):
            response = client.post(
                "/api/mobile-auth/start",
                headers={"Origin": invalid},
                json={"provider": "telegram", "code_challenge": challenge("x" * 43)},
            )
            assert response.status_code == 403
