"""H1Cloud node write adapter for operator-verified, single-claim LIVE orders.

NOT hooked into public checkout or live webhook. The H1Cloud node's exact
/api/create and /api/edit contract must be approved against the owner's node
before a trusted worker can set write_contract_approved=True.

No automatic retries after a write attempt: PATCH /edit is additive in common
H1 node APIs and retrying after a network timeout can double-extend service.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx

from .billing import get_plan
from .h1_panel import H1PanelError, panel_settings
from .live_ledger import PendingLiveOrder
from .production_contracts import LIVE_ORDER_RE, H1ProvisionIntent


class LiveH1Error(Exception):
    """Sanitized error code; never contain H1Cloud key or subscription link."""


@dataclass(frozen=True)
class LiveH1Proof:
    name: str
    expires_at: int
    subscription_url: str


def _validate_subscription_url(value: object) -> str:
    if not isinstance(value, str) or not 10 <= len(value) <= 2048:
        raise LiveH1Error("H1_SUBSCRIPTION_UNAVAILABLE")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise LiveH1Error("H1_SUBSCRIPTION_UNAVAILABLE") from None
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment
            or re.search(r"\s", value)):
        raise LiveH1Error("H1_SUBSCRIPTION_UNAVAILABLE")
    return value


def _client(record: object, expected_name: str) -> dict:
    if not isinstance(record, dict) or record.get("ok") is not True:
        raise LiveH1Error("H1_RESPONSE_INVALID")
    obj = record.get("client")
    if not isinstance(obj, dict) or obj.get("name") != expected_name:
        raise LiveH1Error("H1_CUSTOMER_MISMATCH")
    return obj


class LiveH1CloudNode:
    """Performs exactly one intended write after an explicit durable claim."""

    def __init__(
        self, *, transport: httpx.AsyncBaseTransport | None = None,
        write_contract_approved: bool = False,
    ):
        self.transport = transport
        self.write_contract_approved = write_contract_approved

    async def provision_once(
        self, *, claim: PendingLiveOrder, intent: H1ProvisionIntent,
        operation: str,
    ) -> LiveH1Proof:
        if (not self.write_contract_approved
                or claim.delivery_state != "claimed"
                or claim.payment_state != "paid"
                or not LIVE_ORDER_RE.fullmatch(claim.order_id)
                or operation not in {"create", "extend"}):
            raise LiveH1Error("H1_PROVISIONING_DISABLED")
        plan = get_plan(claim.plan_id)
        if (not re.fullmatch(r"vn[0-9a-f]{28}", intent.client_name)
                or plan is None or intent.days != plan["days"]
                or intent.devices != plan["devices"]):
            raise LiveH1Error("H1_INTENT_INVALID")
        try:
            settings = panel_settings()
        except H1PanelError:
            raise LiveH1Error("H1_CONFIGURATION_INVALID") from None
        if settings is None:
            raise LiveH1Error("H1_NOT_CONFIGURED")
        headers = {
            "Authorization": "Bearer " + settings.token,
            "Accept": "application/json",
        }
        base = settings.origin
        path = "/api/clients/" + quote(intent.client_name, safe="")
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False,
            transport=self.transport,
        ) as session:
            # Before a write, verify whether the node already has this account.
            # We do not fabricate subscription URLs or claim the VPN is active.
            try:
                before = await session.get(base + path, headers=headers)
            except (httpx.RequestError, httpx.TimeoutException):
                raise LiveH1Error("H1_PRECHECK_UNAVAILABLE") from None
            if len(before.content) > 100000:
                raise LiveH1Error("H1_RESPONSE_INVALID")
            old_expiry = 0
            if operation == "create":
                if before.status_code != 404:
                    raise LiveH1Error("H1_CREATE_REQUIRES_ABSENT_USER")
                try:
                    body = before.json()
                except ValueError:
                    raise LiveH1Error("H1_PRECHECK_INVALID") from None
                if not isinstance(body, dict) or body.get("error") != "user_not_found":
                    raise LiveH1Error("H1_PRECHECK_INVALID")
                verb, endpoint = "POST", "/api/create"
                payload = intent.create_payload()
            else:
                if before.status_code != 200:
                    raise LiveH1Error("H1_EXTEND_REQUIRES_EXISTING_USER")
                try:
                    record = _client(before.json(), intent.client_name)
                    old_expiry = int(record["expires_at"])
                except (ValueError, KeyError, TypeError):
                    raise LiveH1Error("H1_PRECHECK_INVALID") from None
                verb, endpoint = "PATCH", "/api/edit"
                payload = intent.extend_payload()

            # A network exception here is AMBIGUOUS: node might have committed.
            # We never issue a second POST/PATCH automatically.
            try:
                result = await session.request(
                    verb, base + endpoint, headers=headers, json=payload,
                )
            except (httpx.RequestError, httpx.TimeoutException):
                raise LiveH1Error("H1_WRITE_UNCERTAIN_MANUAL_REVIEW") from None
            if not 200 <= result.status_code < 300:
                raise LiveH1Error("H1_WRITE_REJECTED_MANUAL_REVIEW")
            if len(result.content) > 100000:
                raise LiveH1Error("H1_WRITE_UNCERTAIN_MANUAL_REVIEW")
            try:
                write_body = result.json()
            except ValueError:
                raise LiveH1Error("H1_WRITE_UNCERTAIN_MANUAL_REVIEW") from None
            if not isinstance(write_body, dict) or write_body.get("ok") is not True:
                raise LiveH1Error("H1_WRITE_REJECTED_MANUAL_REVIEW")

            # Read after write and use only the result from our exact user.
            try:
                after = await session.get(base + path, headers=headers)
            except (httpx.RequestError, httpx.TimeoutException):
                raise LiveH1Error("H1_POSTCHECK_UNCERTAIN_MANUAL_REVIEW") from None
            if after.status_code != 200 or len(after.content) > 100000:
                raise LiveH1Error("H1_POSTCHECK_UNCERTAIN_MANUAL_REVIEW")
            try:
                account = _client(after.json(), intent.client_name)
                expiry = int(account["expires_at"])
            except (ValueError, TypeError, KeyError):
                raise LiveH1Error("H1_POSTCHECK_UNCERTAIN_MANUAL_REVIEW") from None
            if expiry <= max(int(time.time()), old_expiry):
                raise LiveH1Error("H1_POSTCHECK_UNCERTAIN_MANUAL_REVIEW")
            device_limit = account.get("device_limit")
            if type(device_limit) is not int or device_limit != intent.devices:
                raise LiveH1Error("H1_DEVICE_LIMIT_UNVERIFIED_MANUAL_REVIEW")
            url = _validate_subscription_url(
                account.get("subscription_url") or account.get("sub_url")
            )
            return LiveH1Proof(intent.client_name, expiry, url)
