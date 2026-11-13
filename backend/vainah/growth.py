"""Verified-email referral tracking, rewards preview and gift drafts.

Financial benefits are intentionally NOT issued here. Purchases stay inside
the audited RollyPay -> H1Cloud path. No customer endpoint can mark a charge
paid, mint a voucher or extend a VPN subscription.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

import psycopg
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from .customer_portal import PLAN_LABELS
from .email_auth import current_email
from .email_delivery import database_url, verified_email
from .live_checkout import owner_ref_for_email
from .live_ledger import PostgresLiveOrderLedger
from .telegram_auth import current_user, require_same_origin

router = APIRouter(prefix="/api/account/growth", tags=["Referral and gift drafts"])
CODE_PATTERN = re.compile(r"^VN[A-F0-9]{18}$")
DRAFT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,40}$")


class ReferralClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=20, max_length=20)


class GiftDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=2, max_length=24)


def _email(request: Request) -> str:
    email = current_email(request)
    if not email:
        telegram = current_user(request)
        if telegram:
            email = verified_email(telegram["telegram_id"])
    if not email:
        raise HTTPException(401, "VERIFIED_EMAIL_REQUIRED")
    return email.strip().lower()


def _secret() -> str:
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "GROWTH_UNAVAILABLE")
    return secret


def _owner(email: str) -> str:
    return hmac.new(
        _secret().encode(), ("vainah-growth-owner-v1:" + email).encode(),
        hashlib.sha256,
    ).hexdigest()


def _code(email: str) -> str:
    return "VN" + hmac.new(
        _secret().encode(), ("vainah-referral-code-v1:" + email).encode(),
        hashlib.sha256,
    ).hexdigest().upper()[:18]


def _schema(cur) -> None:
    cur.execute("""
        SELECT set_config('lock_timeout','4000ms',TRUE),
               set_config('statement_timeout','8000ms',TRUE)
    """)
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_growth_schema_v1'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_growth_referrers (
            referral_code VARCHAR(20) PRIMARY KEY,
            owner_hash CHAR(64) UNIQUE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_growth_invites (
            invitee_owner CHAR(64) PRIMARY KEY,
            invitee_live_ref VARCHAR(67) UNIQUE NOT NULL,
            referrer_owner CHAR(64) NOT NULL,
            referral_code VARCHAR(20) NOT NULL
                REFERENCES vainah_growth_referrers(referral_code),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT no_self_referral CHECK (invitee_owner <> referrer_owner)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_growth_invites_referrer
        ON vainah_growth_invites(referrer_owner, created_at DESC)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_gift_drafts (
            draft_id VARCHAR(40) PRIMARY KEY,
            owner_hash CHAR(64) NOT NULL,
            plan_id VARCHAR(24) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_gift_drafts_owner
        ON vainah_gift_drafts(owner_hash, created_at DESC)
    """)


def _register(cur, owner: str, code: str) -> None:
    cur.execute("""
        INSERT INTO vainah_growth_referrers(referral_code, owner_hash)
        VALUES (%s,%s) ON CONFLICT (referral_code) DO NOTHING
    """, (code, owner))


def _db_error() -> HTTPException:
    return HTTPException(503, "GROWTH_DATABASE_UNAVAILABLE")


def _overview(email: str) -> dict:
    owner = _owner(email)
    code = _code(email)
    live_ref = owner_ref_for_email(email)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            _register(cur, owner, code)
            # The purchase ledger is authoritative for a paid+delivered
            # invoice, excluding demo/pilot transactions and reversals.
            PostgresLiveOrderLedger._schema(cur)
            cur.execute("""
                SELECT COUNT(*)
                FROM vainah_live_orders
                WHERE payment_state='paid' AND is_pilot=FALSE
                  AND is_discount_pilot=FALSE
                  AND (
                    (owner_ref=%s AND is_gift=FALSE
                      AND delivery_state='delivered')
                    OR (gift_buyer_ref=%s AND is_gift=TRUE
                      AND webhook_at IS NOT NULL)
                  )
            """, (live_ref, live_ref))
            purchases = int(cur.fetchone()[0])
            cur.execute("""
                SELECT COUNT(*), COUNT(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1 FROM vainah_live_orders o
                        WHERE o.payment_state='paid'
                          AND o.is_pilot=FALSE
                          AND o.is_discount_pilot=FALSE
                          AND (
                            (o.owner_ref=i.invitee_live_ref AND o.is_gift=FALSE
                              AND o.delivery_state='delivered')
                            OR (o.gift_buyer_ref=i.invitee_live_ref
                              AND o.is_gift=TRUE
                              AND o.webhook_at IS NOT NULL)
                          )
                    )
                )
                FROM vainah_growth_invites i
                WHERE i.referrer_owner=%s
            """, (owner,))
            invited, qualified = (int(v) for v in cur.fetchone())
            cur.execute("""
                SELECT referral_code FROM vainah_growth_invites
                WHERE invitee_owner=%s
            """, (owner,))
            row = cur.fetchone()
            cur.execute("""
                SELECT draft_id,plan_id,created_at FROM vainah_gift_drafts
                WHERE owner_hash=%s ORDER BY created_at DESC LIMIT 10
            """, (owner,))
            drafts = [{
                "id": r[0], "plan_id": r[1],
                "plan_title": PLAN_LABELS.get(r[1], ("Подписка", 3))[0],
                "created_at": r[2].isoformat(),
                "status": "draft_unpaid",
            } for r in cur.fetchall()]
    except psycopg.Error:
        raise _db_error() from None
    # Non-redeemable preview, no financial or promotional liability created.
    return {
        "referral_code": code,
        "share_path": "/referrals.html?ref=" + code,
        "invited_count": invited,
        "qualified_paid_count": qualified,
        "joined_referral": row[0] if row else None,
        "eligible_purchase_count": purchases,
        "potential_points": purchases * 10 + qualified * 25,
        "redeemable_points": 0,
        "redemption_enabled": False,
        "gift_checkout_enabled": False,
        "drafts": drafts,
        "message": "Бонусы — предварительный расчёт. Начисления и обмен выключены.",
    }


