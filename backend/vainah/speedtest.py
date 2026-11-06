"""Small, bounded same-origin browser throughput probe.

Not a carrier-grade speed test: the destination is the Render web service.
No remote hosts, no disk writes, no user secrets and no unrestricted payloads.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/speedtest", tags=["Browser speed test"])

# A single test moves at most ~1.8 MiB total. Shared Free Render instances
# must not become unbounded public traffic amplifiers.
DOWNLOAD_BYTES = 512 * 1024
MAX_UPLOAD_BYTES = 256 * 1024
WINDOW_SECONDS = 60
REQUESTS_PER_WINDOW = 24
MAX_IDENTITIES = 2048
_download_payload = secrets.token_bytes(DOWNLOAD_BYTES)
_lock = asyncio.Lock()
_recent: dict[str, deque[float]] = defaultdict(deque)


async def _allow(request: Request) -> None:
    # Never trust spoofable forwarding headers as a rate-limit identity.
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    async with _lock:
        if len(_recent) > MAX_IDENTITIES:
            for key in list(_recent):
                if not _recent[key] or now - _recent[key][-1] > WINDOW_SECONDS:
                    del _recent[key]
        calls = _recent[address]
        while calls and now - calls[0] >= WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= REQUESTS_PER_WINDOW:
            raise HTTPException(status_code=429, detail="SPEEDTEST_RATE_LIMIT")
        calls.append(now)


@router.get("/ping")
async def ping(request: Request):
    await _allow(request)
    return Response(
        status_code=204,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/download")
async def download(request: Request):
    await _allow(request)
    return Response(
        content=_download_payload,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store, no-transform",
            "Content-Encoding": "identity",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/upload")
async def upload(request: Request):
    await _allow(request)
    length = request.headers.get("content-length")
    if length is None or not length.isdecimal() or int(length) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="SPEEDTEST_UPLOAD_SIZE_INVALID")
    # Stream bounded chunks so a client cannot consume unlimited memory if
    # content-length is incorrect. Reject discrepancies.
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="SPEEDTEST_UPLOAD_TOO_LARGE")
    if total != int(length):
        raise HTTPException(status_code=400, detail="SPEEDTEST_UPLOAD_INCOMPLETE")
    return {"received_bytes": total}
