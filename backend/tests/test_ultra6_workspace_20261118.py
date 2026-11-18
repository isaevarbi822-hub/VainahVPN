"""Ultra 6 UI checks. Browser smoke uses a local fixture and never calls a VPN API."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STORE = Path(__file__).resolve().parents[2] / "storefront"


def test_ultra6_is_integrated_into_existing_site_not_checkout_logic():
    shell = (STORE / "site-shell.js").read_text(encoding="utf-8")
    home = (STORE / "index.html").read_text(encoding="utf-8")
    control = (STORE / "command-hub.html").read_text(encoding="utf-8")
    release = (STORE / "whats-new.html").read_text(encoding="utf-8")
    assert "ultra6-workspace.css?v=20261118-u6a" in shell
    assert "ultra6-workspace.js?v=20261118-u6a" in shell
    assert "site-shell.js?v=20261118-ultra6" in home
    assert "site-shell.js?v=20261118-ultra6" in control
    assert 'data-vx6-home-continue' in home
    assert 'data-vx6-home-link' in home
    assert 'data-vx6-pin-home' in home
    for name in (
        'data-vx6-pinned', 'data-vx6-recent', 'data-vx6-history-toggle',
        'data-vx6-clear-history', 'data-vx6-status',
        'data-vx6-preference="contrast"',
        'data-vx6-preference="readable"',
        'data-vx6-preference="motion"',
    ):
        assert name in control
    assert 'id="vx-ultra6-20261118"' in release


def test_ultra6_uses_public_whitelist_and_has_no_data_leak():
    script = (STORE / "ultra6-workspace.js").read_text(encoding="utf-8")
    whitelist = script.split("const allowed = Object.freeze({", 1)[1].split("});", 1)[0]
    assert "'index.html':" in whitelist
    assert "'plans.html':" in whitelist
    for private in (
        "account.html", "checkout.html", "payment-return.html",
        "support-center.html", "operator-pilot.html",
        "gifts.html", "notifications.html", "my-devices.html",
    ):
        assert f"'{private}':" not in whitelist
    for needed in (
        "localStorage.getItem(key)", "localStorage.setItem(key",
        "normalizedList(original.pins,6)",
        "normalizedList(original.recent,5)",
        "state.historyEnabled=false",
    ):
        # Last expression is implemented through inversion and a clear.
        if needed == "state.historyEnabled=false":
            assert "state.historyEnabled=!state.historyEnabled;" in script
            assert "if(!state.historyEnabled)state.recent=[];" in script
        else:
            assert needed in script
    assert "state.recent=[page,...state.recent.filter" in script
    assert "location.pathname.split('/').pop()" in script
    assert "a.href=id;" in script
    assert "textContent" in script
    assert ".innerHTML" not in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "document.cookie" not in script
    assert "sendBeacon" not in script
    assert "localStorage.clear()" not in script
    assert script.count("{") == script.count("}")


def test_ultra6_responsive_and_user_accessibility_preferences():
    css = (STORE / "ultra6-workspace.css").read_text(encoding="utf-8")
    for selector in (
        ".vx6-workspace", ".vx6-grid", ".vx6-home", ".vx6-link",
        ".vx6-link-list", "html.vx6-readable", "html.vx6-contrast",
        "html.vx6-no-motion", "@media(max-width:730px)",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert selector in css
    assert "focus-visible" in css
    assert css.count("{") == css.count("}")
    assert "overflow-x:hidden" not in css.replace(" ", "")


def _fixture() -> str:
    javascript = (STORE / "ultra6-workspace.js").read_text(encoding="utf-8")
    css = (STORE / "ultra6-workspace.css").read_text(encoding="utf-8")
    html = """<!doctype html><html lang="ru"><head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>
    body{margin:0;background:#0b1120;color:#f8f5ff;font:16px/1.5 system-ui}
    main{width:min(1100px,calc(100% - 28px));margin:24px auto}
    </style><style>__STYLE__</style></head>
    <body><main>
      <nav class="vx-breadcrumbs"><a href="index.html">Главная</a>
      <span> / </span> <span>Vainah Control</span></nav>
      <section class="vx6-workspace">
       <div class="vx6-heading"><h2>Рабочий экран</h2>
       <button data-vx6-pin-home aria-pressed="false">☆ Сохранить раздел</button></div>
       <div class="vx6-grid">
        <section class="vx6-card"><h3>Быстрые ссылки</h3>
        <div data-vx6-pinned class="vx6-link-list"></div></section>
        <section class="vx6-card"><h3>Недавние страницы</h3>
        <div data-vx6-recent class="vx6-link-list"></div>
        <button data-vx6-history-toggle></button>
        <button data-vx6-clear-history></button></section>
        <section class="vx6-card vx6-preferences">
        <button data-vx6-preference="contrast" aria-pressed="false">Контраст</button>
        <button data-vx6-preference="readable" aria-pressed="false">Текст</button>
        <button data-vx6-preference="motion" aria-pressed="false">Анимации</button>
        <p data-vx6-status role="status"></p></section>
       </div>
      </section>
    </main>
    <script>
      window.fetch=()=>{throw Error('No network allowed in UI test')};
    </script>
    <script>__SCRIPT__</script>
    <script>
    (() => {
      const pin=document.querySelector('[data-vx6-pin-home]');
      const recent=document.querySelector('[data-vx6-recent]');
      const oldRecent=recent.querySelectorAll('.vx6-link').length>=1;
      pin.click();
      const a=document.querySelector('[data-vx6-pinned] .vx6-pin-item a');
      const pinWorks=Boolean(a&&a.getAttribute('href')==='command-hub.html'&&
        pin.getAttribute('aria-pressed')==='true');
      document.querySelector('[data-vx6-preference="contrast"]').click();
      document.querySelector('[data-vx6-preference="readable"]').click();
      document.querySelector('[data-vx6-preference="motion"]').click();
      const settingsWork=['contrast','readable','no-motion'].every(mode=>
        document.documentElement.classList.contains('vx6-'+mode));
      document.querySelector('[data-vx6-history-toggle]').click();
      const cleared=recent.querySelectorAll('a').length===0 &&
        document.querySelector('[data-vx6-history-toggle]').getAttribute('aria-pressed')==='false';
      document.querySelector('[data-vx6-pinned] .vx6-unpin')?.click();
      const removal=document.querySelectorAll('.vx6-pin-item').length===0;
      const box=document.querySelector('.vx6-workspace').getBoundingClientRect();
      const viewportOK=box.left>=-2 && box.right<=innerWidth+2 &&
        document.documentElement.scrollWidth<=innerWidth+2;
      document.body.dataset.ultra6Smoke=
        oldRecent&&pinWorks&&settingsWork&&cleared&&removal&&viewportOK?'ok':'failed';
      document.body.dataset.ultra6Detail=[
        oldRecent,pinWorks,settingsWork,cleared,removal,viewportOK,
        innerWidth,document.documentElement.scrollWidth,
        Math.round(box.left),Math.round(box.right)
      ].join(',');
    })();
    </script></body></html>"""
    return html.replace("__STYLE__", css).replace("__SCRIPT__", javascript)


@pytest.mark.parametrize(("width", "height"), [(480, 840), (1280, 900)])
def test_ultra6_browser_pin_accessibility_and_mobile_fit(tmp_path, width, height):
    chrome = (shutil.which("chromium") or shutil.which("chromium-browser")
              or shutil.which("google-chrome"))
    if not chrome:
        pytest.skip("Chromium unavailable; static safety checks still run")
    document = tmp_path / "command-hub.html"
    document.write_text(_fixture(), encoding="utf-8")
    result = subprocess.run([
        chrome, "--headless", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage", "--no-first-run",
        "--user-data-dir=" + str(tmp_path / f"chromium-{width}"),
        "--window-size=" + str(width) + "," + str(height),
        "--dump-dom", document.as_uri()
    ], capture_output=True, text=True, timeout=36, check=False)
    assert result.returncode == 0, result.stderr[-900:]
    assert 'data-ultra6-smoke="ok"' in result.stdout, result.stdout[-1900:]


def test_every_public_shell_has_cache_busting():
    for name in ("index", "command-hub", "plans", "devices", "help", "about"):
        page = (STORE / f"{name}.html").read_text(encoding="utf-8")
        assert re.search(r"site-shell\.js\?v=20261118-ultra6", page), name
