"""The new subscriptions and introduction must be served by the real app."""
from pathlib import Path

from fastapi.testclient import TestClient

from vainah.billing import CATALOG, get_plan
from vainah.expanded_tariffs import REFRESH_CATALOG
from vainah.main import app

SITE = Path(__file__).resolve().parents[2] / "storefront"


def test_refresh_adds_twenty_five_distinct_personal_and_family_options():
    assert len(REFRESH_CATALOG) == 25
    assert sum(p["devices"] == 3 for p in REFRESH_CATALOG) == 15
    assert sum(p["devices"] == 6 for p in REFRESH_CATALOG) == 10
    assert len({(p["days"], p["devices"]) for p in CATALOG}) == 75
    with TestClient(app) as client:
        public = client.get("/api/site/tariffs").json()
        prices = {p["id"]: p for p in client.get("/api/shop/plans").json()["items"]}
    assert public["total"] == 76
    assert public["existing_paid_count"] == 75
    assert public["trial_count"] == 1
    for plan in REFRESH_CATALOG:
        card = next(p for p in public["plans"] if p["id"] == plan["id"])
        assert get_plan(plan["id"]) == plan
        assert prices[plan["id"]]["kopeks"] == plan["kopeks"]
        assert card["days"] == plan["days"]
        assert card["devices"] == plan["devices"]
        assert card["price_rub"] == prices[plan["id"]]["priceRub"]
        assert card["checkout_path"] == "/checkout.html?plan=" + plan["id"]


def test_intro_video_supports_mobile_streaming_and_russian_captions():
    with TestClient(app) as client:
        clip = client.get("/assets/video/vainah-orbit-30.mp4", headers={"Range": "bytes=0-63"})
        assert clip.status_code == 206
        assert clip.headers["content-type"] == "video/mp4"
        assert clip.headers["accept-ranges"] == "bytes"
        assert b"ftyp" in clip.content
        poster = client.get("/assets/video/vainah-orbit-30-poster.jpg")
        assert poster.status_code == 200
        assert poster.headers["content-type"] == "image/jpeg"
        captions = client.get("/assets/video/vainah-orbit-30-ru.vtt")
        assert captions.status_code == 200
        assert captions.text.startswith("WEBVTT")
        assert captions.text.count(" --> ") == 6
        assert "00:00:30.000" in captions.text
    home = (SITE / "index.html").read_text()
    assert 'controls playsinline preload="none"' in home
    assert '<track kind="captions"' in home
    assert "autoplay" not in home
