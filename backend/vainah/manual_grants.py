"""Operator-issued no-payment VPN access, isolated from paid subscriptions.

An explicit 2-secret operator action creates at most one H1Cloud client per
idempotency ID. A durable claim precedes any write; uncertain outcomes are
locked for manual review. Customer access requires a verified email session.
Never log private links, credentials, or customer email addresses.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
import psycopg
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .billing import _require_operator
from .email_auth import current_email, normalize_email
from .email_delivery import database_url, send_email
from .h1_live_provision import LiveH1Error, _client, _disabled, _expiry, _validate_subscription_url
from .h1_panel import H1PanelError, panel_settings, panel_tls_verify, read_h1_issued_client_status
from .live_checkout import require_pilot_operator
from .live_ledger import LiveLedgerError, seal_live_secret, unseal_live_secret
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/operator/manual-grants", tags=["Operator grants"])
customer_router = APIRouter(prefix="/api/account", tags=["Customer account"])
GRANT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ALLOWED_DAYS = {1, 7, 30, 90, 180, 365}
ALLOWED_DEVICES = {1, 2, 3, 6}


class GrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_email: str = Field(min_length=5, max_length=254)
    grant_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    days: int
    devices: int
    confirm: bool


class GrantError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


def _authorized(operator_token: str | None, pilot_token: str | None) -> None:
    _require_operator(operator_token)
    require_pilot_operator(pilot_token)
    if os.environ.get("VAINAH_MANUAL_GRANTS_ENABLED") != "enabled":
        raise HTTPException(503, "MANUAL_GRANTS_DISABLED")


def _key() -> bytes:
    key = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(key) < 32:
        raise GrantError("GRANT_SIGNING_NOT_READY", 503)
    return key.encode("utf-8")


def _owner_hash(email: str) -> str:
    return hmac.new(
        _key(), ("vainah-manual-email-v1:" + email).encode(), hashlib.sha256
    ).hexdigest()


def _client_name(grant_id: str) -> str:
    return "vn" + hmac.new(
        _key(), ("vainah-manual-grant-v1:" + grant_id).encode(), hashlib.sha256
    ).hexdigest()[:28]


def _schema(cur) -> None:
    cur.execute(
        "SELECT set_config('lock_timeout', '4000ms', TRUE), "
        "set_config('statement_timeout', '8000ms', TRUE)"
    )
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_manual_grants_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_manual_grants (
            grant_id CHAR(32) PRIMARY KEY,
            owner_hash CHAR(64) NOT NULL,
            client_name VARCHAR(30) NOT NULL UNIQUE,
            days INT NOT NULL CHECK (days IN (1,7,30,90,180,365)),
            devices INT NOT NULL CHECK (devices IN (1,2,3,6)),
            state TEXT NOT NULL CHECK (state IN ('claimed','issued','needs_review')),
            subscription_cipher TEXT,
            expires_at TIMESTAMPTZ,
            email_sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            issued_at TIMESTAMPTZ
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_manual_grants_owner_idx
        ON vainah_manual_grants(owner_hash, created_at DESC)
    """)


def _claim(grant_id: str, owner: str, days: int, devices: int, client_name: str) -> dict | None:
    """Transactionally prevent duplicate grant writes and active duplicates."""
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (owner,))
            cur.execute("""
                SELECT owner_hash, days, devices, state, subscription_cipher, expires_at
                FROM vainah_manual_grants WHERE grant_id = %s
            """, (grant_id,))
            existing = cur.fetchone()
            if existing:
                if (str(existing[0]), existing[1], existing[2]) != (owner, days, devices):
                    raise GrantError("GRANT_ID_MISMATCH")
                if existing[3] == "issued":
                    return {
                        "status": "issued", "days": days, "devices": devices,
                        "expires_at": existing[5].isoformat(),
                        "subscription_url": unseal_live_secret(existing[4]),
                        "already_issued": True,
                    }
                raise GrantError("GRANT_ALREADY_CLAIMED_REVIEW_REQUIRED")
            cur.execute("""
                SELECT state, expires_at FROM vainah_manual_grants
                WHERE owner_hash = %s ORDER BY created_at DESC LIMIT 1
            """, (owner,))
            previous = cur.fetchone()
            if previous and (previous[0] != "issued"
                             or (previous[1] is not None
                                 and previous[1].timestamp() > time.time())):
                raise GrantError("GRANT_RECIPIENT_HAS_ACTIVE_OR_UNCERTAIN_GRANT")
            cur.execute("""
                INSERT INTO vainah_manual_grants
                    (grant_id, owner_hash, client_name, days, devices, state)
                VALUES (%s, %s, %s, %s, %s, 'claimed')
            """, (grant_id, owner, client_name, days, devices))
    except GrantError:
        raise
    except (psycopg.Error, LiveLedgerError, OSError):
        raise GrantError("GRANT_DATABASE_UNAVAILABLE", 503) from None
    return None


