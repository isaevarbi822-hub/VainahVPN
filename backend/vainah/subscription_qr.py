"""Private QR for a verified, paid VPN subscription.

The secret stays in a server-rendered QR and is NEVER included in the request
URL, 3rd-party QR APIs, logs or page source. Reuses existing paid owner guard.
"""
from __future__ import annotations

from io import BytesIO

import qrcode
from fastapi import APIRouter, HTTPException, Request, Response
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.svg import SvgPathImage

from .customer_portal import access

router = APIRouter(prefix="/api/account", tags=["Customer QR"])

@router.get("/qr")
async def subscription_qr(request: Request) -> Response:
    result = await access(request)  # Ownership + paid delivery + H1 authorization.
    value = result.get("subscription_url")
    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 2100:
        raise HTTPException(422, "SUBSCRIPTION_QR_UNSUPPORTED")
    try:
        qr = qrcode.QRCode(
            error_correction=ERROR_CORRECT_M, box_size=5, border=4
        )
        qr.add_data(value)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        buffer = BytesIO()
        image.save(buffer)
        raw = buffer.getvalue()
        if not raw or len(raw) > 2_000_000:
            raise ValueError("QR_IMAGE_TOO_LARGE")
    except (ValueError, OverflowError, qrcode.exceptions.DataOverflowError):
        raise HTTPException(422, "SUBSCRIPTION_QR_UNSUPPORTED") from None
    return Response(
        content=raw, media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Content-Disposition": 'inline; filename="vainah-vpn-qr.svg"',
            "Content-Security-Policy": "default-src 'none'; script-src 'none'; sandbox",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
