# Path: modules/love/love_data_collector.py
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


def _normalize_houses(houses_raw: Any) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict: {"1": {...}, "2": {...}, ...}
    Supports:
    - already dict (string keys)
    - list of dicts (each may contain house number as house/house_no/number)
    """
    if isinstance(houses_raw, dict):
        # ensure string keys
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in houses_raw.items():
            if isinstance(v, dict):
                out[str(k)] = v
        return out

    if isinstance(houses_raw, list):
        out: Dict[str, Dict[str, Any]] = {}
        for item in houses_raw:
            if not isinstance(item, dict):
                continue
            hn = item.get("house") or item.get("house_no") or item.get("number") or item.get("index")
            if hn is None:
                # if list is 12-length and has no house field, fallback not possible reliably
                continue
            out[str(hn)] = item
        return out

    return {}


def _normalize_planets(planets_raw: Any) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict: {"Sun": {...}, "Moon": {...}}
    Supports:
    - already dict
    - list of dicts (each item has name/planet keys)
    """
    if isinstance(planets_raw, dict):
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in planets_raw.items():
            if isinstance(v, dict):
                out[str(k)] = v
        return out

    if isinstance(planets_raw, list):
        out: Dict[str, Dict[str, Any]] = {}
        for item in planets_raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("planet") or item.get("planet_name")
            if not name:
                continue
            out[str(name)] = item
        return out

    return {}


def _safe_list(val: Any) -> list:
    if isinstance(val, list):
        return val
    if val is None:
        return []
    return [val]


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

    # 1) Ashtakoot / Compatibility (untouched)
    try:
        compat = run_love_compatibility(
            user=user,
            partner=partner,
            boy_is_user=bool(boy_is_user),
        )
    except LoveServiceError as e:
        raise LoveCollectorError(str(e))

    # 2) Compiler (untouched)
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

    # 3) NEW: Astro Facts (now safe for list/dict kundali shapes)
    houses = _normalize_houses(user_kundali.get("houses"))
    planets = _normalize_planets(user_kundali.get("planets"))

    h5 = houses.get("5", {}) if isinstance(houses.get("5", {}), dict) else {}
    h7 = houses.get("7", {}) if isinstance(houses.get("7", {}), dict) else {}

    lord_5 = h5.get("lord") or h5.get("house_lord")
    lord_7 = h7.get("lord") or h7.get("house_lord")

    planets_in_5 = _safe_list(h5.get("planets") or h5.get("planet_list"))
    planets_in_7 = _safe_list(h7.get("planets") or h7.get("planet_list"))

    dasha = user_kundali.get("dasha") if isinstance(user_kundali.get("dasha"), dict) else {}
    current_dasha_planet = None
    if isinstance(dasha.get("current"), dict):
        current_dasha_planet = dasha["current"].get("planet") or dasha["current"].get("lord")

    # aspects: keep flexible (some kundali don't have it)
    aspects = user_kundali.get("aspects") if isinstance(user_kundali.get("aspects"), dict) else {}

    astro_facts = {
        "love_flow": {
            "lord_5": lord_5,
            "lord_7": lord_7,
            "planets_in_5": planets_in_5,
            "planets_in_7": planets_in_7,
            "lord_5_position": planets.get(str(lord_5)) if lord_5 else None,
            "lord_7_position": planets.get(str(lord_7)) if lord_7 else None,
            "connection_5_7": aspects.get("5_7_relation") or aspects.get("connection_5_7"),
            "current_dasha_related": bool(current_dasha_planet and current_dasha_planet in {lord_5, lord_7}),
        },
        "love_vs_arranged": {
            "rahu_in_5_or_7": ("Rahu" in planets_in_5) or ("Rahu" in planets_in_7),
            "venus_involved": ("Venus" in planets) or ("Shukra" in planets),
            "direct_5_7_link": bool(aspects.get("5_7_relation") or aspects.get("connection_5_7")),
            "family_house_support": any(houses.get(h) for h in ("2", "11")),
        },
        "strength_risk": {
            "benefic_support": aspects.get("benefic_support", []),
            "malefic_affliction": aspects.get("malefic_affliction", []),
            "manglik": user_kundali.get("manglik", False),
            "verdict_level": (compiled.get("verdict") or {}).get("level") if isinstance(compiled, dict) else None,
        },
        "remedies": {
            "weak_house": ((compiled.get("signals") or {}).get("weak_house")) if isinstance(compiled, dict) else None,
            "weak_lord": ((compiled.get("signals") or {}).get("weak_lord")) if isinstance(compiled, dict) else None,
            "current_dasha": dasha.get("current"),
        },
    }

    return {
        "product": "relationship_future_report",
        "language": lang,
        "client": user,
        "partner": partner,
        "compatibility": compat,
        "compiled_report": compiled,
        "astro_facts": astro_facts,
    }
