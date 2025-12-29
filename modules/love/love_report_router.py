# Path: modules/love/love_report_router.py
# Jyotishasha — Report Router (LOCKED)

from __future__ import annotations
from typing import Optional

# Existing normal report task (OLD SYSTEM)
from tasks import generate_and_send_report

# Love premium task (NEW SYSTEM)
from modules.love.love_premium_task import generate_love_premium_report


# 🔒 Product keys (LOCKED)
LOVE_PREMIUM_PRODUCT = "relationship_future_report"


def route_report_generation(order_id: int, product: Optional[str]):
    """
    Central router for ALL paid reports.
    - Decides which engine should run
    - Never breaks old flow
    """

    product = (product or "").strip().lower()

    # ✅ Love & Relationship Premium Report
    if product == LOVE_PREMIUM_PRODUCT:
        return generate_love_premium_report(order_id)

    # ✅ Fallback: Old report system (ALL other reports)
    return generate_and_send_report(order_id)
