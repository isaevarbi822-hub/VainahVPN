"""Public tariff showcase: 6 supported paid plans, 5 upcoming ideas, 1 free trial.

This endpoint is marketing metadata ONLY. It cannot reserve a checkout or
grant a subscription. Existing RollyPay and H1Cloud plan allowlists stay
unchanged until new durations/device limits are separately verified.
"""
from __future__ import annotations

from fastapi import APIRouter

from .billing import CATALOG, price_rub

router = APIRouter(prefix="/api/site", tags=["Public tariff catalog"])

# These are proposed prices, NOT approved live RollyPay/H1Cloud contracts.
# Keep experimental plans out of billing.CATALOG and gift-card allowlists.
UPCOMING = (
    {"id": "7", "title": "Неделя", "days": 7, "kopeks": 3900,
     "devices": 3, "category": "personal", "tag": "На короткий срок"},
    {"id": "14", "title": "Две недели", "days": 14, "kopeks": 6500,
     "devices": 3, "category": "personal", "tag": "Гибкий старт"},
    {"id": "45", "title": "Полтора месяца", "days": 45, "kopeks": 13900,
     "devices": 3, "category": "personal", "tag": "Больше месяца"},
    {"id": "120", "title": "Четыре месяца", "days": 120, "kopeks": 27900,
     "devices": 3, "category": "personal", "tag": "Длинный срок"},
    {"id": "30-family", "title": "Семейный месяц", "days": 30,
     "kopeks": 18900, "devices": 6, "category": "family",
     "tag": "Для семьи"},
)
LIVE_TAGS = {
    "30": "Популярный",
    "60": "На каждый день",
    "90": "На три месяца",
    "180": "Экономный",
    "365": "На год",
    "365-family": "Семья на год",
}
ORDER = (
    "trial-free", "7", "14", "30", "45", "60", "90", "120",
    "180", "365", "30-family", "365-family",
)


def public_tariff_catalog() -> dict:
    paid = []
    for plan in CATALOG:
        paid.append({
            "id": plan["id"], "title": plan["title"],
            "days": plan["days"], "devices": plan["devices"],
            "price_rub": price_rub(plan),
            "category": "family" if plan["id"].endswith("-family") else "personal",
            "tag": LIVE_TAGS.get(plan["id"], ""),
            "status": "existing", "checkout_supported": True,
            "checkout_path": "/checkout.html?plan=" + plan["id"],
        })
    for plan in UPCOMING:
        paid.append({
            "id": plan["id"], "title": plan["title"],
            "days": plan["days"], "devices": plan["devices"],
            "price_rub": price_rub(plan), "category": plan["category"],
            "tag": plan["tag"], "status": "upcoming",
            "checkout_supported": False, "checkout_path": None,
        })
    trial = {
        "id": "trial-free", "title": "Пробный день", "days": 1,
        "devices": 2, "traffic_gb": 10, "price_rub": "0.00",
        "category": "trial", "status": "trial",
        "checkout_supported": False, "checkout_path": "/trial.html",
    }
    order = {identifier: index for index, identifier in enumerate(ORDER)}
    all_plans = sorted([trial, *paid], key=lambda p: order[p["id"]])
    return {
        "plans": all_plans,
        "total": len(all_plans),
        "existing_paid_count": len(CATALOG),
        "upcoming_count": len(UPCOMING),
        "trial_count": 1,
        "note": (
            "Новые тарифы предварительные и недоступны к оплате до "
            "проверки RollyPay и H1Cloud. Покупка действующих тарифов "
            "зависит от доступности защищённой кассы."
        ),
    }


@router.get("/tariffs")
def tariffs() -> dict:
    return public_tariff_catalog()
