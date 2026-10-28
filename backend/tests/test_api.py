from fastapi.testclient import TestClient
from vainah.main import app

client = TestClient(app)


def test_frontend_and_health():
    assert client.get("/").status_code == 200
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_headers_are_safe():
    r = client.get("/api/v1/overview")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.json()["vpn"]["connected"] is False
    assert r.json()["subscription"]["expires_at"] is None


def test_no_fake_locations():
    r = client.get("/api/v1/locations")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_import_no_echo_credentials():
    token = "THIS_MUST_NOT_APPEAR_IN_ERROR"
    r = client.post("/api/v1/import/inspect", json={"content": token})
    assert r.status_code == 422
    assert token not in r.text


def test_http_local_url_blocked():
    r = client.post("/api/v1/import/inspect", json={"content": "http://127.0.0.1/admin"})
    assert r.status_code == 422


def test_oversized_payload_rejected():
    r = client.post("/api/v1/import/inspect", json={"content": "A" * 65537})
    assert r.status_code == 422
