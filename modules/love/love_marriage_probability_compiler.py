# modules/love/love_marriage_probability_compiler.py
# Jyotishasha — Love Marriage Probability (Tool #3)
# LOCKED: compiler only, no Flask, no DB

from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_lang(lang: str) -> str:
    return "hi" if (lang or "").lower().strip() == "hi" else "en"


def _t(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en


def _non_empty_str(x: Any) -> bool:
    return isinstance(x, str) and x.strip() != ""


# ---------- Safe kundali readers (works across shapes) ----------

def _extract_house_planets(kundali: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    """
    Returns {house: [planet_dicts]} for NON-EMPTY houses only.
    Accepts:
      - kundali["house_planets"] as dict
      - kundali["houses"] as list
      - kundali["charts"]["D1"]["houses"] as list (optional)
    """
    out: Dict[int, List[Dict[str, Any]]] = {}

    hp = kundali.get("house_planets")
    if isinstance(hp, dict):
        for k, v in hp.items():
            try:
                h = int(k)
            except Exception:
                continue
            if isinstance(v, list) and v:
                out[h] = [p for p in v if isinstance(p, dict)]
        return out

    houses = kundali.get("houses")
    if isinstance(houses, list):
        for h in houses:
            if not isinstance(h, dict):
                continue
            hn = h.get("house") or h.get("number")
            try:
                hn = int(hn)
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
            hn = h.get("house") or h.get("number")
            try:
                hn = int(hn)
            except Exception:
                continue
            ps = h.get("planets")
            if isinstance(ps, list) and ps:
                out[hn] = [p for p in ps if isinstance(p, dict)]
        return out

    return out


def _extract_planet_house_map(kundali: Dict[str, Any]) -> Dict[str, int]:
    """
    Returns {planet_name: house_number} if available.
    Supports:
      - kundali["planets"] list with 'house'
      - derived from house_planets
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
                    hn = int(house)
                    out[name] = hn
                except Exception:
                    pass

    # If not found, derive from houses
    if not out:
        hp = _extract_house_planets(kundali)
        for hn, ps in hp.items():
            for p in ps:
                name = p.get("name")
                if _non_empty_str(name):
                    out[name] = hn

    return out


def _extract_house_lords(kundali: Dict[str, Any]) -> Dict[int, str]:
    """
    Returns {house_number: lord_planet_name} if available.
    Supports:
      - kundali["house_lords"] dict
      - kundali["houses"] list containing 'lord' / 'house_lord'
    """
    out: Dict[int, str] = {}

    hl = kundali.get("house_lords")
    if isinstance(hl, dict):
        for k, v in hl.items():
            try:
                hn = int(k)
            except Exception:
                continue
            if _non_empty_str(v):
                out[hn] = str(v).strip()
        if out:
            return out

    houses = kundali.get("houses")
    if isinstance(houses, list):
        for h in houses:
            if not isinstance(h, dict):
                continue
            hn = h.get("house") or h.get("number")
            try:
                hn = int(hn)
            except Exception:
                continue
            lord = h.get("lord") or h.get("house_lord")
            if _non_empty_str(lord):
                out[hn] = str(lord).strip()

    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------- Core scoring (simple + stable) ----------

def _compute_love_marriage_pct(
    lang: str,
    kundali: Dict[str, Any],
    *,
    fallback_mode: bool,
) -> Dict[str, Any]:
    """
    Returns:
      { pct, band, reasons[], meta{} }
    RULE:
      - Fallback: treat 5th house as Lagna (we still only talk about 5th/7th signals)
      - Do NOT mention empty houses; only use detected placements/relations
    """
    hp = _extract_house_planets(kundali)
    ph = _extract_planet_house_map(kundali)
    hl = _extract_house_lords(kundali)

    score = 50.0
    reasons: List[str] = []

    # 1) Direct activation
    if 5 in hp:
        score += 10
        reasons.append(_t(lang, "5th house is activated (romance signal).", "5वां भाव सक्रिय है (रोमांस संकेत)।"))
    if 7 in hp:
        score += 10
        reasons.append(_t(lang, "7th house is activated (marriage/commitment signal).", "7वां भाव सक्रिय है (विवाह/कमिटमेंट संकेत)।"))

    # 2) 5th–7th linkage via lords (best simple Vedic check)
    lord5 = hl.get(5)
    lord7 = hl.get(7)

    if _non_empty_str(lord5) and _non_empty_str(lord7):
        h_lord5 = ph.get(lord5)
        h_lord7 = ph.get(lord7)

        # Exchange / mutual connection
        if h_lord5 == 7 or h_lord7 == 5:
            score += 20
            reasons.append(_t(lang, "Strong 5th–7th lord linkage (love → marriage pathway).",
                              "5वें-7वें स्वामी का मजबूत संबंध (लव → मैरिज योग)।"))
        # Conjunction / same house
        elif h_lord5 is not None and h_lord7 is not None and h_lord5 == h_lord7:
            score += 15
            reasons.append(_t(lang, "5th and 7th lords connect (supports love marriage).",
                              "5वें और 7वें स्वामी का योग (लव मैरिज सपोर्ट)।"))

    # 3) Venus support (secondary)
    venus_house = ph.get("Venus")
    if venus_house in (5, 7):
        score += 10
        reasons.append(_t(lang, "Venus supports romance/commitment.", "शुक्र रोमांस/कमिटमेंट को सपोर्ट करता है।"))

    # 4) Rahu support (optional unconventional marker) — keep mild
    rahu_house = ph.get("Rahu")
    if rahu_house in (5, 7):
        score += 5
        reasons.append(_t(lang, "Rahu influence can indicate non-traditional choices.", "राहु प्रभाव गैर-पारंपरिक निर्णय दिखा सकता है।"))

    # 5) Heavy pressure (mild deductions)
    saturn_house = ph.get("Saturn")
    mars_house = ph.get("Mars")
    if saturn_house in (5, 7):
        score -= 5
        reasons.append(_t(lang, "Saturn may delay or demand maturity in commitment.", "शनि देरी या परिपक्वता की मांग दिखा सकता है।"))
    if mars_house in (5, 7):
        score -= 5
        reasons.append(_t(lang, "Mars may create impulsive conflicts; needs control.", "मंगल उतावले विवाद ला सकता है; नियंत्रण जरूरी है।"))

    # Fallback handling note (no extra scoring)
    if fallback_mode:
        reasons.append(_t(
            lang,
            "Fallback mode: based on limited birth details (Moon + 5th-house reference).",
            "फॉलबैक मोड: सीमित जन्म विवरण (चंद्र + 5वां भाव संदर्भ) पर आधारित।",
        ))

    score = _clamp(score, 0, 100)

    # Banding
    if score >= 70:
        band = "High"
    elif score >= 50:
        band = "Medium"
    else:
        band = "Low"

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
                "venus_house": venus_house,
                "rahu_house": rahu_house,
                "saturn_house": saturn_house,
                "mars_house": mars_house,
            }
        }
    }


# =========================================================
# PUBLIC COMPILER
# =========================================================

def compile_love_marriage_probability(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Payload EXPECTS:
      - language
      - user: {name,dob,tob,lat,lng} (full recommended)
      - partner: {name,dob,tob,lat,lng} (full recommended)
      - kundali_user (optional)
      - kundali_partner (optional)
      - case: A_FULL_DUAL | B_DOB_ONLY_HYBRID (optional)
    """
    lang = _ensure_lang(payload.get("language", "en"))
    case = payload.get("case") or "UNKNOWN"

    user = payload.get("user") or {}
    partner = payload.get("partner") or {}

    kundali_user = payload.get("kundali_user") or {}
    kundali_partner = payload.get("kundali_partner") or {}

    # If kundali not provided, compiler still returns safe output (but low confidence)
    user_fallback = (case != "A_FULL_DUAL") or not bool(kundali_user)
    partner_fallback = (case != "A_FULL_DUAL") or not bool(kundali_partner)

    user_out = _compute_love_marriage_pct(lang, kundali_user, fallback_mode=user_fallback)
    partner_out = _compute_love_marriage_pct(lang, kundali_partner, fallback_mode=partner_fallback) if kundali_partner else None

    # Simple overall line (frontend-ready)
    if partner_out:
        overall_line = _t(
            lang,
            f"User: {int(user_out['pct'])}% ({user_out['band']}), Partner: {int(partner_out['pct'])}% ({partner_out['band']}).",
            f"यूज़र: {int(user_out['pct'])}% ({user_out['band']}), पार्टनर: {int(partner_out['pct'])}% ({partner_out['band']})।",
        )
    else:
        overall_line = _t(
            lang,
            f"User: {int(user_out['pct'])}% ({user_out['band']}). Partner result needs full birth details.",
            f"यूज़र: {int(user_out['pct'])}% ({user_out['band']})। पार्टनर के लिए पूर्ण जन्म विवरण चाहिए।",
        )

    return {
        "type": "tool",
        "tool_id": "love-marriage-probability",
        "generated_at": _utc_iso(),
        "case": case,
        "overall_line": overall_line,
        "user_result": {
            "name": user.get("name"),
            **user_out,
        },
        "partner_result": ({
            "name": partner.get("name"),
            **partner_out,
        } if partner_out else None),
        "disclaimers": [
            _t(lang, "This tool estimates love-marriage probability from 5th–7th linkage indicators.",
                "यह टूल 5वें–7वें भाव के लिंक संकेतों से लव मैरिज संभावना का अनुमान देता है।"),
        ],
    }
