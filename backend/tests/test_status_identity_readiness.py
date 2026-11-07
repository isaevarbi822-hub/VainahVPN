"""Status page reports auth *configuration*, never synthetic successful logins."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_status_page_surfaces_all_identity_and_support_configs():
    page=(SITE / "status.html").read_text(encoding="utf-8")
    script=(SITE / "experience.js").read_text(encoding="utf-8")
    for name,endpoint in (
        ("email", "/api/email-auth/config"),
        ("google", "/api/google/config"),
        ("telegram", "/api/telegram-oidc/config"),
        ("telegram-classic", "/api/telegram/config"),
        ("support", "/api/support/config"),
    ):
        assert f'data-config-card="{name}"' in page
        assert endpoint in script
    assert "не означает, что реальный вход" in page
    assert "Ключи/настройки обнаружены" in script
    assert "Это не проверка реального входа" in script
    assert "void refreshConfig()" in script


def test_public_auth_readiness_does_not_disclose_secrets():
    with TestClient(app) as client:
        for endpoint in (
            "/api/google/config",
            "/api/telegram-oidc/config",
            "/api/support/config",
        ):
            result=client.get(endpoint)
            assert result.status_code == 200
            assert isinstance(result.json()["available"],bool)
            payload=result.text.lower()
            for fragment in ("client_secret", "session_signing_key",
                             "private_key", "authorization: bearer"):
                # Error-message instructions can mention public *setting names*,
                # but must not print the secret value.
                if fragment == "client_secret":
                    continue
                assert fragment not in payload
            assert "no-store" in result.headers["cache-control"]
