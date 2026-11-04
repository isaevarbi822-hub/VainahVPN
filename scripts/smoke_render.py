"""Read-only/public-contract smoke check for Vainah VPN.

Run: py -3 scripts/smoke_render.py
Use --base-url https://your-domain.tld after attaching a custom domain.
No API keys, cookies, sandbox tokens, payment links or provider calls are used.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_BASE = "https://vainahvpn-python-preview.onrender.com"


def fetch(base: str, path: str, *, method: str = "GET",
          payload: dict | None = None) -> tuple[int, bytes]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        base + path, data=data, method=method,
        headers={"Accept": "application/json",
                 **({"Content-Type": "application/json"} if data else {})},
    )
    try:
        with urlopen(req, timeout=35) as result:
            return result.status, result.read(256_001)
    except HTTPError as error:
        # Never print response bodies: they could contain private data.
        error.close()
        return error.code, b""


def main() -> int:
    parser = argparse.ArgumentParser(description="Vainah VPN public smoke check")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    url = urlsplit(base)
    if (url.scheme != "https" or not url.hostname or url.username
            or url.password or url.query or url.fragment or url.path):
        parser.error("Use an HTTPS origin such as https://example.com")
    failures: list[str] = []

    def check(label: str, path: str, expected: int,
              predicate=None, *, method: str = "GET",
              payload: dict | None = None) -> dict | None:
        try:
            status, body = fetch(base, path, method=method, payload=payload)
            valid = status == expected
            value = None
            if valid and predicate is not None:
                value = json.loads(body)
                valid = isinstance(value, dict) and predicate(value)
            print(("[OK] " if valid else "[FAIL] ") +
                  f"{label}: HTTP {status} (expected {expected})")
            if not valid:
                failures.append(label)
            return value
        except (URLError, OSError, ValueError, json.JSONDecodeError):
            print(f"[FAIL] {label}: request or JSON validation error")
            failures.append(label)
            return None

    check("Homepage", "/", 200)
    check("Checkout page", "/checkout.html", 200)
    check("Dashboard preview", "/app", 200)
    check("API health", "/api/health", 200,
          lambda x: x.get("ok") is True)
    check("Six server-priced tariffs", "/api/shop/plans", 200,
          lambda x: x.get("currency") == "RUB"
          and isinstance(x.get("items"), list)
          and len(x["items"]) == 6
          and {str(p.get("id")) for p in x["items"]} ==
          {"30", "60", "90", "180", "365", "365-family"})
    config = check("Checkout safely disabled", "/api/shop/config", 200,
                   lambda x: x.get("checkout_ready") is False
                   and x.get("sandbox_available") is False)
    check("Database reachable", "/api/site/services", 200,
          lambda x: x.get("services", {}).get("database", {})
          .get("status") == "ok")
    check("Sandbox operator-only", "/api/shop/sandbox/orders", 401)
    check("VPN and charge features off", "/api/v1/security", 200,
          lambda x: x.get("payments_enabled") is False
          and x.get("native_tunnel_attached") is False)
    if config and config.get("checkout_ready") is False:
        # Only invoke this disabled endpoint when config proves that
        # production checkout is switched off.
        check("Public checkout rejects payment", "/api/shop/checkout",
              503, method="POST", payload={"plan": "30"})
    else:
        print("[SKIP] Public checkout: not proven disabled")
        failures.append("Unsafe checkout configuration")

    if failures:
        print(f"\nFAIL: {len(failures)} checks need attention.")
        return 1
    print("\nPASS: all public deployment checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
