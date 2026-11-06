"""Safe renewal dispatcher: disabled by default, protected and deduplicated."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from vainah.main import app
from vainah import reminder_dispatch as dispatcher

ORIGIN = "https://vainahvpn-python-preview.onrender.com"


def test_dispatcher_is_disabled_without_optin_runner_config(monkeypatch):
    monkeypatch.delenv("VAINAH_REMINDER_DELIVERY_ENABLED", raising=False)
    monkeypatch.delenv("VAINAH_REMINDER_RUNNER_KEY", raising=False)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post("/api/internal/reminders/run").status_code == 503


def test_runner_enforces_long_separate_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", "s" * 48)
    monkeypatch.setenv("VAINAH_REMINDER_RUNNER_KEY", "k" * 48)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post("/api/internal/reminders/run").status_code == 403
        assert client.post("/api/internal/reminders/run",
                           headers={"X-Vainah-Reminder-Key": "incorrect"}).status_code == 403


def test_threshold_uses_only_real_future_datetimes():
    now = datetime(2026, 11, 6, tzinfo=UTC)
    assert dispatcher.threshold(now + timedelta(days=9), now) is None
    assert dispatcher.threshold(now + timedelta(days=6), now) == 7
    assert dispatcher.threshold(now + timedelta(days=2), now) == 3
    assert dispatcher.threshold(now + timedelta(hours=4), now) == 1
    assert dispatcher.threshold(now - timedelta(seconds=1), now) is None


def test_disabled_batch_never_queries_or_sends(monkeypatch):
    import asyncio
    monkeypatch.delenv("VAINAH_REMINDER_DELIVERY_ENABLED", raising=False)
    def forbidden():
        raise AssertionError("database must not be queried")
    monkeypatch.setattr(dispatcher, "_candidates", forbidden)
    assert asyncio.run(dispatcher.run_batch()) == {
        "enabled": False, "checked": 0, "sent": 0,
    }


def test_dispatcher_contains_single_delivery_claim_and_paid_order_guards():
    import inspect
    source = inspect.getsource(dispatcher)
    assert "ON CONFLICT DO NOTHING RETURNING owner_hash" in source
    assert "payment_state='paid'" in source
    assert "delivery_state='delivered'" in source
    assert "payment_state IN ('refunded','chargeback')" in source
    assert "read_h1_issued_client_status" in source
    assert "VAINAH_REMINDER_DELIVERY_ENABLED" in source
    assert "subscription_url" not in source
