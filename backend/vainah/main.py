"""Vainah VPN preview API.

All customer-specific endpoints are deliberately absent until authorization exists.
Do not put tokens, VLESS keys or subscription URLs in logs.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import auth_public_config
from .auth import router as auth_router
from .billing import router as shop_router
from .config import Settings, deployment_commit
from .customer_portal import router as customer_router
from .db_health import database_status
from .email_auth import router as email_auth_router
from .google_auth import router as google_auth_router
from .h1_panel import public_h1_status
from .h1_panel import router as h1_router
from .h1_trial import router as h1_trial_router
from .inspector import InvalidSubscription, inspect_subscription
from .integration_status import integration_status
from .public_trial import router as public_trial_router
from .speedtest import router as speedtest_router
from .subscription_qr import router as qr_router
from .support_tickets import router as support_router
from .telegram_auth import router as telegram_router
from .telegram_oidc import router as telegram_oidc_router

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
STORE_DIR = ROOT / "storefront"
settings = Settings.from_env()

app = FastAPI(title="Vainah VPN", version=settings.version, docs_url="/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
app.include_router(shop_router)
app.include_router(auth_router)
app.include_router(h1_router)
app.include_router(h1_trial_router)
app.include_router(telegram_router)
app.include_router(telegram_oidc_router)
app.include_router(email_auth_router)
app.include_router(google_auth_router)
app.include_router(customer_router)
app.include_router(public_trial_router)
app.include_router(speedtest_router)
app.include_router(qr_router)
app.include_router(support_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    # Historical storefront uses inline page scripts and style attributes.
    # Checkout API, billing credentials and web dashboard remain separate.
    if request.url.path in {
        "/support-operator.html",
        "/support-operator.js",
        "/support-center.js",
        "/support-center.css",
        "/operator-pilot.html",
        "/operator-pilot.js",
        "/operator-pilot.css",
        "/operations.html",
        "/operations.css",
        "/operations.js",
        "/trial.html",
        "/trial.js",
        "/trial.css",
    }:
        # No inline JS/CSS or external assets on the token-entry page.
        # Static HTML is public, but both billing endpoints require operator
        # secrets, a verified email cookie, and the server-side pilot gates.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    elif request.url.path == "/api/account/qr":
        # The generated SVG contains a subscriber secret; never allow active
        # SVG content or search indexing, even if the client opens it directly.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'none'; object-src 'none'; sandbox"
        )
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    elif request.url.path == "/" or request.url.path.endswith(".html"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' "
            "https://telegram.org https://oauth.telegram.org; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
            "connect-src 'self'; frame-src https://oauth.telegram.org; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    # Browser caches can preserve disabled Telegram Login JavaScript after deploy.
    # Auth pages and scripts always need the currently deployed revision.
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path in {
        "/support-center.html",
        "/support-operator.html",
        "/support-operator.js",
        "/account.html",
        "/account-login.js",
        "/account-dashboard.js",
        "/telegram-login-widget.js",
        "/operator-pilot.html",
        "/operator-pilot.js",
        "/operator-pilot.css",
        "/operations.html",
        "/operations.css",
        "/operations.js",
    }:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    elif request.url.path.endswith((".css", ".js", ".mjs", ".svg", ".png", ".jpg", ".jpeg", ".webp")):
        # Public static resources can use Starlette's ETag/Last-Modified
        # revalidation. Paths are unversioned, so never cache them long.
        # Private account, operator and API routes above remain no-store.
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    return response


class ImportRequest(BaseModel):
    content: str = Field(min_length=1, max_length=65536)


@app.get("/app", include_in_schema=False)
async def home():
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/api/health")
async def health():
    return {
        "ok": True, "service": "vainahvpn-api", "version": settings.version,
        "mode": settings.mode, "commit_sha": deployment_commit(),
    }


@app.get("/api/v1/overview")
async def overview():
    return {
        "product": settings.project_name,
        "version": settings.version,
        "mode": settings.mode,
        "account": {"state": "not_connected", "provider": "clerk"},
        "subscription": {"state": "not_connected", "expires_at": None, "devices_used": None},
        "vpn": {"state": "not_available", "engine": "libbox", "connected": False},
        "traffic": {"download_bytes": None, "upload_bytes": None},
        "message": "Деморежим. Аккаунт, H1Cloud и libbox ещё не подключены.",
    }


@app.get("/api/v1/locations")
async def locations():
    # Never fabricate ping, server availability, countries or traffic.
    return {"items": [], "source": "not_connected", "message": "Список появится после подключения H1Cloud."}


@app.get("/api/v1/diagnostics")
async def diagnostics():
    return {
        "checks": [
            {"key": "api", "name": "Python API", "state": "ok", "note": "Сервер отвечает."},
            {"key": "identity", "name": "Авторизация Clerk", "state": "configured" if auth_public_config()["jwt_verification_ready"] else "pending", "note": "Сервер может проверять JWT, вход на сайте пока отключён." if auth_public_config()["jwt_verification_ready"] else "Проверка JWT не настроена."},
            {"key": "provider", "name": "H1Cloud", "state": public_h1_status()["status"], "note": public_h1_status()["message"]},
            {"key": "tunnel", "name": "libbox VPN", "state": "pending", "note": "Нужен нативный клиент и VpnService."},
            {"key": "payments", "name": "Платежи", "state": "disabled", "note": "Отключено до безопасной интеграции."},
        ],
        "vpn_egress_verified": False,
    }


@app.get("/api/v1/platforms")
async def platforms():
    return {
        "items": [
            {"name": "Android", "state": "planned", "detail": "libbox + VpnService"},
            {"name": "iOS / iPadOS", "state": "planned", "detail": "Network Extension + нативный движок"},
            {"name": "Windows", "state": "planned", "detail": "Системный туннель"},
            {"name": "macOS", "state": "planned", "detail": "System Extension"},
            {"name": "Galaxy Watch / Apple Watch", "state": "research", "detail": "Проверка ограничений платформ"},
        ]
    }


@app.post("/api/v1/import/inspect")
async def inspect(body: ImportRequest):
    try:
        return inspect_subscription(body.content)
    except InvalidSubscription as exc:
        # Never echo the user-supplied content in errors.
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/v1/security")
async def security():
    return {
        "tls_verification": True, "payments_enabled": False,
        "user_data_connected": False, "subscription_secrets_stored": False,
        "native_tunnel_attached": False,
    }

@app.get("/api/site/services")
async def public_site_services():
    """Cached read-only API probes; not evidence of user VPN delivery."""
    db = await database_status()
    services = await integration_status()
    return {
        "mode": "preview",
        "services": {
            "api": {"status": "ok", "message": "Python API отвечает."},
            "database": db,
            **services,
            "identity": auth_public_config(),
        },
    }


@app.get("/api/site/locations")
async def public_site_locations():
    return {"locations": [], "source": "not_connected"}


# Public historical website is mounted AFTER the API.
# New standalone dashboard is available at /app.
app.mount("/", StaticFiles(directory=STORE_DIR, html=True), name="storefront")
