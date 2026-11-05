"""Automatic SANDBOX RollyPay paid -> H1Cloud issuance integration tests.

Provider APIs are mocked: no real charges or VPN users are created. PostgreSQL
checks run only against VAINAH_TEST_DATABASE_URL in disposable per-test schemas.
The provider stub validates that only one POST is sent per signed test order.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from vainah import billing
from vainah import sandbox_auto_h1 as auto
from vainah.postgres_ledger import PostgresSandboxLedger

OPERATOR = "test-sandbox-operator-" + "x" * 40
WEBHOOK_SECRET = "test-webhook-only-" + "y" * 40
SIGNING_KEY = "test-account-secret-" + "z" * 40


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/vainah")
    monkeypatch.setenv("PANEL_BASE_URL", "https://vpn-panel.example.com/api")
    monkeypatch.setenv("PANEL_API_TOKEN", "test-h1-only-token")
    monkeypatch.delenv("PANEL_TLS_CA_PEM", raising=False)
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SHOP_PROVIDER_TEST_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SHOP_SANDBOX_MODE", "provider")
    monkeypatch.setenv("VAINAH_SANDBOX_AUTO_H1_ENABLED", "enabled")
    monkeypatch.setenv("VAINAH_SANDBOX_TEST_TOKEN", OPERATOR)
    monkeypatch.setenv("ROLLYPAY_SIGNING_SECRET", WEBHOOK_SECRET)


@pytest.fixture
def offline_claim_gate(monkeypatch):
    # Unit tests replace the durable claim itself; DB tests use the real gate.
    monkeypatch.setattr(auto, "_assert_claim_paid", lambda _claim: None)


def test_disabled_without_explicit_flag(configured, monkeypatch):
    monkeypatch.delenv("VAINAH_SANDBOX_AUTO_H1_ENABLED")
    assert auto.auto_enabled() is False
    monkeypatch.setenv("VAINAH_SANDBOX_AUTO_H1_ENABLED", "enabled")
    # Live app may not have persistent PostgreSQL test ledger: fail closed.
    old = billing.sandbox.ledger
    monkeypatch.setattr(billing.sandbox, "ledger", None)
    assert auto.auto_enabled() is False
    monkeypatch.setattr(
        billing.sandbox, "ledger",
        PostgresSandboxLedger("postgresql://test:test@localhost/vainah"),
    )
    old_mode = billing.sandbox.mode
    monkeypatch.setattr(billing.sandbox, "mode", "provider")
    assert auto.auto_enabled() is True
    monkeypatch.setattr(billing.sandbox, "mode", old_mode)
    monkeypatch.setattr(billing.sandbox, "ledger", old)


def test_h1_one_signed_paid_order_created_once(configured, offline_claim_gate, monkeypatch):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "a" * 32
    client_name = auto._name(order)
    issued = []
    claims = []
    requests = []
    expires_at = int(time.time()) + 30 * 86400

    def claim_once(order_id):
        claims.append(order_id)
        return (
            auto.Claim(order_id, client_name, "30", "v1_" + "e" * 64)
            if len(claims) == 1 else None
        )

    def provider(request):
        requests.append((request.method, str(request.url)))
        assert request.url.scheme == "https"
        assert request.headers.get("Authorization") == "Bearer test-h1-only-token"
        assert request.url.path in ("/api/info", "/api/create")
        if len(requests) == 1:
            assert request.method == "GET"
            assert request.url.params.get("name") == client_name
            return httpx.Response(404, json={"error": "user_not_found"})
        if len(requests) == 2:
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "name": client_name, "days": 30, "device_limit": 3,
            }
            return httpx.Response(201, json={"ok": True})
        assert request.method == "GET"
        return httpx.Response(200, json={
            "ok": True, "client": {
                "name": client_name, "expires_at": expires_at,
                "device_limit": 3,
                "subscription_url": "https://sub.example.com/private-test-link",
            },
        })

    monkeypatch.setattr(auto, "_claim_once", claim_once)
    monkeypatch.setattr(
        auto, "_mark_issued",
        lambda order_id, url: issued.append((order_id, url)),
    )
    monkeypatch.setattr(
        auto, "read_delivery", lambda _id: {
            "status": "issued", "vpn_delivered": True,
        },
    )
    monkeypatch.setattr(
        auto, "_mark_review",
        lambda _order: pytest.fail("Successful write must not need review"),
    )
    transport = httpx.MockTransport(provider)
    result = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert result == {"status": "issued", "vpn_delivered": True}
    assert len(requests) == 3
    assert issued == [(order, "https://sub.example.com/private-test-link")]

    # Provider retries a correctly signed webhook: no second H1 request.
    repeated = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert repeated == {"status": "issued", "vpn_delivered": True}
    assert len(requests) == 3


def test_h1_ambiguous_post_stays_locked(configured, offline_claim_gate, monkeypatch):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "b" * 32
    claimed = []
    needs_review = []
    calls = []
    monkeypatch.setattr(auto, "_claim_once", lambda order_id: (
        claimed.append(order_id) or
        auto.Claim(order_id, auto._name(order_id), "30", "v1_" + "f" * 64)
    ) if not claimed else None)
    monkeypatch.setattr(auto, "_mark_review", lambda oid: needs_review.append(oid))
    monkeypatch.setattr(auto, "read_delivery", lambda _id: {
        "status": "needs_review", "vpn_delivered": False,
    })

    def provider(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(404, json={"error": "user_not_found"})
        raise httpx.ReadTimeout("Test H1 write timeout")

    transport = httpx.MockTransport(provider)
    result = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert result["status"] == "needs_review"
    assert calls == ["GET", "POST"]
    assert needs_review == [order]
    again = __import__("asyncio").run(
        auto.auto_issue_paid_sandbox(order, transport=transport)
    )
    assert again == {"status": "needs_review", "vpn_delivered": False}
    assert calls == ["GET", "POST"]


def test_claim_sql_requires_paid_signed_provider_and_owner(configured, monkeypatch):
    queries = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, params=None):
            queries.append((sql, params))

        def fetchone(self):
            return (auto._name("vainah_test_" + "a" * 32), "30", "v1_" + "e" * 64)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        auto.psycopg, "connect", lambda *_args, **_kw: Connection(),
    )
    order = "vainah_test_" + "a" * 32
    claim = auto._claim_once(order)
    assert claim.plan_id == "30"
    sql = next(q for q, _ in queries if "INSERT INTO vainah_sandbox_auto_h1" in q)
    for guard in (
        "status = 'paid'", "paid_webhook_received = TRUE", "mode = 'provider'",
        "receipt_recipient IS NOT NULL", "ON CONFLICT (order_id) DO NOTHING",
    ):
        assert guard in sql
    assert order not in sql



@pytest.mark.parametrize("failure", ["timeout", "unavailable", "config"])
def test_h1_failure_before_write_is_retryable(configured, offline_claim_gate, monkeypatch, failure):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "c" * 32
    claim = auto.Claim(order, auto._name(order), "30", "v1_" + "f" * 64)
    monkeypatch.setattr(auto, "_claim_once", lambda _order: claim)
    failed = []
    monkeypatch.setattr(auto, "_mark_failed_before_write", failed.append)
    monkeypatch.setattr(auto, "_mark_review", lambda _order: pytest.fail(
        "A proven pre-write failure must not require ambiguous-write review"
    ))
    calls = []

    def provider(request):
        calls.append(request.method)
        if failure == "timeout":
            raise httpx.ReadTimeout("simulated preflight timeout")
        return httpx.Response(503)

    if failure == "config":
        monkeypatch.setattr(auto, "panel_settings", lambda: None)
    result = asyncio.run(auto.auto_issue_paid_sandbox(
        order, transport=httpx.MockTransport(provider),
    ))
    assert result == {"status": "failed_before_write", "vpn_delivered": False}
    assert failed == [order]
    assert calls == ([] if failure == "config" else ["GET"])


def test_existing_h1_user_requires_reconciliation_without_post(configured, offline_claim_gate, monkeypatch):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "d" * 32
    monkeypatch.setattr(auto, "_claim_once", lambda _order: auto.Claim(
        order, auto._name(order), "30", "v1_" + "f" * 64,
    ))
    reviewed = []
    calls = []
    monkeypatch.setattr(auto, "_mark_review", reviewed.append)

    def provider(request):
        calls.append(request.method)
        return httpx.Response(200, json={"ok": True})

    result = asyncio.run(auto.auto_issue_paid_sandbox(
        order, transport=httpx.MockTransport(provider),
    ))
    assert result == {"status": "needs_review", "vpn_delivered": False}
    assert reviewed == [order]
    assert calls == ["GET"]


@pytest.mark.parametrize("change", ["short_term", "banned", "wrong_name", "wrong_devices", "malformed_status", "malformed_ban", "malformed_expiry"])
def test_auto_h1_rejects_unverified_profile(configured, offline_claim_gate, monkeypatch, change):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "e" * 32
    name = auto._name(order)
    monkeypatch.setattr(auto, "_claim_once", lambda _order: auto.Claim(
        order, name, "30", "v1_" + "f" * 64,
    ))
    reviewed = []
    calls = []
    monkeypatch.setattr(auto, "_mark_review", reviewed.append)
    monkeypatch.setattr(auto, "_mark_issued", lambda *_: pytest.fail("Unverified account delivered"))
    profile = {
        "name": name, "expires_at": int(time.time()) + 30 * 86400,
        "device_limit": 3, "subscription_url": "https://sub.example.com/private",
    }
    if change == "short_term":
        profile["expires_at"] = int(time.time()) + 3600
    elif change == "banned":
        profile["banned"] = True
    elif change == "wrong_name":
        profile["name"] = "another_user"
    elif change == "wrong_devices":
        profile["device_limit"] = 1
    elif change == "malformed_status":
        profile["status"] = []
    elif change == "malformed_ban":
        profile["banned"] = "true"
    else:
        profile["expires_at"] = True

    def provider(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(200, json={"ok": True, "client": profile})

    assert asyncio.run(auto.auto_issue_paid_sandbox(
        order, transport=httpx.MockTransport(provider),
    )) == {"status": "needs_review", "vpn_delivered": False}
    assert reviewed == [order]
    assert calls == ["GET", "POST", "GET"]


def test_database_failure_after_h1_write_never_releases_claim(configured, offline_claim_gate, monkeypatch):
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = "vainah_test_" + "f" * 32
    name = auto._name(order)
    claimed = []
    monkeypatch.setattr(auto, "_claim_once", lambda _order: (
        claimed.append(order) or auto.Claim(order, name, "30", "v1_" + "f" * 64)
    ) if not claimed else None)
    monkeypatch.setattr(auto, "read_delivery", lambda _: {
        "status": "needs_review", "vpn_delivered": False,
    })
    reviewed = []
    calls = []
    monkeypatch.setattr(auto, "_mark_review", reviewed.append)
    monkeypatch.setattr(auto, "_mark_failed_before_write", lambda _: pytest.fail("Unsafe claim release"))

    def database_unavailable(*_args):
        raise auto.SandboxAutoH1Error("SANDBOX_AUTO_H1_DATABASE_UNAVAILABLE")

    monkeypatch.setattr(auto, "_mark_issued", database_unavailable)

    def provider(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(200, json={"ok": True, "client": {
            "name": name, "expires_at": int(time.time()) + 30 * 86400,
            "device_limit": 3, "subscription_url": "https://sub.example.com/private",
        }})

    transport = httpx.MockTransport(provider)
    for _ in range(2):
        result = asyncio.run(auto.auto_issue_paid_sandbox(order, transport=transport))
        assert result == {"status": "needs_review", "vpn_delivered": False}
    assert reviewed == [order]
    assert calls == ["GET", "POST", "GET"]


def test_signed_payment_real_postgres_otp_to_one_h1_delivery(
    configured, postgres_url, monkeypatch,
):
    """All persistence/auth/signature paths are real; external APIs are mocks."""
    import hashlib
    import hmac

    import psycopg
    from fastapi.testclient import TestClient

    from vainah import email_auth
    from vainah.main import app

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("RESEND_API_KEY", "test-email-key-" + "s" * 32)
    monkeypatch.setenv("VAINAH_EMAIL_FROM", "Vainah Test <test@example.com>")
    origin = "https://vainah-test.example.com"
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", origin)
    codes, receipts, h1_calls = [], [], []
    invoice = {}

    async def send_code(email, code):
        codes.append((email, code))

    async def send_receipt(email, **details):
        receipts.append((email, details))

    monkeypatch.setattr(email_auth, "send_verification_code", send_code)
    monkeypatch.setattr(billing, "send_sandbox_receipt", send_receipt)

    def rollypay(request):
        assert request.method == "POST"
        assert request.url.host == "rollypay.io"
        body = json.loads(request.content)
        # The reservation must already be committed before the provider call.
        with psycopg.connect(postgres_url) as conn:
            pending = conn.execute(
                "SELECT status FROM vainah_sandbox_orders WHERE order_id = %s",
                (body["order_id"],),
            ).fetchone()
        assert pending == ("created",)
        invoice.update({
            "order_id": body["order_id"], "payment_id": "pay_test_1234567890",
            "amount": "99.00", "currency": "RUB", "status": "created",
            "test": True, "environment": "sandbox",
            "pay_url": "https://pay.rollypay.io/pay/synthetic_test_only",
        })
        return httpx.Response(200, json=invoice)

    store = billing.BillingSandbox(
        "provider", api_key="test-only-rollypay-key", ledger_path=postgres_url,
        transport=httpx.MockTransport(rollypay),
    )
    monkeypatch.setattr(billing, "sandbox", store)

    def h1(request):
        h1_calls.append(request.method)
        assert request.url.host == "vpn-panel.example.com"
        name = auto._name(invoice["order_id"])
        if len(h1_calls) == 1:
            assert request.method == "GET"
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            assert json.loads(request.content) == {
                "name": name, "days": 30, "device_limit": 3,
            }
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(200, json={"ok": True, "client": {
            "name": name, "device_limit": 3,
            "expires_at": int(time.time()) + 30 * 86400,
            "subscription_url": "https://sub.example.com/secret-sandbox-only",
        }})

    original_issue = auto.auto_issue_paid_sandbox

    async def issue_with_mock(order_id):
        return await original_issue(order_id, transport=httpx.MockTransport(h1))

    monkeypatch.setattr(auto, "auto_issue_paid_sandbox", issue_with_mock)

    def callback(client, event, *, valid_signature=True):
        raw = json.dumps(event, separators=(",", ":")).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(
            WEBHOOK_SECRET.encode(), stamp.encode() + b"." + raw, hashlib.sha256,
        ).hexdigest() if valid_signature else "0" * 64
        return client.post("/api/shop/webhooks/rollypay", content=raw, headers={
            "X-Test-Mode": "true", "X-Signature": signature,
            "X-Timestamp": stamp, "Content-Type": "application/json",
        })

    with TestClient(app, base_url=origin) as client:
        # Obtain a real OTP-verified cookie, using actual PostgreSQL OTP storage.
        response = client.post("/api/email-auth/request", json={
            "email": "buyer@example.com",
        }, headers={"Origin": origin})
        assert response.status_code == 200, response.text
        response = client.post("/api/email-auth/verify", json={
            "email": "buyer@example.com", "code": codes[0][1],
        }, headers={"Origin": origin})
        assert response.status_code == 200, response.text
        response = client.post("/api/shop/sandbox/start", json={"plan": "30"}, headers={
            "X-Sandbox-Token": OPERATOR,
        })
        assert response.status_code == 200, response.text
        order_id = response.json()["order_id"]
        # Callback reaches an independent worker whose cache predates this order.
        receiver = billing.BillingSandbox("provider", ledger_path=postgres_url)
        receiver._ensure_loaded()
        receiver.orders.clear()
        monkeypatch.setattr(billing, "sandbox", receiver)
        paid = {key: invoice[key] for key in (
            "order_id", "payment_id", "amount", "currency", "test",
        )} | {"event_type": "payment.paid", "status": "paid"}
        assert callback(client, paid, valid_signature=False).status_code == 403
        for changed in (
            {"order_id": "vainah_test_" + "0" * 32},
            {"payment_id": "pay_other_1234567890"},
            {"amount": "1.00"}, {"currency": "USD"},
            {"test": False},
        ):
            assert callback(client, paid | changed).status_code == (404 if "order_id" in changed else 400)
        created = paid | {"event_type": "payment.created", "status": "created"}
        assert callback(client, created).status_code == 200
        assert h1_calls == []
        for _ in range(2):
            response = callback(client, paid)
            assert response.status_code == 200, response.text
            assert response.json()["delivery_state"] == "issued"
            assert response.json()["vpn_delivered"] is True
        assert h1_calls == ["GET", "POST", "GET"]
        assert len(receipts) == 1
        recipient, receipt = receipts[0]
        assert recipient == "buyer@example.com"
        assert receipt["vpn_issued"] is True
        assert receipt["order_id"] == order_id
        assert receipt["amount_rub"] == "99.00"
        assert receipt["duration_days"] == 30
        assert receipt["devices"] == 3
        assert receipt["subscription_url"] == "https://sub.example.com/secret-sandbox-only"
        access_path = f"/api/shop/my-test-orders/{order_id}/vpn-access"
        response = client.get(access_path)
        assert response.status_code == 200, response.text
        assert response.json()["subscription_url"] == "https://sub.example.com/secret-sandbox-only"
        summary = client.get("/api/account/test-subscriptions")
        assert summary.status_code == 200, summary.text
        assert summary.json()["items"][0]["delivery_state"] == "issued"
        assert "secret-sandbox-only" not in summary.text
        client.cookies.clear()
        assert client.get(access_path).status_code == 401
        client.cookies.set(email_auth.EMAIL_SESSION_COOKIE, email_auth._sign_session("outsider@example.com"))
        assert client.get(access_path).status_code == 404
        assert client.get("/api/account/test-subscriptions").json()["items"] == []
    with psycopg.connect(postgres_url) as conn:
        delivery = conn.execute(
            "SELECT state, subscription_cipher FROM vainah_sandbox_auto_h1 WHERE order_id = %s",
            (order_id,),
        ).fetchone()
        assert delivery[0] == "issued"
        assert "secret-sandbox-only" not in delivery[1]


def test_postgres_claim_concurrency_and_only_prewrite_retry(configured, postgres_url, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    import psycopg

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    ledger = PostgresSandboxLedger(postgres_url)
    order = billing.TestOrder(
        "vainah_test_" + "a" * 32, "30", "99.00", "pay_test_1234567890",
        "paid", "provider", owner_ref="v1_" + "a" * 64,
        receipt_recipient="encrypted-recipient", webhook_received=True,
        paid_webhook_received=True,
    )
    ledger.save(order)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(auto._claim_once, [order.order_id] * 8))
    assert sum(claim is not None for claim in claims) == 1
    auto._mark_failed_before_write(order.order_id)
    assert auto._claim_once(order.order_id) is not None
    # A crashed historical claim remains locked regardless of its age.
    with psycopg.connect(postgres_url) as conn:
        conn.execute("UPDATE vainah_sandbox_auto_h1 SET created_at = now() - interval '10 years'")
    assert auto._claim_once(order.order_id) is None
    auto._mark_review(order.order_id)
    assert auto._claim_once(order.order_id) is None


def test_postgres_legacy_generic_paid_proof_is_not_claimable(configured, postgres_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    ledger = PostgresSandboxLedger(postgres_url)
    order = billing.TestOrder(
        "vainah_test_" + "b" * 32, "30", "99.00", "pay_test_1234567890",
        "paid", "provider", owner_ref="v1_" + "a" * 64,
        receipt_recipient="encrypted-recipient", webhook_received=True,
    )
    ledger.save(order)
    assert auto._claim_once(order.order_id) is None
    assert auto.read_delivery(order.order_id) == {"status": "not_issued", "vpn_delivered": False}


def test_postgres_legacy_delivery_schema_migrates_without_reclaim(
    configured, postgres_url, monkeypatch,
):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    with psycopg.connect(postgres_url) as conn:
        conn.execute("""
            CREATE TABLE vainah_sandbox_auto_h1 (
                order_id VARCHAR(44) PRIMARY KEY,
                client_name VARCHAR(30) NOT NULL UNIQUE,
                owner_ref VARCHAR(67) NOT NULL,
                plan_id VARCHAR(24) NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('claimed', 'issued', 'needs_review')),
                subscription_cipher TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                issued_at TIMESTAMPTZ
            )
        """)
    ledger = PostgresSandboxLedger(postgres_url)
    for index, state in enumerate(("claimed", "needs_review", "issued")):
        order_id = "vainah_test_" + str(index) * 32
        ledger.save(billing.TestOrder(
            order_id, "30", "99.00", "pay_test_" + str(index) * 32,
            "paid", "provider", owner_ref="v1_" + "a" * 64,
            receipt_recipient="encrypted-recipient", webhook_received=True,
            paid_webhook_received=True,
        ))
        with psycopg.connect(postgres_url) as conn:
            conn.execute("""
                INSERT INTO vainah_sandbox_auto_h1
                (order_id, client_name, owner_ref, plan_id, state, subscription_cipher)
                VALUES (%s, %s, %s, '30', %s, %s)
            """, (order_id, auto._name(order_id), "v1_" + "a" * 64, state,
                  auto.seal_live_secret("https://sub.example.com/legacy") if state == "issued" else None))
        assert auto._claim_once(order_id) is None
        assert auto.read_delivery(order_id)["status"] == state
    # The migrated constraint allows proven pre-write failures and pending rows;
    # old ambiguous claims were not reset as a side effect of migration.
    with psycopg.connect(postgres_url) as conn:
        conn.execute("UPDATE vainah_sandbox_auto_h1 SET state = 'failed_before_write' WHERE state = 'claimed'")
    assert auto._claim_once("vainah_test_" + "0" * 32) is not None
    with psycopg.connect(postgres_url) as conn:
        conn.execute("UPDATE vainah_sandbox_auto_h1 SET state = 'pending' WHERE state = 'claimed'")
    assert auto._claim_once("vainah_test_" + "0" * 32) is not None


@pytest.mark.parametrize("phase", ["preflight", "write", "postcheck"])
def test_cancelled_attempt_persists_safe_state(
    configured, offline_claim_gate, monkeypatch, phase,
):
    order = "vainah_test_" + "d" * 32
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    monkeypatch.setattr(auto, "_claim_once", lambda _order: auto.Claim(
        order, auto._name(order), "30", "v1_" + "e" * 64,
    ))
    states, calls = [], []
    monkeypatch.setattr(auto, "_mark_review", lambda _: states.append("needs_review"))
    monkeypatch.setattr(auto, "_mark_failed_before_write", lambda _: states.append("failed_before_write"))

    def provider(request):
        calls.append(request.method)
        if ((phase == "preflight" and len(calls) == 1)
                or (phase == "write" and request.method == "POST")
                or (phase == "postcheck" and len(calls) == 3)):
            raise asyncio.CancelledError()
        return httpx.Response(404, json={"error": "user_not_found"}) if len(calls) == 1 else httpx.Response(201, json={"ok": True})

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(auto.auto_issue_paid_sandbox(order, transport=httpx.MockTransport(provider)))
    assert states == ["failed_before_write" if phase == "preflight" else "needs_review"]
    assert calls.count("POST") == (0 if phase == "preflight" else 1)


@pytest.mark.parametrize("transition", ["_mark_review", "_mark_failed_before_write"])
def test_failed_state_persistence_reports_storage_error(configured, monkeypatch, transition):
    import psycopg

    def unavailable(*_args, **_kwargs):
        raise psycopg.OperationalError("private connection details")

    monkeypatch.setattr(auto.psycopg, "connect", unavailable)
    with pytest.raises(auto.SandboxAutoH1Error, match="DATABASE_UNAVAILABLE") as failure:
        getattr(auto, transition)("vainah_test_" + "a" * 32)
    assert "private connection details" not in str(failure.value)


def test_refund_during_preflight_prevents_h1_write(configured, postgres_url, monkeypatch):
    from dataclasses import replace

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    ledger = PostgresSandboxLedger(postgres_url)
    order = billing.TestOrder(
        "vainah_test_" + "c" * 32, "30", "99.00", "pay_test_1234567890",
        "paid", "provider", owner_ref="v1_" + "a" * 64,
        receipt_recipient="encrypted-recipient", webhook_received=True,
        paid_webhook_received=True,
    )
    ledger.save(order)
    calls = []

    def provider(request):
        calls.append(request.method)
        assert request.method == "GET"
        # A different worker commits the signed reversal during preflight.
        ledger.save(replace(order, status="refunded"))
        return httpx.Response(404, json={"error": "user_not_found"})

    result = asyncio.run(auto.auto_issue_paid_sandbox(
        order.order_id, transport=httpx.MockTransport(provider),
    ))
    assert result == {"status": "failed_before_write", "vpn_delivered": False}
    assert calls == ["GET"]
    assert auto._claim_once(order.order_id) is None
    assert auto.read_delivery(order.order_id, owner_ref=order.owner_ref, with_access=True) == {
        "status": "not_issued", "vpn_delivered": False,
    }


def test_issued_row_without_link_is_not_reported_delivered(configured, postgres_url, monkeypatch):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    order = billing.TestOrder(
        "vainah_test_" + "d" * 32, "30", "99.00", "pay_test_1234567890",
        "paid", "provider", owner_ref="v1_" + "a" * 64,
        receipt_recipient="encrypted-recipient", webhook_received=True,
        paid_webhook_received=True,
    )
    PostgresSandboxLedger(postgres_url).save(order)
    assert auto._claim_once(order.order_id) is not None
    with psycopg.connect(postgres_url) as conn:
        conn.execute("UPDATE vainah_sandbox_auto_h1 SET state = 'issued'")
    for with_access in (False, True):
        with pytest.raises(auto.SandboxAutoH1Error, match="LINK_UNAVAILABLE"):
            auto.read_delivery(order.order_id, owner_ref=order.owner_ref, with_access=with_access)


@pytest.mark.parametrize("transition", ["_mark_review", "_mark_failed_before_write"])
def test_stale_state_transition_does_not_report_success(
    configured, postgres_url, monkeypatch, transition,
):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    order = billing.TestOrder(
        "vainah_test_" + "e" * 32, "30", "99.00", "pay_test_1234567890",
        "paid", "provider", owner_ref="v1_" + "a" * 64,
        receipt_recipient="encrypted-recipient", webhook_received=True,
        paid_webhook_received=True,
    )
    PostgresSandboxLedger(postgres_url).save(order)
    assert auto._claim_once(order.order_id) is not None
    auto._mark_issued(order.order_id, "https://sub.example.com/issued")
    with pytest.raises(auto.SandboxAutoH1Error):
        getattr(auto, transition)(order.order_id)
    assert auto.read_delivery(order.order_id) == {"status": "issued", "vpn_delivered": True}


def test_refund_after_h1_write_does_not_deliver_access(configured, postgres_url, monkeypatch):
    from dataclasses import replace

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setattr(auto, "auto_enabled", lambda: True)
    order = billing.TestOrder(
        "vainah_test_" + "f" * 32, "30", "99.00", "pay_test_1234567890",
        "paid", "provider", owner_ref="v1_" + "a" * 64,
        receipt_recipient="encrypted-recipient", webhook_received=True,
        paid_webhook_received=True,
    )
    ledger = PostgresSandboxLedger(postgres_url)
    ledger.save(order)
    calls = []

    def provider(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(404, json={"error": "user_not_found"})
        if request.method == "POST":
            return httpx.Response(201, json={"ok": True})
        ledger.save(replace(order, status="refunded"))
        return httpx.Response(200, json={"ok": True, "client": {
            "name": auto._name(order.order_id), "expires_at": int(time.time()) + 30 * 86400,
            "device_limit": 3, "subscription_url": "https://sub.example.com/not-delivered",
        }})

    assert asyncio.run(auto.auto_issue_paid_sandbox(
        order.order_id, transport=httpx.MockTransport(provider),
    )) == {"status": "needs_review", "vpn_delivered": False}
    assert calls == ["GET", "POST", "GET"]
    assert auto._claim_once(order.order_id) is None
    assert auto.read_delivery(order.order_id, owner_ref=order.owner_ref, with_access=True) == {
        "status": "not_issued", "vpn_delivered": False,
    }


@pytest.mark.parametrize("operation", ["review", "prewrite_failed", "claim_check", "issued", "claim", "read"])
def test_delivery_database_lock_waits_are_bounded(
    configured, postgres_url, monkeypatch, operation,
):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", postgres_url)
    order = billing.TestOrder(
        "vainah_test_" + "b" * 32, "30", "99.00", "pay_test_1234567890",
        "paid", "provider", owner_ref="v1_" + "a" * 64,
        receipt_recipient="encrypted-recipient", webhook_received=True,
        paid_webhook_received=True,
    )
    PostgresSandboxLedger(postgres_url).save(order)
    claim = auto._claim_once(order.order_id)
    assert claim is not None
    monkeypatch.setattr(auto, "LOCK_TIMEOUT_MS", 30)
    monkeypatch.setattr(auto, "STATEMENT_TIMEOUT_MS", 200)
    operations = {
        "review": lambda: auto._mark_review(order.order_id),
        "prewrite_failed": lambda: auto._mark_failed_before_write(order.order_id),
        "claim_check": lambda: auto._assert_claim_paid(claim),
        "issued": lambda: auto._mark_issued(order.order_id, "https://sub.example.com/held"),
        "claim": lambda: auto._claim_once(order.order_id),
        "read": lambda: auto.read_delivery(order.order_id),
    }
    with psycopg.connect(postgres_url) as holder:
        holder.execute("LOCK TABLE vainah_sandbox_auto_h1 IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        with pytest.raises(auto.SandboxAutoH1Error, match="DATABASE_UNAVAILABLE"):
            operations[operation]()
        assert time.monotonic() - started < 2
    assert auto.read_delivery(order.order_id) == {"status": "claimed", "vpn_delivered": False}
