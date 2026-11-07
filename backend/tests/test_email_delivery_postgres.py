"""Email identity/challenge checks against disposable PostgreSQL schemas."""
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from fastapi import HTTPException

from vainah import customer_portal, email_auth, email_delivery


@pytest.fixture
def configured(postgres_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-only-email-binding-" + "s" * 40)
    return postgres_url


def test_login_success_does_not_reset_resend_cooldown(configured):
    code = email_auth._locked_send_code("owner@example.com", "a" * 64)
    assert email_auth._verify_code("owner@example.com", code) is True
    with pytest.raises(HTTPException) as error:
        email_auth._locked_send_code("owner@example.com", "a" * 64)
    assert error.value.status_code == 429
    assert error.value.detail == "EMAIL_LOGIN_COOLDOWN"
    assert email_auth._verify_code("owner@example.com", code) is False


def test_verified_logins_preserve_the_per_email_hour_budget(configured):
    for _ in range(email_auth.HOUR_LIMIT):
        code = email_auth._locked_send_code("owner@example.com", "a" * 64)
        assert email_auth._verify_code("owner@example.com", code) is True
        # Advance only the resend deadline to simulate another send this hour.
        with psycopg.connect(configured) as connection:
            connection.execute("UPDATE vainah_email_login_codes SET next_send_at = now() - interval '1 second'")
    with pytest.raises(HTTPException) as error:
        email_auth._locked_send_code("owner@example.com", "b" * 64)
    assert error.value.status_code == 429
    assert error.value.detail == "EMAIL_LOGIN_LIMIT"


def test_binding_first_workers_create_and_confirm_independent_emails(configured):
    start = Barrier(4)

    def issue(index):
        start.wait(timeout=10)
        uid = str(123456780 + index)
        email = f"owner{index}@example.com"
        return uid, email, email_delivery.start_challenge(uid, email)

    with ThreadPoolExecutor(max_workers=4) as pool:
        challenges = list(pool.map(issue, range(4)))
    for uid, email, code in challenges:
        assert email_delivery.confirm_challenge(uid, code) == email
        assert email_delivery.verified_email(uid) == email
        with pytest.raises(HTTPException):
            email_delivery.confirm_challenge(uid, code)


def test_same_mailbox_cannot_be_claimed_by_two_telegram_accounts(configured):
    codes = {uid: email_delivery.start_challenge(uid, "shared@example.com") for uid in ("123456781", "123456782")}
    start = Barrier(2)

    def confirm(uid):
        start.wait(timeout=10)
        try:
            return uid, email_delivery.confirm_challenge(uid, codes[uid])
        except HTTPException as error:
            return uid, error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(confirm, codes))
    winners = [uid for uid, result in outcomes if result == "shared@example.com"]
    assert len(winners) == 1
    assert [result for _, result in outcomes].count(409) == 1
    assert email_delivery.verified_email(winners[0]) == "shared@example.com"
    other = next(uid for uid in codes if uid != winners[0])
    assert email_delivery.verified_email(other) is None


