"""PostgreSQL sandbox ledger tests use in-memory fake connections, not a live DB."""
import asyncio

import psycopg
import pytest
from fastapi import HTTPException

from vainah.billing import BillingSandbox
from vainah.postgres_ledger import LedgerUnavailable, PostgresSandboxLedger


class FakeCursor:
    def __init__(self, storage):
        self.storage = storage
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        query = " ".join(sql.split()).upper()
        if query.startswith("CREATE TABLE"):
            assert "VAINAH_SANDBOX_ORDERS" in query
        elif query.startswith("INSERT"):
            assert "%s" in sql
            assert params is not None and len(params) == 6
            self.storage[params[0]] = tuple(params)
        elif query.startswith("SELECT"):
            self.rows = [
                self.storage[key]
                for key in sorted(self.storage)
            ]
        else:
            raise AssertionError("Unexpected SQL statement")

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, storage):
        self.storage = storage

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return FakeCursor(self.storage)


def test_postgres_sandbox_orders_survive_reconstructed_service(monkeypatch):
    storage = {}
    urls = []

    def fake_connect(url, **kwargs):
        urls.append((url, kwargs))
        return FakeConnection(storage)

    monkeypatch.setattr("vainah.postgres_ledger.psycopg.connect", fake_connect)
    url = "postgresql://test_user:SECRET_PASSWORD@localhost/sandbox_db"
    first = BillingSandbox("mock", ledger_path=url)
    # No database connection is made during import/service startup.
    assert urls == []

    created = asyncio.run(first.create("30"))
    assert created["status"] == "created"
    assert asyncio.run(first.refresh(created["order_id"]))["status"] == "created"
    assert first.simulate(created["order_id"])["status"] == "paid"
    assert all(kwargs["connect_timeout"] == 4 for _, kwargs in urls)

    second = BillingSandbox("mock", ledger_path=url)
    assert second.read(created["order_id"])["status"] == "paid"
    assert second.activation_preview(created["order_id"])["h1cloud_connected"] is False
    assert second.activation_preview(created["order_id"])["vpn_delivered"] is False
    assert second.list_test_orders()[0]["pay_url"] is None
    assert "SECRET_PASSWORD" not in str(second.list_test_orders())


def test_postgres_sandbox_ledger_redacts_failed_connection(monkeypatch):
    private_url = "postgresql://username:SECRET_PASSWORD@db.example/sandbox"

    def fail_connection(_url, **_kwargs):
        raise psycopg.OperationalError(private_url)

    monkeypatch.setattr("vainah.postgres_ledger.psycopg.connect", fail_connection)
    store = PostgresSandboxLedger(private_url)
    with pytest.raises(LedgerUnavailable) as error:
        store.load()
    assert "SECRET_PASSWORD" not in str(error.value)

    service = BillingSandbox("mock", ledger_path=private_url)
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.create("30"))
    assert error.value.status_code == 503
    assert error.value.detail == "SANDBOX_LEDGER_UNAVAILABLE"
    assert service.orders == {}


def test_test_sandbox_database_never_shows_real_payment_options(monkeypatch):
    storage = {}

    def fake_connect(_url, **_kwargs):
        return FakeConnection(storage)

    monkeypatch.setattr("vainah.postgres_ledger.psycopg.connect", fake_connect)
    service = BillingSandbox(
        "mock", ledger_path="postgresql://user:password@localhost/db"
    )
    created = asyncio.run(service.create("365-family"))
    assert created["real_charge"] is False
    service.simulate(created["order_id"])
    plan = service.activation_preview(created["order_id"])
    assert plan["status"] == "demo_ready"
    assert plan["duration_days"] == 365
    assert plan["device_limit"] == 6
    assert plan["vpn_delivered"] is False
    assert plan["subscription_url"] is None
