"""Operator-published public location labels only, never H1Cloud secrets or live claims."""
import json
import os
import re

_NAME_RE = re.compile(r"^[\w\s.,()\-–№]{1,72}$", re.UNICODE)
_IP_RE = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)


def public_locations() -> dict:
    """Return a bounded, display-only directory configured by the operator."""
    raw = os.environ.get("VAINAH_PUBLIC_LOCATIONS_JSON", "").strip()
    if not raw or len(raw) > 8192:
        return {"locations": [], "source": "not_connected"}
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return {"locations": [], "source": "invalid_config"}
    if not isinstance(items, list):
        return {"locations": [], "source": "invalid_config"}
    result = []
    seen = set()
    for item in items[:80]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        flag = item.get("flag", "🌐")
        if not isinstance(name, str) or not isinstance(flag, str):
            continue
        name = name.strip()
        if not _NAME_RE.fullmatch(name) or _IP_RE.search(name) or _UUID_RE.search(name):
            continue
        if not flag or len(flag) > 8 or any(ord(c) < 32 or c in "<>&" for c in flag):
            continue
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        result.append({"name": name, "flag": flag})
        if len(result) == 40:
            break
    return {"locations": result, "source": "operator_published",
            "availability_verified": False}
