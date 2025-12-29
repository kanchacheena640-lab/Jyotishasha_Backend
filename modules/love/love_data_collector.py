# Path: modules/love/love_data_collector.py
# Jyotishasha — Love Premium Report Data Collector (LOCKED)
#
# Purpose:
# - Collect structured love intelligence for premium report generation
# - NO OpenAI here
# - Output is strictly JSON/dict to be later converted into prompt blocks
#
# Key Upgrade (Dec 2025):
# - Adds astro_facts block for non-generic premium narration
# - Ashtakoot logic untouched
# - Backward compatible

from __future__ import annotations
from typing import Any, Dict

from modules.love.service_love import run_love_compatibility, LoveServiceError
from modules.love.love_report_compiler import compile_love_report


class LoveCollectorError(Exception):
    pass


def _pick_partner(order: Dict[str, Any]) -> Dict[str, Any]:
    partner = order.get("partner")
    if isinstance(partner, dict) and partner:
        return partner

    p = {
        "name": order.get("partner_name"),
        "dob": order.get("partner_dob"),
        "tob": order.get("partner_tob"),
        "lat": order.get("partner_lat"),
        "lng": order.get("partner_lng"),
        "language": order.get("partner_language") or order.get("language") or "en",
    }
    return {k: v for k, v in p.items() if v is not None}


def _pick_user(order: Dict[str, Any], language: str) -> Dict[str, Any]:
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

    if not isinstance(order, dict) or not order:
        raise LoveCollectorError("order payload missing/invalid")
    if not isinstance(user_kundali, dict) or not user_kundali:
        raise LoveCollectorError("user_kundali missing/invalid")

    lang = (language or order.get("language") or "en").lower()
    lang = "hi" if lang == "hi" else "en"

    user = _pick_user(order, lang)
    partner = _pick_partner(order)

    if not user.get("name") or not user.get("dob") or not user.get("tob"):
        raise LoveCollectorError("User basic details missing")
    if user.get("lat") is None or user.get("lng") is None:
        raise LoveCollectorError("User lat/lng missing")
    if not partner.get("name") or not partner.get("dob"):
        raise LoveCollectorError("Partner details missing")

    # ---------------- 1) Ashtakoot / Compatibility ----------------
    try:
        compat = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=bool(boy_is_user),
        )
    except LoveServiceError as e:
        raise LoveCollectorError(str(e))

    # ---------------- 2) Structured Compiler (existing) ----------------
    compiled = compile_love_report(
        {
            "language": lang,
            "client": {
                "name": user.get("name"),
                "dob": user.get("dob"),
                "tob": user.get("tob"),
                "pob": order.get("pob"),
            },
            "kundali": user_kundali,
            "ashtakoot": compat.get("ashtakoot") or {},
            "fallback": compat.get("fallback"),
            "dasha": user_kundali.get("dasha") or {},
            "transits": user_kundali.get("transit_summary") or {},
        }
    )

    # ---------------- 3) NEW: Astro Facts for Premium Narration ----------------
    houses = user_kundali.get("houses", {})
    planets = user_kundali.get("planets", {})
    aspects = user_kundali.get("aspects", {})
    dasha = user_kundali.get("dasha", {})

    lord_5 = houses.get("5", {}).get("lord")
    lord_7 = houses.get("7", {}).get("lord")

    astro_facts = {
        "love_flow": {
            "lord_5": lord_5,
            "lord_7": lord_7,
            "planets_in_5": houses.get("5", {}).get("planets", []),
            "planets_in_7": houses.get("7", {}).get("planets", []),
            "lord_5_position": planets.get(lord_5),
            "lord_7_position": planets.get(lord_7),
            "connection_5_7": aspects.get("5_7_relation"),
            "current_dasha_related": dasha.get("current", {}).get("planet") in (lord_5, lord_7),
        },

        "love_vs_arranged": {
            "rahu_in_5_or_7": "Rahu" in (
                houses.get("5", {}).get("planets", []) +
                houses.get("7", {}).get("planets", [])
            ),
            "venus_involved": "Venus" in planets,
            "direct_5_7_link": bool(aspects.get("5_7_relation")),
            "family_house_support": any(
                houses.get(h) for h in ("2", "7", "11")
            ),
        },

        "strength_risk": {
            "benefic_support": aspects.get("benefic_support", []),
            "malefic_affliction": aspects.get("malefic_affliction", []),
            "manglik": user_kundali.get("manglik", False),
            "verdict_level": compiled.get("verdict", {}).get("level"),
        },

        "remedies": {
            "weak_house": compiled.get("signals", {}).get("weak_house"),
            "weak_lord": compiled.get("signals", {}).get("weak_lord"),
            "current_dasha": dasha.get("current"),
        },
    }

    # ---------------- FINAL PAYLOAD ----------------
    return {
        "product": "relationship_future_report",
        "language": lang,
        "client": user,
        "partner": partner,
        "compatibility": compat,
        "compiled_report": compiled,
        "astro_facts": astro_facts,   # 🔑 THIS FIXES GENERIC OUTPUT
    }
