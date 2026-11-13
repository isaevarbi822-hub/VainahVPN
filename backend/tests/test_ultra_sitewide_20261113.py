"""Site-wide Ultra improvements: real links, local search and safe device setup.

These checks do not create payments or subscriptions and do not use secrets.
"""
from __future__ import annotations

from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_all_shared_pages_use_the_new_assets():
    pages = [p for p in SITE.glob("*.html") if "refresh.css" in p.read_text(encoding="utf-8")]
    assert len(pages) >= 48
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert 'refresh.css?v=20261113-ultra3' in html, page.name
        if 'src="site-shell.js' in html:
            assert 'site-shell.js?v=20261113-ultra3' in html, page.name
    connect_page = (SITE / "connect.html").read_text(encoding="utf-8")
    assert 'connect.js?v=20261113-device3' in connect_page


def test_home_device_links_reach_safe_preselected_guides():
    home = (SITE / "index.html").read_text(encoding="utf-8")
    guide = (SITE / "connect.js").read_text(encoding="utf-8")
    for platform in ("android", "ios", "windows", "macos", "linux"):
        assert f'href="connect.html?device={platform}"' in home
        assert f"    {platform}:{{" in guide
    assert "new URLSearchParams(window.location.search).get('device')" in guide
    assert "Object.hasOwn(flows,requested)" in guide
    assert "ArrowRight" in guide and "ArrowLeft" in guide
    assert "fetch(" not in guide


def test_global_navigation_is_keyboard_accessible_and_read_only():
    shell = (SITE / "site-shell.js").read_text(encoding="utf-8")
    assert "vx-header-search" in shell
    assert "vx-mobile-search" in shell
    assert "ArrowDown" in shell and "ArrowUp" in shell
    assert "key.toLowerCase()==='k'" in shell
    assert "event.key==='/'" in shell
    assert "vx-breadcrumbs" in shell
    assert "vx-back-to-top" in shell
    assert "prefers-reduced-motion: reduce" in shell
    assert "fetch(" not in shell
    assert "localStorage" not in shell
    assert "sessionStorage" not in shell


def test_universal_ui_respects_accessibility_and_responsive_layouts():
    css = (SITE / "refresh.css").read_text(encoding="utf-8")
    for expected in ("Vainah Ultra: discoverable navigation",
                     ".refresh-device-choices", ".vx-finder-result",
                     ".vx-back-to-top", "max-width:420px",
                     "max-width:360px", "pointer:coarse",
                     "prefers-reduced-motion:reduce"):
        assert expected in css
    assert css.count("{") == css.count("}")


def test_release_notes_distinguish_website_work_from_vpn_payment_system():
    release = (SITE / "whats-new.html").read_text(encoding="utf-8")
    assert "13 НОЯБРЯ 2026" in release
    assert "Реальные платежи, существующие подписки, RollyPay, H1Cloud" in release
    assert "index.html#choose-device" in release
