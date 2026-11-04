"""Database status checks must never disclose secrets or require a live DB."""
import asyncio

from fastapi.testclient import TestClient

from vainah import db_health
from vainah.main import app


def test_status_without_render_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = asyncio.run(db_health.database_status())
    assert result["status"] == "not_connected"
    assert "DATABASE_URL" in result["message"]


def test_status_when_database_url_invalid(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "invalid-secret-connection")
    result = asyncio.run(db_health.database_status())
    assert result["status"] == "error"
    assert "invalid-secret-connection" not in str(result)


def test_status_success_does_not_expose_connection_url(monkeypatch):
    secret = "postgresql://test_user:SECRET_PASSWORD@db.example/test_db"
    monkeypatch.setenv("DATABASE_URL", secret)
    seen = []

    async def fake_ping(url):
        seen.append(url)

    monkeypatch.setattr(db_health, "_ping", fake_ping)
    result = asyncio.run(db_health.database_status())
    assert result["status"] == "ok"
    assert seen == [secret]
    assert secret not in str(result)
    assert "SECRET_PASSWORD" not in str(result)


def test_status_failure_hides_database_error(monkeypatch):
    secret = "postgresql://test_user:SECRET_PASSWORD@db.example/test_db"
    monkeypatch.setenv("DATABASE_URL", secret)

    async def fake_ping(_url):
        raise RuntimeError(secret)

    monkeypatch.setattr(db_health, "_ping", fake_ping)
    result = asyncio.run(db_health.database_status())
    assert result["status"] == "error"
    assert "SECRET_PASSWORD" not in str(result)
    assert "db.example" not in str(result)


def test_site_services_checks_real_database_status(monkeypatch):
    async def fake_status():
        return {"status": "ok", "message": "PostgreSQL отвечает."}

    monkeypatch.setattr("vainah.main.database_status", fake_status)
    result = TestClient(app).get("/api/site/services")
    assert result.status_code == 200
    assert result.json()["services"]["database"]["status"] == "ok"
    assert result.json()["services"]["database"]["message"] == "PostgreSQL отвечает."