def _needs_review(grant_id: str) -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE vainah_manual_grants SET state='needs_review'
                WHERE grant_id=%s AND state='claimed'
            """, (grant_id,))
    except (psycopg.Error, OSError):
        # Keep the existing durable claim locked if the DB is unavailable.
        pass


def _finish(grant_id: str, url: str, expiry: int) -> None:
    try:
        cipher = seal_live_secret(url)
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE vainah_manual_grants
                SET state='issued', subscription_cipher=%s,
                    expires_at=%s, issued_at=now()
                WHERE grant_id=%s AND state='claimed'
                RETURNING grant_id
            """, (cipher, datetime.fromtimestamp(expiry, UTC), grant_id))
            if cur.fetchone() is None:
                raise GrantError("GRANT_CLAIM_LOST")
    except GrantError:
        raise
    except (psycopg.Error, LiveLedgerError, ValueError, OverflowError, OSError):
        raise GrantError("GRANT_SAVE_UNCERTAIN", 503) from None


async def _provision(
    *, client_name: str, days: int, devices: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, int]:
    try:
        settings = panel_settings()
        verifier = panel_tls_verify()
    except H1PanelError:
        raise GrantError("GRANT_PANEL_CONFIGURATION_INVALID", 503) from None
    if settings is None:
        raise GrantError("GRANT_PANEL_NOT_CONFIGURED", 503)
    headers = {"Authorization": "Bearer " + settings.token, "Accept": "application/json"}
    url = settings.origin + "/api/info?" + urlencode({"name": client_name})
    async with httpx.AsyncClient(
        timeout=10, verify=verifier, follow_redirects=False,
        trust_env=False, transport=transport,
    ) as client:
        try:
            before = await client.get(url, headers=headers)
        except httpx.RequestError:
            raise GrantError("GRANT_PRECHECK_UNAVAILABLE", 503) from None
        if before.status_code != 404 or len(before.content) > 100000:
            raise GrantError("GRANT_PRECHECK_NOT_ABSENT")
        try:
            missing = before.json()
        except ValueError:
            raise GrantError("GRANT_PRECHECK_INVALID") from None
        if not isinstance(missing, dict) or missing.get("error") != "user_not_found":
            raise GrantError("GRANT_PRECHECK_INVALID")

        started_at = int(time.time())
        try:
            created = await client.post(
                settings.origin + "/api/create", headers=headers,
                json={"name": client_name, "days": days, "device_limit": devices},
            )
        except httpx.RequestError:
            raise GrantError("GRANT_WRITE_UNCERTAIN", 503) from None
        if len(created.content) > 100000 or created.status_code not in (200, 201):
            raise GrantError("GRANT_WRITE_REJECTED_REVIEW_REQUIRED")
        try:
            response = created.json()
        except ValueError:
            raise GrantError("GRANT_WRITE_UNCERTAIN", 503) from None
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise GrantError("GRANT_WRITE_REJECTED_REVIEW_REQUIRED")
        try:
            checked = await client.get(url, headers=headers)
        except httpx.RequestError:
            raise GrantError("GRANT_POSTCHECK_UNCERTAIN", 503) from None
        if checked.status_code != 200 or len(checked.content) > 100000:
            raise GrantError("GRANT_POSTCHECK_UNCERTAIN", 503)
        try:
            record = _client(checked.json(), client_name)
            expiry = _expiry(record)
            limit = record.get("device_limit")
            link = _validate_subscription_url(
                record.get("subscription_url") or record.get("sub_url")
            )
            disabled = _disabled(record)
        except (ValueError, TypeError, KeyError, LiveH1Error):
            raise GrantError("GRANT_POSTCHECK_INVALID") from None
        if (expiry < started_at + days * 86400 - 300
                or type(limit) is not int or limit != devices or disabled):
            raise GrantError("GRANT_POSTCHECK_INVALID")
        return link, expiry


