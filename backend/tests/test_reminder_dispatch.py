"""Safe renewal dispatcher: disabled by default, protected and deduplicated."""
import asyncio
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import psycopg
from fastapi.testclient import TestClient

from vainah import reminder_dispatch as dispatcher
from vainah.live_checkout import owner_ref_for_email
from vainah.live_ledger import PostgresLiveOrderLedger, seal_live_secret
from vainah.main import app

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


def test_batch_reaches_opted_in_customer_after_first_page(monkeypatch, postgres_url):
    key = "test-reminder-" + "k" * 40
    monkeypatch.setenv("SESSION_SIGNING_KEY", key)
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("VAINAH_REMINDER_DELIVERY_ENABLED", "true")
    monkeypatch.setattr(dispatcher, "email_service_ready", lambda: True)
    emails = sorted((f"customer{i}@example.com" for i in range(dispatcher.PAGE_SIZE + 1)),
                    key=owner_ref_for_email)
    expiry = datetime.now(UTC) + timedelta(days=2)

    def preference_hash(email):
        return hmac.new(key.encode(), ("subscription-reminder-v1\n" + email).encode(),
                        hashlib.sha256).hexdigest()

    with psycopg.connect(postgres_url) as conn, conn.cursor() as cur:
        PostgresLiveOrderLedger._schema(cur)
        dispatcher._schema(cur)
        cur.executemany("""
            INSERT INTO vainah_live_orders (
                order_id, owner_ref, plan_id, amount_rub, receipt_email_cipher,
                payment_state, delivery_state, delivered_at, h1_expires_at
            ) VALUES (%s,%s,'30',99,%s,'paid','delivered',now(),%s)
        """, [(f"vainah_live_{i:032x}", owner_ref_for_email(email), seal_live_secret(email), expiry)
              for i, email in enumerate(emails)])
        cur.executemany("INSERT INTO vainah_reminder_preferences (owner_hash, enabled) VALUES (%s, TRUE)",
                        [(preference_hash(email),) for email in (emails[0], emails[-1])])
    assert dispatcher._claim(preference_hash(emails[0]), expiry, 3)

    sent, provider_checks = [], []

    async def read_panel(name):
        provider_checks.append(name)
        return {"found": True, "active": True, "expires_at": expiry.isoformat()}

    async def send(email, *_args, **_kwargs):
        sent.append(email)

    monkeypatch.setattr(dispatcher, "read_h1_issued_client_status", read_panel)
    monkeypatch.setattr(dispatcher, "send_email", send)
    assert asyncio.run(dispatcher.run_batch())["sent"] == 1
    assert asyncio.run(dispatcher.run_batch())["sent"] == 0
    assert sent == [emails[-1]]
    assert len(provider_checks) == 1
