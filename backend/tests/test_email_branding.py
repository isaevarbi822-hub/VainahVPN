"""Branded, accessible Vainah email delivery without sending real email."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from vainah import email_delivery
from vainah.email_design import (
    BRAND_IMAGE,
    plaintext_version,
    render_email,
    reply_to_identity,
    sender_identity,
)
from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_public_avatar_exists_and_is_a_small_real_png():
    icon = SITE / "email-avatar.png"
    data = icon.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert 1024 < len(data) < 40000
    with TestClient(app) as client:
        result = client.get("/email-avatar.png")
        assert result.status_code == 200
        assert result.headers["content-type"].startswith("image/png")
        assert result.content == data


def test_email_html_is_mobileresponsive_and_contains_branding_not_tracker():
    markup = render_email(
        "Vainah VPN — подписка выдана",
        "<p>VPN активирован на 3 устройства.</p>",
    )
    assert "<!doctype html>" in markup
    assert 'lang="ru"' in markup
    assert 'name="viewport"' in markup
    assert "width:100%;max-width:580px" in markup
    assert "VAINAH" in markup
    assert "Твоё соединение. Твои правила." in markup
    assert BRAND_IMAGE in markup
    assert "Открыть личный кабинет" in markup
    assert "VPN активирован на 3 устройства." in markup
    assert 'role="presentation"' in markup
    assert "<script" not in markup
    assert "tracking." not in markup


def test_text_fallback_includes_code_and_support_link_without_html_tags():
    body = (
        '<p>Код подтверждения: <b>123456</b></p>'
        '<p><a href="https://vainahvpn-python-preview.onrender.com/support-center.html">'
        "Прочитать ответ поддержки</a></p>"
    )
    content = plaintext_version(body)
    assert "123456" in content
    assert "<b>" not in content
    assert "https://vainahvpn-python-preview.onrender.com/support-center.html" in content
    assert "Vainah VPN" in content


def test_sender_rebranding_does_not_change_verified_mailbox(monkeypatch):
    monkeypatch.delenv("VAINAH_EMAIL_SENDER_NAME", raising=False)
    assert sender_identity(
        "Old label <noreply@verified.example>"
    ) == "Vainah VPN <noreply@verified.example>"
    assert sender_identity(
        "hello@verified.example"
    ) == "Vainah VPN <hello@verified.example>"
    monkeypatch.setenv("VAINAH_EMAIL_SENDER_NAME", "Vainah VPN Support")
    assert sender_identity("hello@verified.example") == (
        "Vainah VPN Support <hello@verified.example>"
    )
    monkeypatch.setenv("VAINAH_EMAIL_SENDER_NAME", "Bad\nInjected")
    assert sender_identity("hello@verified.example") == (
        "Vainah VPN <hello@verified.example>"
    )


def test_invalid_sender_and_reply_to_are_not_marked_ready(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_example_test_valid_key_123")
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "Vainah VPN <hello@verified.example>")
    monkeypatch.delenv("VAINAH_EMAIL_REPLY_TO", raising=False)
    assert email_delivery.email_service_ready()
    monkeypatch.setenv("VAINAH_EMAIL_REPLY_TO", "invalid\r\nBcc: attacker@example.com")
    assert email_delivery.email_service_ready() is False
    monkeypatch.setenv("VAINAH_EMAIL_REPLY_TO", "team@verified.example")
    assert reply_to_identity() == "team@verified.example"
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "No mailbox")
    assert email_delivery.email_service_ready() is False


def test_resend_receives_html_plaintext_sender_name_and_reply_to(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_example_test_valid_key_123")
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "Old label <hello@verified.example>")
    monkeypatch.setenv("VAINAH_EMAIL_REPLY_TO", "help@verified.example")
    monkeypatch.delenv("VAINAH_EMAIL_SENDER_NAME", raising=False)
    sent = []

    def handler(request: httpx.Request):
        assert request.method == "POST"
        assert request.url.host == "api.resend.com"
        assert request.headers["Idempotency-Key"] == "brand-test/first"
        payload = json.loads(request.content)
        sent.append(payload)
        return httpx.Response(200, json={"id": "test_email_id"})

    asyncio.run(email_delivery.send_email(
        "customer@example.com",
        "Vainah VPN — уведомление",
        "<p>Твоя ссылка: <a href=\"https://example.com/personal?x=1&amp;y=2\">"
        "Открыть подписку</a></p>",
        idempotency_key="brand-test/first",
        transport=httpx.MockTransport(handler),
    ))
    assert len(sent) == 1
    payload = sent[0]
    assert payload["from"] == "Vainah VPN <hello@verified.example>"
    assert payload["reply_to"] == "help@verified.example"
    assert payload["to"] == ["customer@example.com"]
    assert payload["subject"] == "Vainah VPN — уведомление"
    assert BRAND_IMAGE in payload["html"]
    assert "personal?x=1&amp;y=2" in payload["html"]
    assert "https://example.com/personal?x=1&y=2" in payload["text"]
    assert "<p>" not in payload["text"]


def test_otp_design_keeps_code_only_in_body_not_subject_or_preheader(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_example_test_valid_key_123")
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "hello@verified.example")
    monkeypatch.delenv("VAINAH_EMAIL_REPLY_TO", raising=False)
    sent = []

    def handler(request: httpx.Request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "test_otp_id"})

    asyncio.run(email_delivery.send_verification_code(
        "owner@example.com", "592714",
        transport=httpx.MockTransport(handler),
    ))
    assert len(sent) == 1
    payload = sent[0]
    assert "592714" in payload["text"]
    assert "592714" in payload["html"]
    assert "592714" not in payload["subject"]
    assert 'background:#f0f3ff' in payload["html"]
    assert "10 минут" in payload["text"]
    assert "reply_to" not in payload
