# Path: modules/love/love_data_collector.py
# Jyotishasha — Love Premium Report Data Collector (LOCKED)
#
# Purpose:
# - Collect structured love intelligence for premium report generation
# - NO OpenAI here
# - Output is strictly JSON/dict to be later converted into prompt blocks
#
# Inputs:
# - order: dict (from get_order_details(order_id) OR already in task.py)
# - user_kundali: dict (already calculated in task.py)
# - language: "en" | "hi"
#
# Notes:
# - Partner data must come from order payload (preferred) or fallback keys.
# - Supports two cases:
#   A) Full partner details (DOB+TOB+LAT+LNG) -> full dual-kundali Ashtakoot
#   B) Partner DOB only -> Moon approximation + Vedic fallback (safe_mode)

from __future__ import annotations
from typing import Any, Dict, Optional

from modules.love.service_love import run_love_compatibility, LoveServiceError
from modules.love.love_report_compiler import compile_love_report


class LoveCollectorError(Exception):
    pass


def _pick_partner(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Partner details source priority:
    1) order["partner"] dict (recommended)
    2) legacy flat fields if you stored them (partner_name, partner_dob, etc.)
    """
    partner = order.get("partner")
    if isinstance(partner, dict) and partner:
        return partner

    # Legacy flat fields fallback (optional)
    p = {
        "name": order.get("partner_name"),
        "dob": order.get("partner_dob"),
        "tob": order.get("partner_tob"),
        "lat": order.get("partner_lat"),
        "lng": order.get("partner_lng"),
        "language": order.get("partner_language") or order.get("language") or "en",
    }
    # Clean None keys
    return {k: v for k, v in p.items() if v is not None}


def _pick_user(order: Dict[str, Any], language: str) -> Dict[str, Any]:
    """
    User is ALWAYS full details in your current system (dob+tob+lat+lng).
    """
    return {
        "name": order.get("name"),
        "dob": order.get("dob"),
        "tob": order.get("tob"),
        "lat": order.get("latitude") if order.get("latitude") is not None else order.get("lat"),
        "lng": order.get("longitude") if order.get("longitude") is not None else order.get("lng"),
        "language": language or order.get("language") or "en",
    }


def collect_love_report_data(
    order: Dict[str, Any],
    user_kundali: Dict[str, Any],
    language: str,
    *,
    boy_is_user: bool = True,
) -> Dict[str, Any]:
    """
    Returns a structured dict that can be used in two ways:
    1) To build OpenAI prompt blocks (premium narrative writing)
    2) To generate direct JSON-only UI (if needed later)

    Output keys (stable contract):
    - product
    - language
    - client
    - partner
    - compatibility (raw output of run_love_compatibility)
    - compiled_report (output of compile_love_report)
    """
    if not isinstance(order, dict) or not order:
        raise LoveCollectorError("order payload missing/invalid")
    if not isinstance(user_kundali, dict) or not user_kundali:
        raise LoveCollectorError("user_kundali missing/invalid")

    lang = (language or order.get("language") or "en").strip().lower()
    lang = "hi" if lang == "hi" else "en"

    user = _pick_user(order, lang)
    partner = _pick_partner(order)

    # Hard requirements for this premium product
    if not user.get("name") or not user.get("dob") or not user.get("tob"):
        raise LoveCollectorError("User basic details missing (name/dob/tob)")
    if user.get("lat") is None or user.get("lng") is None:
        raise LoveCollectorError("User lat/lng missing")

    if not partner.get("name") or not partner.get("dob"):
        raise LoveCollectorError("Partner details missing (name/dob)")

    # 1) Compatibility (Ashtakoot + optional fallback)
    try:
        compat = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=bool(boy_is_user),
        )
    except LoveServiceError as e:
        raise LoveCollectorError(str(e))

    # 2) Compile structured paid report JSON (NOT the final narrative)
    compiled = compile_love_report(
        {
            "language": lang,
            "client": {
                "name": user.get("name"),
                "dob": user.get("dob"),
                "tob": user.get("tob"),
                "pob": order.get("pob"),
            },
            # IMPORTANT: we pass user kundali already computed in task.py
            "kundali": user_kundali,
            "ashtakoot": compat.get("ashtakoot") or {},
            # If CASE_B, compiler can use this later for disclaimers/logic if needed
            "fallback": compat.get("fallback"),
            # Optional (only if available in your pipeline)
            "dasha": user_kundali.get("dasha") if isinstance(user_kundali.get("dasha"), dict) else {},
            "transits": user_kundali.get("transit_summary") if isinstance(user_kundali.get("transit_summary"), dict) else {},
        }
    )

    return {
        "product": "love-marriage-life",
        "language": lang,
        "client": user,
        "partner": partner,
        "compatibility": compat,
        "compiled_report": compiled,
    }