def test_wrong_binding_attempts_are_committed_and_cannot_verify_later(configured):
    uid = "123456789"
    code = email_delivery.start_challenge(uid, "owner@example.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(email_delivery.MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as error:
            email_delivery.confirm_challenge(uid, wrong)
        assert error.value.detail == "EMAIL_CODE_INVALID"
    with pytest.raises(HTTPException) as error:
        email_delivery.confirm_challenge(uid, code)
    assert error.value.detail == "EMAIL_CODE_EXPIRED"
    assert email_delivery.verified_email(uid) is None


def test_failed_old_delivery_cannot_cancel_replacement_challenge(configured, monkeypatch):
    uid = "123456789"
    monkeypatch.setattr(email_delivery.secrets, "randbelow", lambda _n: 123456)
    old = email_delivery.start_challenge(uid, "old@example.com")
    with psycopg.connect(configured) as connection:
        connection.execute("UPDATE vainah_email_challenges SET next_send_at = now() - interval '1 second'")
    monkeypatch.setattr(email_delivery.secrets, "randbelow", lambda _n: 654321)
    new = email_delivery.start_challenge(uid, "new@example.com")
    email_delivery.cancel_challenge(uid, old, "old@example.com")
    assert email_delivery.confirm_challenge(uid, new) == "new@example.com"


def test_failed_login_deliveries_do_not_reset_hourly_budget(configured):
    for _ in range(email_auth.HOUR_LIMIT):
        code = email_auth._locked_send_code("owner@example.com", "a" * 64)
        email_auth._cancel_failed_delivery("owner@example.com", code)
        assert email_auth._verify_code("owner@example.com", code) is False
    with pytest.raises(HTTPException) as error:
        email_auth._locked_send_code("owner@example.com", "b" * 64)
    assert error.value.detail == "EMAIL_LOGIN_LIMIT"


def test_successful_binding_keeps_resend_cooldown(configured):
    code = email_delivery.start_challenge("123456789", "owner@example.com")
    assert email_delivery.confirm_challenge("123456789", code) == "owner@example.com"
    with pytest.raises(HTTPException) as error:
        email_delivery.start_challenge("123456789", "another@example.com")
    assert error.value.status_code == 429
    assert error.value.detail == "EMAIL_VERIFY_COOLDOWN"


def test_binding_and_reverse_lookup_share_first_use_initializer(configured):
    start = Barrier(4)

    def call(index):
        start.wait(timeout=10)
        email = f"owner{index}@example.com"
        if index % 2:
            return customer_portal.telegram_id_for_verified_email(email)
        return email_delivery.start_challenge(str(123456780 + index), email)

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(call, range(4)))
    assert outcomes[1] is None and outcomes[3] is None
    assert all(isinstance(outcomes[index], str) for index in (0, 2))


def test_concurrent_login_sources_cannot_exceed_shared_budget(configured, monkeypatch):
    monkeypatch.setattr(email_auth, "IP_HOUR_LIMIT", 2)
    start = Barrier(5)

    def issue(index):
        start.wait(timeout=10)
        try:
            return email_auth._locked_send_code(f"owner{index}@example.com", "a" * 64)
        except HTTPException as error:
            assert error.detail == "EMAIL_LOGIN_LIMIT"
            return error.status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(issue, range(5)))
    assert sum(isinstance(result, str) for result in outcomes) == 2
    assert outcomes.count(429) == 3


@pytest.mark.parametrize("mode", ["login", "binding"])
def test_failed_delivery_cleanup_has_bounded_lock_wait(configured, monkeypatch, mode):
    module = email_auth if mode == "login" else email_delivery
    monkeypatch.setattr(module, "LOCK_TIMEOUT_MS", 100)
    monkeypatch.setattr(module, "STATEMENT_TIMEOUT_MS", 250)
    if mode == "login":
        code = email_auth._locked_send_code("owner@example.com", "a" * 64)

        def cancel():
            email_auth._cancel_failed_delivery("owner@example.com", code)

        query = "SELECT email FROM vainah_email_login_codes FOR UPDATE"
    else:
        code = email_delivery.start_challenge("123456789", "owner@example.com")

        def cancel():
            email_delivery.cancel_challenge("123456789", code, "owner@example.com")

        query = "SELECT telegram_id FROM vainah_email_challenges FOR UPDATE"
    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(configured) as blocker:
        blocker.execute(query)
        # Cleanup must not hide an upstream delivery failure behind an
        # unlimited row lock wait. Its own database errors are sanitized.
        assert pool.submit(cancel).result(timeout=1) is None
    cancel()
    if mode == "login":
        assert email_auth._verify_code("owner@example.com", code) is False
    else:
        with pytest.raises(HTTPException):
            email_delivery.confirm_challenge("123456789", code)


def test_binding_code_expiring_while_waiting_for_row_lock_is_rejected(configured):
    code = email_delivery.start_challenge("123456789", "owner@example.com")
    with psycopg.connect(configured) as connection:
        connection.execute("UPDATE vainah_email_challenges SET expires_at = clock_timestamp() + interval '150 milliseconds'")
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(configured) as blocker:
            blocker.execute("SELECT telegram_id FROM vainah_email_challenges FOR UPDATE")
            outcome = pool.submit(email_delivery.confirm_challenge, "123456789", code)
            time.sleep(0.3)
        with pytest.raises(HTTPException) as error:
            outcome.result(timeout=2)
    assert error.value.detail == "EMAIL_CODE_EXPIRED"
    assert email_delivery.verified_email("123456789") is None

