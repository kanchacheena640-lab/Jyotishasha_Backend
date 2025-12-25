from __future__ import annotations
from typing import Dict, Any

from full_kundali_api import calculate_full_kundali
from modules.love.ashtakoot_love import compute_ashtakoot
from modules.love.fallback_love import compute_vedic_fallback
from modules.love.moon_only import derive_moon_from_dob
from modules.love.love_report_compiler import compile_love_report


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

    # -------- User kundali (always full) --------
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
            "user_name": user["name"],
            "partner_name": partner["name"],
        },
    }

    # ======================================================
    # CASE A — Full Dual Kundali
    # ======================================================
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

        boy_moon = user_moon if boy_is_user else partner_moon
        girl_moon = partner_moon if boy_is_user else user_moon

        ashtakoot = compute_ashtakoot(
            bride_moon=girl_moon,
            groom_moon=boy_moon,
        )

        result["labels"]["analysis"] = "Full Dual-Kundali Vedic"
        result["ashtakoot"] = ashtakoot

    # ======================================================
    # CASE B — Partner DOB only
    # ======================================================
    else:
        partner_moon = derive_moon_from_dob(partner["dob"])

        boy_moon = user_moon if boy_is_user else partner_moon
        girl_moon = partner_moon if boy_is_user else user_moon

        ashtakoot = compute_ashtakoot(
            bride_moon=girl_moon,
            groom_moon=boy_moon,
        )

        fallback = compute_vedic_fallback(user_kundali, safe_mode=True)

        result["labels"]["analysis"] = "Partial Analysis (Moon-based + Vedic fallback)"
        result["ashtakoot"] = ashtakoot
        result["fallback"] = fallback
        result["notes"].append(
            "Partner birth time/place not provided. Moon derived from DOB; "
            "5th-house-based Vedic fallback applied."
        )

    # ---------------- NORMALIZE ASHTAKOOT STATUS FOR REPORT ----------------
    STATUS_MAP = {
        "pass": "pass",
        "mixed": "partial",
        "enemy": "fail",
        "sworn_enemy": "dosha",
        "dosha": "dosha",
        "fail": "fail",
    }

    if isinstance(result.get("ashtakoot"), dict):
        kootas = result["ashtakoot"].get("kootas", {})
        for _, v in kootas.items():
            if not isinstance(v, dict):
                continue
            st = (v.get("status") or "").lower()
            v["status"] = STATUS_MAP.get(st, "partial")

    return result
