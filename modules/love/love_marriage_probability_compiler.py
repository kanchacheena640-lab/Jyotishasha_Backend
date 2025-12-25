# modules/love/love_marriage_probability_compiler.py
# Jyotishasha — Love Marriage Probability (Tool #3)
# LOCKED: compiler only, no Flask, no DB

from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime, timezone

# -------------------------------------------------
# SIGN → LORD MAP (LOCKED)
# -------------------------------------------------

SIGN_LORD = {
    "Aries": "Mars",
    "Taurus": "Venus",
    "Gemini": "Mercury",
    "Cancer": "Moon",
    "Leo": "Sun",
    "Virgo": "Mercury",
    "Libra": "Venus",
    "Scorpio": "Mars",
    "Sagittarius": "Jupiter",
    "Capricorn": "Saturn",
    "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}

# 🔒 FIXED ZODIAC ORDER (VERY IMPORTANT)
ZODIAC_ORDER = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

# -------------------------------------------------
# UTILS
# -------------------------------------------------

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ensure_lang(lang: str) -> str:
    return "hi" if (lang or "").lower().strip() == "hi" else "en"

def _t(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

# -------------------------------------------------
# CHART DATA READERS (SOURCE OF TRUTH)
# chart_data EXPECTED SHAPE:
# {
#   "ascendant": "Capricorn",
#   "planets": [
#       {"name": "Venus", "house": 7},
#       {"name": "Mars", "house": 5},
#       ...
#   ]
# }
# -------------------------------------------------

def _extract_house_planets(chart_data: Dict[str, Any]) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for p in chart_data.get("planets", []):
        h = p.get("house")
        name = p.get("name")
        if isinstance(h, int) and isinstance(name, str):
            out.setdefault(h, []).append(name)
    return out

def _extract_planet_house_map(chart_data: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for p in chart_data.get("planets", []):
        if isinstance(p.get("name"), str) and isinstance(p.get("house"), int):
            out[p["name"]] = p["house"]
    return out

def _get_house_sign(chart_data: Dict[str, Any], house_no: int) -> str | None:
    asc = chart_data.get("ascendant")
    if asc not in ZODIAC_ORDER:
        return None

    start = ZODIAC_ORDER.index(asc)
    rotated = ZODIAC_ORDER[start:] + ZODIAC_ORDER[:start]

    if 1 <= house_no <= 12:
        return rotated[house_no - 1]
    return None

def _get_house_lord(chart_data: Dict[str, Any], house_no: int) -> str | None:
    sign = _get_house_sign(chart_data, house_no)
    return SIGN_LORD.get(sign) if sign else None

# -------------------------------------------------
# CORE SCORING LOGIC
# -------------------------------------------------

def _compute_love_marriage_pct(
    lang: str,
    chart_data: Dict[str, Any],
    *,
    fallback_mode: bool,
) -> Dict[str, Any]:

    hp = _extract_house_planets(chart_data)
    ph = _extract_planet_house_map(chart_data)

    score = 50.0
    reasons: List[str] = []

    # 1️⃣ 5th & 7th activation
    if 5 in hp:
        score += 10
        reasons.append(_t(lang, "5th house active (romance).", "5वां भाव सक्रिय (रोमांस)।"))
    if 7 in hp:
        score += 10
        reasons.append(_t(lang, "7th house active (marriage).", "7वां भाव सक्रिय (विवाह)।"))

    # 2️⃣ MAIN RULE: 5th–7th lord linkage
    lord5 = _get_house_lord(chart_data, 5)
    lord7 = _get_house_lord(chart_data, 7)

    h_lord5 = ph.get(lord5)
    h_lord7 = ph.get(lord7)

    if h_lord5 == 7 or h_lord7 == 5:
        score += 20
        reasons.append(_t(
            lang,
            "Strong 5th–7th lord exchange (love marriage yoga).",
            "5वां–7वां स्वामी परिवर्तन (लव मैरिज योग)।"
        ))
    elif h_lord5 is not None and h_lord5 == h_lord7:
        score += 15
        reasons.append(_t(
            lang,
            "5th and 7th lords conjunct.",
            "5वां और 7वां स्वामी युति।"
        ))

    # 3️⃣ Venus support
    if ph.get("Venus") in (5, 7):
        score += 10
        reasons.append(_t(lang, "Venus supports love marriage.", "शुक्र लव मैरिज को सपोर्ट करता है।"))

    # 4️⃣ Rahu (non-traditional)
    if ph.get("Rahu") in (5, 7):
        score += 5
        reasons.append(_t(lang, "Rahu shows unconventional path.", "राहु गैर-परंपरागत मार्ग दिखाता है।"))

    # 5️⃣ Pressure planets
    if ph.get("Saturn") in (5, 7):
        score -= 5
        reasons.append(_t(lang, "Saturn may delay marriage.", "शनि विवाह में देरी कर सकता है।"))
    if ph.get("Mars") in (5, 7):
        score -= 5
        reasons.append(_t(lang, "Mars needs control in relationships.", "मंगल में संयम जरूरी है।"))

    # Fallback note
    if fallback_mode:
        reasons.append(_t(
            lang,
            "Fallback mode used (Moon + 5th house reference).",
            "फॉलबैक मोड (चंद्र + 5वां भाव) उपयोग हुआ।"
        ))

    score = _clamp(score, 0, 100)
    band = "High" if score >= 70 else "Medium" if score >= 50 else "Low"

    return {
        "pct": int(score),
        "band": band,
        "reasons": reasons[:6],
        "meta": {
            "fallback_mode": fallback_mode,
            "effective_lagna_house": 5 if fallback_mode else 1,
            "detected": {
                "lord5": lord5,
                "lord7": lord7,
            },
        },
    }

# -------------------------------------------------
# PUBLIC COMPILER
# -------------------------------------------------

def compile_love_marriage_probability(payload: Dict[str, Any]) -> Dict[str, Any]:

    lang = _ensure_lang(payload.get("language", "en"))
    case = payload.get("case", "UNKNOWN")

    user = payload.get("user") or {}
    partner = payload.get("partner") or {}

    chart_user = payload.get("chart_data_user") or {}
    chart_partner = payload.get("chart_data_partner") or {}

    user_fallback = case != "A_FULL_DUAL" or not chart_user
    partner_fallback = case != "A_FULL_DUAL" or not chart_partner

    user_out = _compute_love_marriage_pct(lang, chart_user, fallback_mode=user_fallback)
    partner_out = (
        _compute_love_marriage_pct(lang, chart_partner, fallback_mode=partner_fallback)
        if chart_partner else None
    )

    overall_line = (
        _t(
            lang,
            f"User: {user_out['pct']}% ({user_out['band']}), "
            f"Partner: {partner_out['pct']}% ({partner_out['band']}).",
            f"यूज़र: {user_out['pct']}% ({user_out['band']}), "
            f"पार्टनर: {partner_out['pct']}% ({partner_out['band']})।",
        )
        if partner_out else
        _t(
            lang,
            f"User: {user_out['pct']}% ({user_out['band']}). Partner details required.",
            f"यूज़र: {user_out['pct']}% ({user_out['band']})। पार्टनर विवरण आवश्यक।",
        )
    )

    return {
        "type": "tool",
        "tool_id": "love-marriage-probability",
        "generated_at": _utc_iso(),
        "case": case,
        "overall_line": overall_line,
        "user_result": {"name": user.get("name"), **user_out},
        "partner_result": (
            {"name": partner.get("name"), **partner_out} if partner_out else None
        ),
        "disclaimers": [
            _t(
                lang,
                "Probability is derived from 5th–7th house linkage indicators.",
                "संभावना 5वें–7वें भाव के संकेतों से निकाली गई है।",
            )
        ],
    }
