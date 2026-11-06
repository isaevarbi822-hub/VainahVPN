"""Private customer-managed device labels, NOT live H1Cloud device sessions.

No H1Cloud device endpoint is available in the verified integration contract.
Removing a row here never disconnects VPN traffic or changes quota.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime
from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from .customer_portal import portal_identity
from .email_delivery import database_url
from .telegram_auth import require_same_origin

router = APIRouter(prefix="/api/account/devices", tags=["Customer device labels"])
MAX_DEVICES = 12
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{20,32}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class DeviceRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    platform: Literal["android", "ios", "windows", "macos", "linux", "other"]


def _owner(request: Request) -> str:
    telegram_id, email, _method = portal_identity(request, include_email=True)
    secret = os.environ.get("SESSION_SIGNING_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "DEVICE_REGISTRY_NOT_CONFIGURED")
    # Email and Telegram sessions share only a server-verified Telegram link.
    if telegram_id is not None:
        principal = "telegram:" + telegram_id
    elif email:
        principal = "email:" + email
    else:
        raise HTTPException(401, "ACCOUNT_LOGIN_REQUIRED")
    return hmac.new(
        secret.encode(), ("vainah-device-labels-v1\n" + principal).encode(),
        hashlib.sha256,
    ).hexdigest()


def _schema(cur) -> None:
    cur.execute(
        "SELECT set_config('lock_timeout','4000ms',TRUE),"
        " set_config('statement_timeout','8000ms',TRUE)"
    )
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('vainah_device_label_schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vainah_device_labels (
            device_id VARCHAR(32) PRIMARY KEY,
            owner_hash CHAR(64) NOT NULL,
            device_name VARCHAR(40) NOT NULL,
            platform VARCHAR(12) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT vainah_device_platform_valid CHECK (
                platform IN ('android','ios','windows','macos','linux','other')
            )
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS vainah_device_labels_owner_idx
        ON vainah_device_labels (owner_hash, created_at DESC)
    """)


def _entry(row: tuple) -> dict:
    created = row[3]
    return {
        "id": str(row[0]),
        "name": str(row[1]),
        "platform": str(row[2]),
        "created_at": created.isoformat() if isinstance(created, datetime) else None,
    }


def _read(owner: str) -> list[dict]:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                SELECT device_id, device_name, platform, created_at
                FROM vainah_device_labels WHERE owner_hash=%s
                ORDER BY created_at DESC, device_id DESC LIMIT 12
            """, (owner,))
            return [_entry(row) for row in cur.fetchall()]
    except psycopg.Error:
        raise HTTPException(503, "DEVICE_REGISTRY_UNAVAILABLE") from None


def _create(owner: str, name: str, platform: str) -> dict:
    device_id = secrets.token_urlsafe(18)
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            # Serialize writes per owner so the maximum cannot be bypassed
            # through parallel requests or duplicate browser tabs.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 98127)", (owner,))
            cur.execute("""
                SELECT count(*) FROM vainah_device_labels WHERE owner_hash=%s
            """, (owner,))
            if cur.fetchone()[0] >= MAX_DEVICES:
                raise HTTPException(409, "DEVICE_REGISTRY_LIMIT")
            cur.execute("""
                INSERT INTO vainah_device_labels (
                    device_id, owner_hash, device_name, platform
                ) VALUES (%s,%s,%s,%s)
            """, (device_id, owner, name, platform))
    except psycopg.Error:
        raise HTTPException(503, "DEVICE_REGISTRY_UNAVAILABLE") from None
    return {"id": device_id, "name": name, "platform": platform}


def _rename(owner: str, device_id: str, name: str) -> bool:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                UPDATE vainah_device_labels SET device_name=%s
                WHERE owner_hash=%s AND device_id=%s
                RETURNING device_id
            """, (name, owner, device_id))
            return cur.fetchone() is not None
    except psycopg.Error:
        raise HTTPException(503, "DEVICE_REGISTRY_UNAVAILABLE") from None


def _valid_name(value: str) -> bool:
    return bool(1 <= len(value) <= 40 and not CONTROL_RE.search(value)
        and not re.search(r"(?i)(?:https?://|vless://|vmess://|trojan://)", value))


def _remove(owner: str, device_id: str) -> bool:
    try:
        with psycopg.connect(database_url(), connect_timeout=4) as conn, conn.cursor() as cur:
            _schema(cur)
            cur.execute("""
                DELETE FROM vainah_device_labels
                WHERE owner_hash=%s AND device_id=%s RETURNING device_id
            """, (owner, device_id))
            return cur.fetchone() is not None
    except psycopg.Error:
        raise HTTPException(503, "DEVICE_REGISTRY_UNAVAILABLE") from None


@router.get("")
def devices(request: Request) -> dict:
    return {
        "items": _read(_owner(request)),
        "source": "customer_managed_labels",
        "live_sessions_available": False,
        "record_limit": MAX_DEVICES,
        "message": (
            "Это личный список названий устройств, а не список активных VPN-сессий. "
            "Удаление записи не отключает устройство в H1Cloud."
        ),
    }


@router.get("/limits")
async def verified_device_limits(request: Request) -> dict:
    """Paid plan limit is distinct from saved labels and live device sessions."""
    from .customer_portal import PLAN_LABELS, overview as customer_overview
    owner = _owner(request)
    labels = _read(owner)
    data = await customer_overview(request)
    sub = data.get("subscription") if isinstance(data.get("subscription"), dict) else {}
    limit = None
    if sub.get("paid") is True and sub.get("status") == "delivered":
        candidate = sub.get("device_limit")
        if type(candidate) is int and 1 <= candidate <= 20:
            limit = candidate
    if limit is None:
        orders = data.get("orders") if isinstance(data.get("orders"), list) else []
        for order in orders:
            if isinstance(order, dict) and order.get("paid") is True and order.get("delivered") is True:
                plan = PLAN_LABELS.get(order.get("plan_id"))
                if plan:
                    limit = plan[1]
                    break
    return {
        "plan_device_limit": limit,
        "active_vpn_sessions": None,
        "slots_available": None,
        "saved_labels": len(labels),
        "label_registry_limit": MAX_DEVICES,
        "device_disconnect_supported": False,
        "message": "Лимит тарифа подтверждён заказом, но H1Cloud не предоставляет список активных устройств и освобождение слотов.",
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def register_device(request: Request, body: DeviceInput) -> dict:
    require_same_origin(request)
    owner = _owner(request)
    name = body.name.strip()
    if not _valid_name(name):
        raise HTTPException(422, "DEVICE_NAME_INVALID")
    return _create(owner, name, body.platform)


@router.patch("/{device_id}")
def rename_device(request: Request, device_id: str, body: DeviceRename) -> dict:
    require_same_origin(request)
    owner = _owner(request)
    name = body.name.strip()
    if not DEVICE_RE.fullmatch(device_id):
        raise HTTPException(404, "DEVICE_RECORD_NOT_FOUND")
    if not _valid_name(name):
        raise HTTPException(422, "DEVICE_NAME_INVALID")
    if not _rename(owner, device_id, name):
        raise HTTPException(404, "DEVICE_RECORD_NOT_FOUND")
    return {"renamed": True, "name": name, "vpn_disconnected": False}


@router.delete("/{device_id}")
def delete_device(request: Request, device_id: str) -> dict:
    require_same_origin(request)
    owner = _owner(request)
    if not DEVICE_RE.fullmatch(device_id) or not _remove(owner, device_id):
        raise HTTPException(404, "DEVICE_RECORD_NOT_FOUND")
    return {"removed": True, "vpn_disconnected": False}
