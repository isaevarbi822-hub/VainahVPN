"""Browser regression for the iPad Safari-style header overflow screenshot.

Uses real page markup + CSS with no requests to payments, accounts or H1Cloud.
Chromium validates responsive layout; Safari hardware still needs manual QA.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[2] / "storefront"


def _fixture() -> str:
    home = (SITE / "index.html").read_text(encoding="utf-8")
    inline = (SITE / "assets/storefront-base.css").read_text(encoding="utf-8")
    inline += home.split("<style>", 1)[1].split("</style>", 1)[0]
    header_start = home.index('<header class="vv-header">')
    header = home[header_start:home.index("</header>", header_start) + len("</header>")]
    hero_start = home.index('<section class="refresh-hero')
    hero = home[hero_start:home.index("</section>", hero_start) + len("</section>")]
    css = "\n".join(
        (SITE / name).read_text(encoding="utf-8")
        for name in (
            "experience.css",
            "site-shell.css",
            "refresh.css",
            "vainah-next.css",
            "site-upgrade.css",
            "responsive-fit.css",
            "interface.css",
        )
    )
    script = r"""
const bar=document.querySelector('.vv-bar');
const brand=bar.querySelector('.vv-brand');
const nav=bar.querySelector('.vv-primary');
const actions=bar.querySelector('.vv-actions');
const menu=actions.querySelector('details');
const toggle=menu.querySelector('summary');
const drawer=menu.querySelector('.vv-drawer');
const rect=el=>el.getBoundingClientRect();
const inside=el=>rect(el).width>0 && rect(el).left>=-1 && rect(el).right<=innerWidth+1;
const separated=rect(brand).right<=rect(actions).left && (innerWidth<=860 ||
  rect(brand).right<=rect(nav).left && rect(nav).right<=rect(actions).left);
const navVisible=(getComputedStyle(nav).display!=='none')===(innerWidth>860);
const heroInside=['.vv-hero h1','.vv-landscape','.vv-hero-actions'].every(sel=>inside(document.querySelector(sel)));
toggle.click();
const opened=menu.open && inside(drawer) && !!drawer.querySelector('a[href="plans.html"]');
toggle.focus();
document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
const closed=!menu.open && document.activeElement===toggle;
const ok=inside(brand)&&inside(actions)&&inside(toggle)&&separated&&navVisible&&heroInside&&opened&&closed;
document.body.dataset.responsiveTest=ok?'ok':'failed';
document.body.dataset.responsiveDetail=[innerWidth,separated,navVisible,heroInside,opened,closed].join(',');
"""
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>' + inline + "\n" + css + '</style></head>'
        '<body data-refresh-home data-vv-interface>' + header + '<main>' + hero + '</main>'
        '<script>' + (SITE / "navigation.js").read_text(encoding="utf-8") + '\n' + script + '</script></body></html>'
    )


def test_responsive_css_has_tablet_cutoff_and_preserves_status():
    css = (SITE / "responsive-fit.css").read_text(encoding="utf-8")
    shell = (SITE / "site-shell.js").read_text(encoding="utf-8")
    status = (SITE / "site-health.js").read_text(encoding="utf-8")
    assert "@media(max-width:1680px)" in css
    assert "@media(max-width:1120px)" in css
    assert "@media(max-width:760px)" in css
    assert "@media(max-width:430px)" in css
    assert "body > header .desktop-nav" in css
    assert "body > header .mobile-nav.open" in css
    assert "body > header .nav-side>a.vainah-login" in css
    assert "responsive-fit.css?v=20261118-ipad2" in shell
    assert "vx-header-collapsed" in shell
    assert "vx-mobile-status" in status
    assert "window.addEventListener('resize'" in shell
    assert css.count("{") == css.count("}")


@pytest.mark.parametrize(("width", "height"), [
    (360, 740), (480, 850), (768, 1024), (1024, 768), (1366, 1024), (1920, 1080),
])
def test_main_header_and_hero_fit_the_viewport(tmp_path, width, height):
    browser = (
        shutil.which("chromium") or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
    )
    if browser is None:
        pytest.skip("Chromium unavailable; manual Safari QA still required")

    page = tmp_path / "responsive.html"
    page.write_text(_fixture(), encoding="utf-8")
    args = [
        browser, "--headless", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage", "--no-first-run",
        "--user-data-dir=" + str(tmp_path / f"chrome-{width}"),
        "--window-size=" + str(width) + "," + str(height),
        "--dump-dom", page.as_uri(),
    ]
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=24, check=False,
    )
    assert result.returncode == 0, result.stderr[-1400:]
    assert 'data-responsive-test="ok"' in result.stdout, (
        result.stdout[-2400:] + result.stderr[-400:]
    )
