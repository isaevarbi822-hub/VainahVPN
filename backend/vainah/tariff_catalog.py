"""Public VPN plan catalog: 11 existing paid, 10 proposed, one free trial.

Proposed tariff metadata is read-only and not a RollyPay/H1Cloud contract.
To launch a proposed tariff, verify its duration/device capabilities and
merchant fulfillment separately before adding its ID to billing.CATALOG.
"""
from __future__ import annotations

from fastapi import APIRouter

from .billing import CATALOG, price_rub

router = APIRouter(prefix="/api/site", tags=["Public tariff catalog"])

# First five additional offers were activated and are already in CATALOG.
NEW_PLAN_IDS = frozenset({"7", "14", "45", "120", "30-family"})

# The next ten are PROPOSALS. Never put these in checkout or gift allowlists
# until RollyPay/H1Cloud production contracts, especially 730-day terms,
# have passed independent readiness and actual end-to-end verification.
UPCOMING = (
    {"id": "mini-3d", "title": "Vainah Mini", "days": 3,
     "kopeks": 1900, "devices": 3, "category": "personal",
     "segment": "short", "tag": "На три дня"},
    {"id": "sprint-5d", "title": "Vainah Sprint", "days": 5,
     "kopeks": 2900, "devices": 3, "category": "personal",
     "segment": "short", "tag": "Быстрый старт"},
    {"id": "start-plus-21d", "title": "Vainah Start+", "days": 21,
     "kopeks": 7900, "devices": 3, "category": "personal",
     "segment": "short", "tag": "Три недели"},
    {"id": "balance-75d", "title": "Vainah Balance", "days": 75,
     "kopeks": 18900, "devices": 3, "category": "personal",
     "segment": "standard", "tag": "Гибкий срок"},
    {"id": "comfort-150d", "title": "Vainah Comfort", "days": 150,
     "kopeks": 30900, "devices": 3, "category": "personal",
     "segment": "long", "tag": "Пять месяцев"},
    {"id": "max-270d", "title": "Vainah Max", "days": 270,
     "kopeks": 49900, "devices": 3, "category": "personal",
     "segment": "long", "tag": "Девять месяцев"},
    {"id": "legend-730d", "title": "Vainah Legend", "days": 730,
     "kopeks": 119000, "devices": 3, "category": "personal",
     "segment": "long", "tag": "Два года"},
    {"id": "family-plus-90d", "title": "Vainah Family+", "days": 90,
     "kopeks": 39900, "devices": 6, "category": "family",
     "segment": "family", "tag": "Семейный на три месяца"},
    {"id": "family-pro-180d", "title": "Vainah Family Pro", "days": 180,
     "kopeks": 64900, "devices": 6, "category": "family",
     "segment": "family", "tag": "Семейный на полгода"},
    {"id": "family-max-730d", "title": "Vainah Family Max", "days": 730,
     "kopeks": 179000, "devices": 6, "category": "family",
     "segment": "family", "tag": "Семейный на два года"},
)
UPCOMING_IDS = frozenset(plan["id"] for plan in UPCOMING)
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
    "trial-free", "mini-3d", "sprint-5d", "7", "14", "start-plus-21d",
    "30", "45", "60", "balance-75d", "90", "120", "comfort-150d",
    "180", "max-270d", "365", "legend-730d", "30-family",
    "family-plus-90d", "family-pro-180d", "365-family",
    "family-max-730d",
)


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
        category = "family" if plan["id"].endswith("-family") else "personal"
        paid.append({
            "id": plan["id"], "title": plan["title"],
            "days": plan["days"], "devices": plan["devices"],
            "price_rub": price_rub(plan), "category": category,
            "segment": _segment(plan["days"], category),
            "tag": LIVE_TAGS.get(plan["id"], ""),
            "status": "existing", "checkout_supported": True,
            "checkout_path": "/checkout.html?plan=" + plan["id"],
        })
    for plan in UPCOMING:
        paid.append({
            "id": plan["id"], "title": plan["title"],
            "days": plan["days"], "devices": plan["devices"],
            "price_rub": price_rub(plan),
            "category": plan["category"], "segment": plan["segment"],
            "tag": plan["tag"], "status": "upcoming",
            "checkout_supported": False, "checkout_path": None,
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
        "upcoming_count": len(UPCOMING),
        "newly_launched_count": len(NEW_PLAN_IDS),
        "trial_count": 1,
        "note": (
            "11 действующих платных тарифов и 10 новых предварительных "
            "предложений. Новые предложения НЕ принимают оплату до отдельной "
            "проверки RollyPay и H1Cloud. Один пробный день предоставляется "
            "без оплаты."
        ),
    }


@router.get("/tariffs")
def tariffs() -> dict:
    return public_tariff_catalog()
