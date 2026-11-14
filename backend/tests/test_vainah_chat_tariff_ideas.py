"""Offline regression checks for the refreshed Vainah guide and new concepts."""

from pathlib import Path

STOREFRONT = Path(__file__).resolve().parents[2] / "storefront"


def test_chat_has_safe_local_answers_and_no_secret_submission():
    chat = (STOREFRONT / "ultra-control.js").read_text(encoding="utf-8")
    assert "['chat','Чат Vainah']" in chat
    assert "chatHistory" in chat
    assert "renderChat()" in chat
    assert "addEventListener('submit'" in chat
    assert "maxLength=350" in chat
    assert "role','log'" in chat
    assert "fetch(" not in chat
    assert "/api/shop/checkout" not in chat


def test_chat_and_dashboard_match_violet_theme():
    css = (STOREFRONT / "ultra-control.css").read_text(encoding="utf-8")
    control_css = (STOREFRONT / "command-hub.css").read_text(encoding="utf-8")
    assert "#a98bff" in css
    assert ".vx-chat-message" in css
    assert ".vx-chat-form" in css
    assert "#080b15" in control_css
    assert "#a98bff" in control_css


def test_twelve_new_concepts_cannot_be_purchased():
    page = (STOREFRONT / "plans.html").read_text(encoding="utf-8")
    js = (STOREFRONT / "next-tariffs.js").read_text(encoding="utf-8")
    assert 'id="vx-new-offers"' in page
    assert 'next-tariffs.js?v=20261114-1' in page
    assert js.count("name:'Vainah") == 12
    assert "button.disabled=true" in js
    assert "/api/shop/checkout" not in js
    assert "fetch(" not in js


def test_chat_and_ideas_work_in_core_navigation():
    shell = (STOREFRONT / "site-shell.js").read_text(encoding="utf-8")
    hub = (STOREFRONT / "command-hub.html").read_text(encoding="utf-8")
    assert "ultra-control.js?v=20261114-chat1" in shell
    assert 'id="vx-hub-open-chat"' in hub
    assert 'href="plans.html#vx-new-offers"' in hub
