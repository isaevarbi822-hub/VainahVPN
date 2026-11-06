"""Regression tests for optimized Speed Lab and private browser checks."""
from pathlib import Path

from fastapi.testclient import TestClient
from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_eco_speed_mode_limits_usage_without_changing_backend_limits():
    html = (SITE / "speed.html").read_text(encoding="utf-8")
    js = (SITE / "speed-test.js").read_text(encoding="utf-8")
    assert 'name="speed-mode" value="eco" checked' in html
    assert 'name="speed-mode" value="normal"' in html
    assert "pings:3,downloads:1,uploads:1,uploadBytes:128*1024" in js
    assert "pings:5,downloads:3,uploads:2,uploadBytes:256*1024" in js
    assert "config.downloads,512*1024" in js
    assert "config.uploads,config.uploadBytes" in js
    assert "options.disabled=true" in js
    assert "options.disabled=false" in js
    assert "previous.mode===latest.mode" in js


def test_browser_check_is_local_and_explicitly_triggered():
    with TestClient(app) as client:
        html = client.get("/browser-check.html")
        script = client.get("/browser-check.js")
        assert html.status_code == 200
        assert script.status_code == 200
        assert 'id="browser-run"' in html.text
        assert 'src="browser-check.js"' in html.text
        assert "addEventListener('click'" in script.text
        assert "fetch(" not in script.text
        assert "localStorage" not in script.text
        assert "sessionStorage" not in script.text
        assert "HTMLDialogElement" in script.text


def test_new_tool_is_findable_and_public():
    shell = (SITE / "site-shell.js").read_text(encoding="utf-8")
    catalog = (SITE / "tools.html").read_text(encoding="utf-8")
    sitemap = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    assert "['browser-check.html','Проверка браузера'" in shell
    assert 'href="browser-check.html"' in catalog
    assert '/browser-check.html' in sitemap