def _find(grant_id: str) -> dict:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT state, days, devices, subscription_cipher, expires_at, email_sent_at
                FROM vainah_manual_grants WHERE grant_id=%s
            """, (grant_id,))
            row = cur.fetchone()
    except (psycopg.Error, OSError):
        raise GrantError("GRANT_DATABASE_UNAVAILABLE", 503) from None
    if row is None:
        raise GrantError("GRANT_NOT_FOUND", 404)
    result = {
        "status": row[0], "days": row[1], "devices": row[2],
        "expires_at": row[4].isoformat() if row[4] else None,
        "email_sent": bool(row[5]),
    }
    if row[0] == "issued":
        try:
            result["subscription_url"] = _validate_subscription_url(
                unseal_live_secret(row[3])
            )
        except (LiveH1Error, LiveLedgerError):
            raise GrantError("GRANT_SECRET_UNAVAILABLE", 503) from None
    return result


async def issue_grant(
    *, email: str, grant_id: str, days: int, devices: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    if not GRANT_ID_RE.fullmatch(grant_id) or days not in ALLOWED_DAYS or devices not in ALLOWED_DEVICES:
        raise GrantError("GRANT_REQUEST_INVALID", 422)
    email = normalize_email(email)
    owner = _owner_hash(email)
    name = _client_name(grant_id)
    existing = _claim(grant_id, owner, days, devices, name)
    if existing is not None:
        return existing
    try:
        link, expiry = await _provision(
            client_name=name, days=days, devices=devices, transport=transport
        )
        _finish(grant_id, link, expiry)
    except BaseException:
        _needs_review(grant_id)
        raise
    email_sent = False
    try:
        escaped = html.escape(link, quote=True)
        await send_email(
            email,
            "Vainah VPN — подписка выдана",
            "<h2>Vainah VPN</h2><p>Для тебя оформлена подписка без оплаты.</p>"
            + "<p>Срок: " + str(days) + " дн. Устройств: " + str(devices) + ".</p>"
            + '<p><a href="' + escaped + '">Открыть личную подписку</a></p>'
            + "<p>Можно также войти в Vainah VPN по этой почте. "
              "Не передавай ссылку посторонним.</p>",
            idempotency_key="manual-grant/" + grant_id,
        )
        email_sent = True
        try:
            with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE vainah_manual_grants SET email_sent_at=now() WHERE grant_id=%s",
                    (grant_id,),
                )
        except (psycopg.Error, OSError):
            pass  # Issued subscription remains valid.
    except (HTTPException, ValueError):
        pass  # Email outage never undoes a successful H1 issuance.
    return {
        "status": "issued", "days": days, "devices": devices,
        "expires_at": datetime.fromtimestamp(expiry, UTC).isoformat(),
        "subscription_url": link, "email_sent": email_sent,
        "already_issued": False,
    }


def _http_error(exc: GrantError) -> HTTPException:
    return HTTPException(exc.status, exc.code)


@router.get("/status")
def status(
    x_sandbox_token: str | None = Header(default=None),
    x_live_pilot_token: str | None = Header(default=None),
):
    _authorized(x_sandbox_token, x_live_pilot_token)
    try:
        database_url()
        _key()
        settings = panel_settings()
        panel_tls_verify()
    except (HTTPException, GrantError, H1PanelError):
        return {"ready": False, "reason": "GRANT_CONFIGURATION_INCOMPLETE"}
    return {
        "ready": settings is not None,
        "days": sorted(ALLOWED_DAYS), "devices": sorted(ALLOWED_DEVICES),
        "note": "Ручная выдача без списания и без изменения оплаченных заказов.",
    }


@router.post("/issue")
async def issue(
    body: GrantRequest,
    request: Request,
    x_sandbox_token: str | None = Header(default=None),
    x_live_pilot_token: str | None = Header(default=None),
):
    _authorized(x_sandbox_token, x_live_pilot_token)
    require_same_origin(request)
    if body.confirm is not True:
        raise HTTPException(422, "GRANT_CONFIRM_REQUIRED")
    try:
        return {"grant_id": body.grant_id, **(await issue_grant(
            email=body.recipient_email, grant_id=body.grant_id,
            days=body.days, devices=body.devices,
        ))}
    except GrantError as exc:
        raise _http_error(exc) from None


@router.get("/{grant_id}")
def get_grant(
    grant_id: str,
    x_sandbox_token: str | None = Header(default=None),
    x_live_pilot_token: str | None = Header(default=None),
):
    _authorized(x_sandbox_token, x_live_pilot_token)
    if not GRANT_ID_RE.fullmatch(grant_id):
        raise HTTPException(404, "GRANT_NOT_FOUND")
    try:
        return {"grant_id": grant_id, **_find(grant_id)}
    except GrantError as exc:
        raise _http_error(exc) from None


@customer_router.get("/manual-grant")
async def customer_manual_grant(request: Request) -> dict:
    """Verified email ownership only; never confuse a grant with paid orders."""
    email = current_email(request)
    if not email:
        raise HTTPException(401, "VERIFIED_EMAIL_LOGIN_REQUIRED")
    try:
        owner = _owner_hash(email)
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT client_name, days, devices, expires_at, subscription_cipher
                FROM vainah_manual_grants
                WHERE owner_hash=%s AND state='issued'
                ORDER BY created_at DESC LIMIT 1
            """, (owner,))
            row = cur.fetchone()
        if not row:
            return {"available": False}
        client_name, days, devices, expiry, cipher = row
        if expiry is None or expiry.timestamp() <= time.time():
            return {"available": False}
        checked = await read_h1_issued_client_status(client_name)
        if not checked.get("active"):
            return {"available": False}
        url = _validate_subscription_url(unseal_live_secret(cipher))
        return {
            "available": True, "days": days, "devices": devices,
            "expires_at": checked.get("expires_at"), "subscription_url": url,
            "gifted": True, "paid": False,
        }
    except (psycopg.Error, LiveLedgerError, H1PanelError, LiveH1Error, OSError):
        raise HTTPException(503, "MANUAL_GRANT_ACCESS_UNAVAILABLE") from None
