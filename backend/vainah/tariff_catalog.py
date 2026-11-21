"""Public catalog of subscriptions currently on sale and the free trial.

All paid plans share the server billing catalog, signed RollyPay webhook
validation, durable order ledger, and H1Cloud post-write verification.
Checkout remains gated by runtime merchant/fulfillment readiness.
"""
from __future__ import annotations

from fastapi import APIRouter

from .billing import SALE_CATALOG, SALE_PLAN_IDS, price_rub
from .expanded_tariffs import EXTRA_PLAN_IDS

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
    "mini-3d": "На три дня",
    "7": "На неделю",
    "14": "На две недели",
    "30": "На месяц",
    "60": "На два месяца",
    "90": "На три месяца",
    "180": "На полгода",
    "365": "На год",
    "30-family": "Для семьи",
    "family-plus-90d": "Семейный на три месяца",
    "family-pro-180d": "Семейный на полгода",
    "365-family": "Семья на год",
}
ORDER = ("trial-free", *SALE_PLAN_IDS)


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
    for plan in SALE_CATALOG:
        category = "family" if plan["devices"] == 6 else "personal"
        paid.append({
            "id": plan["id"], "title": plan["title"],
            "days": plan["days"], "devices": plan["devices"],
            "price_rub": price_rub(plan), "category": category,
            "segment": _segment(plan["days"], category),
            "tag": LIVE_TAGS[plan["id"]],
            "status": "existing", "checkout_supported": True,
            "checkout_path": "/checkout.html?plan=" + plan["id"],
        })
    trial = {
        "id": "trial-free", "title": "Пробный день", "days": 1,
        "devices": 2, "traffic_gb": 10, "price_rub": "0.00",
        "category": "trial", "segment": "trial", "status": "trial",
        "checkout_supported": False, "checkout_path": "/trial.html",
    }
    all_plans = [trial, *paid]
    return {
        "plans": all_plans,
        "total": len(all_plans),
        "existing_paid_count": len(paid),
        "upcoming_count": 0,
        "newly_launched_count": 0,
        "trial_count": 1,
        "note": (
            "Платные тарифы доступны для оформления при готовности кассы "
            "и сервиса выдачи. VPN выдаётся только после подтверждённого "
            "платежа. Бесплатный пробный день без оплаты."
        ),
    }


@router.get("/tariffs")
def tariffs() -> dict:
    return public_tariff_catalog()
