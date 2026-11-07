"""Public catalog of 50 priced paid plans and one free trial.

All paid plans share the server billing catalog, signed RollyPay webhook
validation, durable order ledger, and H1Cloud post-write verification.
Checkout remains gated by runtime merchant/fulfillment readiness.
"""
from __future__ import annotations

from fastapi import APIRouter

from .billing import CATALOG, price_rub
from .expanded_tariffs import EXTRA_CATALOG, EXTRA_PLAN_IDS

router = APIRouter(prefix="/api/site", tags=["Public tariff catalog"])

# First five additional offers were activated and are already in CATALOG.
NEW_PLAN_IDS = frozenset({"7", "14", "45", "120", "30-family"})

# Added to the shared RollyPay/H1Cloud billing catalog; not gift cards.
ADDED_PLAN_IDS = frozenset({
    "mini-3d", "sprint-5d", "start-plus-21d", "balance-75d",
    "comfort-150d", "max-270d", "legend-730d", "family-plus-90d",
    "family-pro-180d", "family-max-730d",
})
ULTRA_PLAN_IDS = EXTRA_PLAN_IDS
UPCOMING_IDS = frozenset()
UPCOMING = ()

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
    "mini-3d": "На три дня",
    "sprint-5d": "Быстрый старт",
    "start-plus-21d": "Три недели",
    "balance-75d": "Гибкий срок",
    "comfort-150d": "Пять месяцев",
    "max-270d": "Девять месяцев",
    "legend-730d": "Два года",
    "family-plus-90d": "Семейный на три месяца",
    "family-pro-180d": "Семейный на полгода",
    "family-max-730d": "Семейный на два года",
}
ORDER = (
    "trial-free", "mini-3d", "sprint-5d", "7", "14", "start-plus-21d",
    "30", "45", "60", "balance-75d", "90", "120", "comfort-150d",
    "180", "max-270d", "365", "legend-730d", "30-family",
    "family-plus-90d", "family-pro-180d", "365-family",
    "family-max-730d",
) + tuple(plan["id"] for plan in EXTRA_CATALOG)


def _segment(days: int, category: str) -> str:
    if category == "family":
        return "family"
    if days <= 21:
        return "short"
    if days <= 120:
        return "standard"
    return "long"


def public_tariff_catalog() -> dict:
    paid = []
    for plan in CATALOG:
        category = "family" if plan["devices"] == 6 else "personal"
        paid.append({
            "id": plan["id"], "title": plan["title"],
            "days": plan["days"], "devices": plan["devices"],
            "price_rub": price_rub(plan), "category": category,
            "segment": _segment(plan["days"], category),
            "tag": LIVE_TAGS.get(plan["id"], (
                "Семейный доступ" if category == "family"
                else "Новый тариф")), 
            "status": "existing", "checkout_supported": True,
            "checkout_path": "/checkout.html?plan=" + plan["id"],
        })
    trial = {
        "id": "trial-free", "title": "Пробный день", "days": 1,
        "devices": 2, "traffic_gb": 10, "price_rub": "0.00",
        "category": "trial", "segment": "trial", "status": "trial",
        "checkout_supported": False, "checkout_path": "/trial.html",
    }
    order = {identifier: index for index, identifier in enumerate(ORDER)}
    all_plans = sorted([trial, *paid], key=lambda p: order[p["id"]])
    return {
        "plans": all_plans,
        "total": len(all_plans),
        "existing_paid_count": len(CATALOG),
        "upcoming_count": 0,
        "newly_launched_count": len(NEW_PLAN_IDS | ADDED_PLAN_IDS | ULTRA_PLAN_IDS),
        "trial_count": 1,
        "note": (
            "50 платных тарифов доступны для оформления при готовности кассы "
            "RollyPay и H1Cloud. VPN выдаётся только после подтверждённого "
            "платежа. Бесплатный пробный день без оплаты."
        ),
    }


@router.get("/tariffs")
def tariffs() -> dict:
    return public_tariff_catalog()
