"""Vainah VPN preview API.

All customer-specific endpoints are deliberately absent until authorization exists.
Do not put tokens, VLESS keys or subscription URLs in logs.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .billing import router as shop_router
from .config import Settings
from .db_health import database_status
from .inspector import InvalidSubscription, inspect_subscription

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
STORE_DIR = ROOT / "storefront"
settings = Settings.from_env()

app = FastAPI(title="Vainah VPN", version=settings.version, docs_url="/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
app.include_router(shop_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    # Historical storefront uses inline page scripts and style attributes.
    # Checkout API, billing credentials and web dashboard remain separate.
    if request.url.path == "/" or request.url.path.endswith(".html"):
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
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class ImportRequest(BaseModel):
    content: str = Field(min_length=1, max_length=65536)


@app.get("/app", include_in_schema=False)
async def home():
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "vainahvpn-api", "version": settings.version, "mode": settings.mode}


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
            {"key": "identity", "name": "Авторизация Clerk", "state": "pending", "note": "Проверка JWT не подключена."},
            {"key": "provider", "name": "H1Cloud", "state": "pending", "note": "Не подключён реальный API."},
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
    """Read-only preview status: never probes private H1Cloud or claims live availability."""
    from .billing import sandbox

    db = await database_status()
    return {
        "mode": "preview",
        "services": {
            "api": {
                "status": "ok",
                "message": "Python API отвечает.",
            },
            "database": db,
            "h1": {
                "status": "not_connected",
                "message": "Панель H1Cloud пока не подключена к этому сайту. Состояние VPN-серверов неизвестно.",
            },
            "rollypay": {
                "status": "sandbox" if sandbox.mode == "mock" else "not_verified",
                "message": (
                    "Доступна только локальная симуляция. Реальных списаний нет."
                    if sandbox.mode == "mock"
                    else "Тестовый режим провайдера выбран; связь с кассой здесь не проверялась."
                ),
            },
            "webhook": {
                "status": "not_verified",
                "message": "Подпись вебхука проверяется тестами; реальная доставка не подтверждена.",
            },
        },
    }


@app.get("/api/site/locations")
async def public_site_locations():
    return {"locations": [], "source": "not_connected"}


# Public historical website is mounted AFTER the API.
# New standalone dashboard is available at /app.
app.mount("/", StaticFiles(directory=STORE_DIR, html=True), name="storefront")