def _claim(email: str, code: str) -> None:
    owner = _owner(email)
    live_ref = owner_ref_for_email(email)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            PostgresLiveOrderLedger._schema(cur)
            cur.execute("SELECT owner_hash FROM vainah_growth_referrers WHERE referral_code=%s", (code,))
            result = cur.fetchone()
            if not result:
                raise HTTPException(404, "REFERRAL_CODE_NOT_FOUND")
            referrer = str(result[0]).strip()
            if hmac.compare_digest(referrer, owner):
                raise HTTPException(409, "REFERRAL_SELF_INVITE")
            # Attribution must precede checkout, including a pending
            # reservation/invoice. Do not allow last-second or retrospective
            # claim on an account that has already entered checkout.
            cur.execute("""
                SELECT 1 FROM vainah_live_orders
                WHERE owner_ref=%s LIMIT 1
            """, (live_ref,))
            if cur.fetchone():
                raise HTTPException(409, "REFERRAL_ALREADY_CUSTOMER")
            cur.execute("""
                INSERT INTO vainah_growth_invites (
                    invitee_owner,invitee_live_ref,referrer_owner,referral_code
                ) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING invitee_owner
            """, (owner, live_ref, referrer, code))
            if cur.fetchone() is None:
                raise HTTPException(409, "REFERRAL_ALREADY_CLAIMED")
    except psycopg.Error:
        raise _db_error() from None


def _save_draft(email: str, plan_id: str) -> dict:
    if plan_id not in PLAN_LABELS:
        raise HTTPException(422, "GIFT_PLAN_NOT_AVAILABLE")
    owner = _owner(email)
    draft_id = secrets.token_urlsafe(18)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 399)", (owner,))
            cur.execute("""
                SELECT COUNT(*) FROM vainah_gift_drafts
                WHERE owner_hash=%s AND created_at > now()-interval '1 day'
            """, (owner,))
            if cur.fetchone()[0] >= 5:
                raise HTTPException(429, "GIFT_DAILY_DRAFT_LIMIT")
            cur.execute("""
                INSERT INTO vainah_gift_drafts(draft_id,owner_hash,plan_id)
                VALUES (%s,%s,%s)
            """, (draft_id, owner, plan_id))
    except psycopg.Error:
        raise _db_error() from None
    return {
        "id": draft_id,
        "status": "draft_unpaid",
        "plan_id": plan_id,
        "plan_title": PLAN_LABELS[plan_id][0],
        "checkout_available": False,
        "redeemable": False,
    }


@router.get("")
def overview(request: Request) -> dict:
    return _overview(_email(request))


@router.post("/referrals/claim", status_code=status.HTTP_201_CREATED)
def claim_referral(request: Request, body: ReferralClaim) -> dict:
    require_same_origin(request)
    email = _email(request)
    code = body.code.strip().upper()
    if not CODE_PATTERN.fullmatch(code):
        raise HTTPException(422, "REFERRAL_CODE_INVALID")
    _claim(email, code)
    return {"linked": True, "reward_issued": False}


@router.post("/gifts/drafts", status_code=status.HTTP_201_CREATED)
def create_gift_draft(request: Request, body: GiftDraftInput) -> dict:
    require_same_origin(request)
    return _save_draft(_email(request), body.plan_id)
