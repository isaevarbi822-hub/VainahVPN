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
    inline = home.split("<style>", 1)[1].split("</style>", 1)[0]
    header_start = home.index("<header>")
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
        )
    )
    script = r"""
const bar=document.querySelector('body > header .nav-wrap');
const logo=bar.querySelector('.logo');
const nav=bar.querySelector('.desktop-nav');
const tools=bar.querySelector('.nav-side');
const menu=bar.querySelector('.hamburger');
const drawer=document.querySelector('.mobile-nav');
const center=document.createElement('a');
center.className='vx-control-nav';center.textContent='✦ Центр Vainah';center.href='command-hub.html';
nav.prepend(center);
const trial=document.createElement('a');
trial.className='vx-trial-nav';trial.textContent='Пробный доступ · 0 ₽';trial.href='trial.html';
nav.append(trial);
const search=document.createElement('button');
search.className='vx-header-search';search.textContent='⌕';search.type='button';
tools.insertBefore(search,menu);
const status=document.createElement('button');
status.className='vx-live-trigger';status.type='button';
status.setAttribute('aria-label','Проверка оплаты');
status.innerHTML='<span class="vx-live-dot"></span><span class="vx-live-label">Проверка оплаты</span>';
tools.prepend(status);
const mobile=document.createElement('button');mobile.className='vx-mobile-status';
mobile.textContent='◈ Проверка оплаты';drawer.prepend(mobile);
menu.addEventListener('click',()=>drawer.classList.toggle('open'));
const compact=innerWidth<=1680;
const visible=(el)=>getComputedStyle(el).display!=='none';
const rect=(el)=>el.getBoundingClientRect();
const v=[logo,tools,...tools.children].filter(visible);
const inside=v.every(el=>rect(el).left>=-2&&rect(el).right<=innerWidth+2);
const separated=rect(logo).right<=rect(tools).left+2;
const isCompact=compact ? !visible(nav)&&visible(menu) : visible(nav);
const heroTitle=document.querySelector('.refresh-hero h1');
const heroOrbit=document.querySelector('.refresh-orbit');
const heroInside=rect(heroTitle).right<=innerWidth+2&&rect(heroOrbit).right<=innerWidth+2;
const headlineSize=parseFloat(getComputedStyle(heroTitle).fontSize);
const scaled=compact ? headlineSize<=70 : headlineSize<=90;
if(visible(menu))menu.click();
const menuWorks=!compact || (drawer.classList.contains('open')&&
  getComputedStyle(drawer).display==='grid'&&
  rect(drawer).right<=innerWidth+2&&
  rect(drawer).left>=-2);
document.body.dataset.responsiveTest=
  inside&&separated&&isCompact&&heroInside&&scaled&&menuWorks?'ok':'failed';
document.body.dataset.responsiveDetail=
  [innerWidth,inside,separated,isCompact,heroInside,scaled,menuWorks].join(',');
"""
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>' + inline + "\n" + css + '</style></head>'
        '<body data-refresh-home>' + header + '<main>' + hero + '</main>'
        '<script>' + script + '</script></body></html>'
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
    (480, 850), (1366, 1024), (1920, 1080),
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
