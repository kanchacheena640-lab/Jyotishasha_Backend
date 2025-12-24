from __future__ import annotations
from typing import Dict, Any

from full_kundali_api import calculate_full_kundali
from modules.love.ashtakoot_love import compute_ashtakoot
from modules.love.fallback_love import compute_vedic_fallback


CASE_A_FULL_DUAL = "A_FULL_DUAL"
CASE_B_DOB_ONLY_HYBRID = "B_DOB_ONLY_HYBRID"


class LoveServiceError(Exception):
    pass


def detect_case(partner: Dict[str, Any]) -> str:
    has_full = (
        partner.get("dob")
        and partner.get("tob")
        and partner.get("lat") is not None
        and partner.get("lng") is not None
    )
    return CASE_A_FULL_DUAL if has_full else CASE_B_DOB_ONLY_HYBRID


def _require(payload: Dict[str, Any], fields: tuple, label: str) -> None:
    missing = [f for f in fields if not payload.get(f)]
    if missing:
        raise LoveServiceError(f"{label} missing: {', '.join(missing)}")


def _extract_moon(kundali: Dict[str, Any]) -> Dict[str, Any]:
    moon = next(
        (p for p in kundali.get("planets", []) if p.get("name") == "Moon"),
        None,
    )
    if not moon:
        raise LoveServiceError("Moon data missing in kundali")
    return {
        "rashi": moon.get("sign"),
        "degree": moon.get("degree"),
        "nakshatra": moon.get("nakshatra"),
    }


def run_love_compatibility(
    user: Dict[str, Any],
    partner: Dict[str, Any],
    *,
    boy_is_user: bool = True,
) -> Dict[str, Any]:

    _require(user, ("name", "dob", "tob", "lat", "lng"), "User")
    _require(partner, ("name", "dob"), "Partner")

    case = detect_case(partner)

    user_kundali = calculate_full_kundali(
        name=user["name"],
        dob=user["dob"],
        tob=user["tob"],
        lat=user["lat"],
        lon=user["lng"],
        language=user.get("language", "en"),
    )

    user_moon = _extract_moon(user_kundali)

    result: Dict[str, Any] = {
        "case": case,
        "labels": {},
        "ashtakoot": None,
        "fallback": None,
        "notes": [],
        "meta": {
            "user_name": user.get("name"),
            "partner_name": partner.get("name"),
        },
    }

    if case == CASE_A_FULL_DUAL:
        partner_kundali = calculate_full_kundali(
            name=partner["name"],
            dob=partner["dob"],
            tob=partner["tob"],
            lat=partner["lat"],
            lon=partner["lng"],
            language=partner.get("language", "en"),
        )

        partner_moon = _extract_moon(partner_kundali)

        ashtakoot = compute_ashtakoot(
            bride_moon=user_moon if boy_is_user else partner_moon,
            groom_moon=partner_moon if boy_is_user else user_moon,
        )

        result["labels"]["analysis"] = "Full Dual-Kundali Vedic"
        result["ashtakoot"] = ashtakoot
        result["kundali"] = {
            "user": user_kundali,
            "partner": partner_kundali,
        }

    else:
        ashtakoot = compute_ashtakoot(
            bride_moon=user_moon if boy_is_user else user_moon,
            groom_moon=user_moon if not boy_is_user else user_moon,
            partial_partner=True,
        )

        fallback = compute_vedic_fallback(user_kundali)

        result["labels"]["analysis"] = "Partial Analysis (Moon-based + Vedic fallback)"
        result["ashtakoot"] = ashtakoot
        result["fallback"] = fallback
        result["notes"].append(
            "Partner time/place not provided. Lagna-based results derived using classical Vedic fallback."
        )

    return result
