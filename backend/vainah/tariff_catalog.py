"""Public 12-option catalog backed by the 11 paid RollyPay/H1Cloud plans.

Checkout is still gated by verified email, live merchant readiness, signed
webhook confirmation, and H1Cloud fulfillment. No payment secrets are exposed.
"""
from __future__ import annotations

from fastapi import APIRouter

from .billing import CATALOG, price_rub

router = APIRouter(prefix="/api/site", tags=["Public tariff catalog"])

NEW_PLAN_IDS = frozenset({"7", "14", "45", "120", "30-family"})
LIVE_TAGS = {
    "7": "На короткий срок",
    "14": "Гибкий старт",
    "45": "Больше месяца",
    "120": "Длинный срок",
    "30-family": "Для семьи",
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
        "upcoming_count": 0,
        "newly_launched_count": len(NEW_PLAN_IDS),
        "trial_count": 1,
        "note": (
            "Доступны 11 платных тарифов и бесплатный пробный день. "
            "Оплата возможна после подтверждения email и проверки кассы. "
            "VPN выдаётся только после подтверждённого платежа."
        ),
    }


@router.get("/tariffs")
def tariffs() -> dict:
    return public_tariff_catalog()
