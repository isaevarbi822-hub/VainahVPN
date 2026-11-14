"""Read-only public availability and SEO audit for Vainah VPN.

Run: python scripts/audit_public_site.py
Only GET requests to the five explicitly allowlisted public endpoints.
Never logs response bodies, secrets, or customer data.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SITE = "https://vainahvpn.onrender.com"
BACKEND = "https://vainahvpn-python-preview.onrender.com"
CHECKS = (
    (SITE + "/", "html"),
    (SITE + "/robots.txt", "robots"),
    (SITE + "/sitemap.xml", "sitemap"),
    (BACKEND + "/api/health", "health"),
    (BACKEND + "/api/shop/config", "config"),
)


def validate(kind: str, data: bytes, content_type: str) -> str | None:
    """Return a short, non-sensitive failure description, or None."""
    if kind == "html":
        if "html" not in content_type.lower() or b"<html" not in data.lower():
            return "Expected HTML response"
    elif kind == "robots":
        if "Allow: /" not in data.decode("utf-8", "replace").splitlines():
            return "Missing Allow: /"
    elif kind == "sitemap":
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return "Invalid sitemap XML"
        if not any((node.text or "").startswith(SITE + "/")
                   for node in root.iter() if node.tag.endswith("loc")):
            return "Sitemap has no public site URL"
    elif kind == "health":
        if not data.strip():
            return "Empty health response"
    elif kind == "config":
        try:
            config = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return "Invalid config JSON"
        if not isinstance(config, dict) or type(config.get("checkout_ready")) is not bool:
            return "Missing boolean checkout_ready"
        # false is a valid readiness state, not an availability failure.
    return None


def check(url: str, kind: str, attempts: int = 2, delay: float = 3.0) -> tuple[str, str]:
    last = "No response"
    for attempt in range(attempts):
        if attempt:
            time.sleep(delay)
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "VainahPublicReadOnlyAudit/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=25) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                body = response.read(1024 * 1024 + 1)
            if status != 200:
                last = f"HTTP {status}"
            elif len(body) > 1024 * 1024:
                last = "Response exceeds 1 MiB"
            else:
                failure = validate(kind, body, content_type)
                if failure is None:
                    return "OK", "HTTP 200; content validated"
                last = failure
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Never print exception text: URLs or headers may be included.
            last = type(exc).__name__
    return "UNCONFIRMED", last


def main() -> int:
    failures = 0
    for url, kind in CHECKS:
        state, detail = check(url, kind)
        print(f"{state}: {url} — {detail}")
        failures += state != "OK"
    if failures:
        print("Some checks were inconclusive or failed; investigate before alerting.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
