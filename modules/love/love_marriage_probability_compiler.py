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

# -------------------------------------------------
# UTILS
# -------------------------------------------------

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ensure_lang(lang: str) -> str:
    return "hi" if (lang or "").lower().strip() == "hi" else "en"

def _t(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en

def _non_empty_str(x: Any) -> bool:
    return isinstance(x, str) and x.strip() != ""

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

# -------------------------------------------------
# SAFE KUNDALI READERS
# -------------------------------------------------

def _extract_house_planets(kundali: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    """
    Returns {house: [planet_dicts]} for NON-EMPTY houses only.
    """
    out: Dict[int, List[Dict[str, Any]]] = {}

    hp = kundali.get("house_planets")
    if isinstance(hp, dict):
        for k, v in hp.items():
            try:
                hn = int(k)
            except Exception:
                continue
            if isinstance(v, list) and v:
                out[hn] = [p for p in v if isinstance(p, dict)]
        return out

    houses = kundali.get("houses")
    if isinstance(houses, list):
        for h in houses:
            if not isinstance(h, dict):
                continue
            try:
                hn = int(h.get("house") or h.get("number"))
            except Exception:
                continue
            ps = h.get("planets")
            if isinstance(ps, list) and ps:
                out[hn] = [p for p in ps if isinstance(p, dict)]
        return out

    d1 = (((kundali.get("charts") or {}).get("D1") or {}).get("houses"))
    if isinstance(d1, list):
        for h in d1:
            if not isinstance(h, dict):
                continue
            try:
                hn = int(h.get("house") or h.get("number"))
            except Exception:
                continue
            ps = h.get("planets")
            if isinstance(ps, list) and ps:
                out[hn] = [p for p in ps if isinstance(p, dict)]

    return out


def _extract_planet_house_map(kundali: Dict[str, Any]) -> Dict[str, int]:
    """
    Returns {planet_name: house_number}
    """
    out: Dict[str, int] = {}

    planets = kundali.get("planets")
    if isinstance(planets, list):
        for p in planets:
            if not isinstance(p, dict):
                continue
            name = p.get("name")
            house = p.get("house")
            if _non_empty_str(name):
                try:
                    out[name] = int(house)
                except Exception:
                    pass

    if not out:
        hp = _extract_house_planets(kundali)
        for hn, ps in hp.items():
            for p in ps:
                name = p.get("name")
                if _non_empty_str(name):
                    out[name] = hn

    return out


def _get_house_sign(kundali: Dict[str, Any], house_no: int) -> str | None:
    houses = kundali.get("houses")
    if isinstance(houses, list):
        for h in houses:
            if int(h.get("house", -1)) == house_no:
                return h.get("sign")

    d1 = (kundali.get("charts", {}).get("D1", {}).get("houses"))
    if isinstance(d1, list):
        for h in d1:
            if int(h.get("house", -1)) == house_no:
                return h.get("sign")

    return None


def _get_house_lord(kundali: Dict[str, Any], house_no: int) -> str | None:
    sign = _get_house_sign(kundali, house_no)
    return SIGN_LORD.get(sign) if sign else None

# -------------------------------------------------
# CORE SCORING LOGIC
# -------------------------------------------------

def _compute_love_marriage_pct(
    lang: str,
    kundali: Dict[str, Any],
    *,
    fallback_mode: bool,
) -> Dict[str, Any]:

    hp = _extract_house_planets(kundali)
    ph = _extract_planet_house_map(kundali)

    score = 50.0
    reasons: List[str] = []

    # 1️⃣ Direct activation
    if 5 in hp:
        score += 10
        reasons.append(_t(lang, "5th house active (romance).", "5वां भाव सक्रिय (रोमांस)।"))
    if 7 in hp:
        score += 10
        reasons.append(_t(lang, "7th house active (marriage).", "7वां भाव सक्रिय (विवाह)।"))

    # 2️⃣ 5th–7th lord linkage
    lord5 = _get_house_lord(kundali, 5)
    lord7 = _get_house_lord(kundali, 7)

    h_lord5 = ph.get(lord5) if lord5 else None
    h_lord7 = ph.get(lord7) if lord7 else None

    if h_lord5 == 7 or h_lord7 == 5:
        score += 20
        reasons.append(_t(lang, "Strong 5th–7th lord exchange.", "5वां–7वां स्वामी परिवर्तन योग।"))
    elif h_lord5 is not None and h_lord5 == h_lord7:
        score += 15
        reasons.append(_t(lang, "5th and 7th lords conjunct.", "5वां और 7वां स्वामी युति।"))

    # 3️⃣ Venus support
    if ph.get("Venus") in (5, 7):
        score += 10
        reasons.append(_t(lang, "Venus supports love marriage.", "शुक्र लव मैरिज को सपोर्ट करता है।"))

    # 4️⃣ Rahu (mild)
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

    if fallback_mode:
        reasons.append(_t(
            lang,
            "Fallback mode used (Moon + 5th house reference).",
            "फॉलबैक मोड (चंद्र + 5वां भाव) उपयोग हुआ।",
        ))

    score = _clamp(score, 0, 100)

    band = "High" if score >= 70 else "Medium" if score >= 50 else "Low"

    return {
        "pct": round(score, 0),
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
    """
    FINAL compiler entrypoint
    """

    lang = _ensure_lang(payload.get("language", "en"))
    case = payload.get("case", "UNKNOWN")

    user = payload.get("user") or {}
    partner = payload.get("partner") or {}

    kundali_user = payload.get("kundali_user") or {}
    kundali_partner = payload.get("kundali_partner") or {}

    user_fallback = case != "A_FULL_DUAL" or not kundali_user
    partner_fallback = case != "A_FULL_DUAL" or not kundali_partner

    user_out = _compute_love_marriage_pct(lang, kundali_user, fallback_mode=user_fallback)
    partner_out = (
        _compute_love_marriage_pct(lang, kundali_partner, fallback_mode=partner_fallback)
        if kundali_partner else None
    )

    overall_line = (
        _t(
            lang,
            f"User: {user_out['pct']}% ({user_out['band']}), Partner: {partner_out['pct']}% ({partner_out['band']}).",
            f"यूज़र: {user_out['pct']}% ({user_out['band']}), पार्टनर: {partner_out['pct']}% ({partner_out['band']})।",
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
