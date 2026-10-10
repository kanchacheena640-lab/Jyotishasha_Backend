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

    # Degree within the sign. Prefer the full-precision longitude: the chart's own `degree` is rounded to
    # 0.01, which can push a Moon at e.g. Sagittarius 14.996 deg across the 15-deg Vashya boundary.
    longitude = moon.get("longitude")
    degree = (float(longitude) % 30) if isinstance(longitude, (int, float)) else moon.get("degree")

    return {
        "rashi": moon.get("sign"),
        "degree": degree,
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
        # The partner's Moon is an estimate from the date of birth only, so every Moon-based koota and the
        # total are approximate. Additive fields; consumers that ignore them are unaffected.
        ashtakoot["approximate"] = True
        ashtakoot["approximation_reason"] = "partner_birth_time_or_place_missing"
        result["ashtakoot"] = ashtakoot
        result["fallback"] = fallback
        result["notes"].append(
            "Partner birth time/place not provided. Moon derived from DOB; "
            "5th-house-based Vedic fallback applied."
        )

    # ---------------- NORMALIZE ASHTAKOOT STATUS FOR REPORT ----------------
    if isinstance(result.get("ashtakoot"), dict):
        kootas = result["ashtakoot"].get("kootas", {})
        for _, v in kootas.items():
            if isinstance(v, dict):
                v["status"] = normalize_koota_status(v)

    return result


# Engine statuses that name an actual dosha (Bhakoot / Nadi "dosha", Yoni Mahavaira "sworn_enemy").
_DOSHA_RAW_STATUSES = {"dosha", "sworn_enemy"}


def normalize_koota_status(koota: Dict[str, Any]) -> str:
    """
    Outward status for one koota: exactly one of "pass" | "partial" | "dosha" | "fail" (the vocabulary the
    website and the Flutter app already render). Derived from the koota's own score/max and the engine's
    dosha flags -- never from the engine's status wording, so a full score is always "pass".
    """
    score, mx = koota.get("score"), koota.get("max")
    raw = (koota.get("status") or "").lower()
    if raw == "invalid" or not isinstance(score, (int, float)) or not isinstance(mx, (int, float)) or mx <= 0:
        return "fail"
    if score >= mx:
        return "pass"  # includes a dosha treated as cancelled with full points; the note says so
    if score <= 0:
        return "dosha" if raw in _DOSHA_RAW_STATUSES else "fail"
    return "partial"
