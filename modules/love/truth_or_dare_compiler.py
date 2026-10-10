# modules/love/truth_or_dare_compiler.py
# Jyotishasha — Truth or Dare (Relationship Reality Check)
# LOCKED DESIGN: Compiler only, no Flask, no DB

from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime, timezone


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_lang(lang: str) -> str:
    return "hi" if (lang or "").lower() == "hi" else "en"


def _t(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en


def _extract_house_planets(kundali: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    """
    Returns only NON-EMPTY houses.
    Accepts common kundali shapes.
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
                out[h] = v
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
            planets = h.get("planets")
            if isinstance(planets, list) and planets:
                out[hn] = planets
        return out

    return out


# =========================================================
# MAIN COMPILER
# =========================================================

def compile_truth_or_dare(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Payload EXPECTS:
    - language
    - user
    - partner
    - kundali_user (optional)
    - kundali_partner (optional)
    - case: A_FULL_DUAL | B_DOB_ONLY_HYBRID
    """

    lang = _ensure_lang(payload.get("language", "en"))
    case = payload.get("case", "UNKNOWN")

    kundali_user = payload.get("kundali_user") or {}
    kundali_partner = payload.get("kundali_partner") or {}

    # ----------------------------
    # Determine fallback mode
    # ----------------------------
    fallback_mode = (case != "A_FULL_DUAL")

    # ----------------------------
    # Extract house data
    # ----------------------------
    user_houses = _extract_house_planets(kundali_user)
    partner_houses = _extract_house_planets(kundali_partner)

    # ----------------------------
    # TEMP LAGNA RULE (LOCKED)
    # ----------------------------
    # Fallback → user 5th house acts as Lagna
    effective_lagna_house = 1
    if fallback_mode:
        effective_lagna_house = 5

        # 🔒 LOCKED: use user houses as proxy if partner kundali missing
        if not partner_houses and effective_lagna_house in user_houses:
            partner_houses = user_houses

    # ----------------------------
    # SIGNAL EVALUATION
    # ----------------------------
    score = 0

    romance_reason = ""
    commitment_reason = ""
    bonding_reason = ""

    # Romance (5th house)
    if 5 in partner_houses:
        score += 2
        romance_reason = _t(
            lang,
            "Partner shows natural romantic inclination.",
            "पार्टनर में स्वाभाविक रोमांटिक प्रवृत्ति दिखती है।"
        )
    else:
        score -= 1
        romance_reason = _t(
            lang,
            "Partner may struggle to express romance consistently.",
            "पार्टनर को रोमांस व्यक्त करने में कठिनाई हो सकती है।"
        )

    # Commitment (7th house)
    if 7 in partner_houses:
        score += 2
        commitment_reason = _t(
            lang,
            "Partner shows seriousness toward long-term commitment.",
            "पार्टनर दीर्घकालिक कमिटमेंट को लेकर गंभीर दिखता है।"
        )
    else:
        score -= 2
        commitment_reason = _t(
            lang,
            "Partner commitment patterns look unstable.",
            "पार्टनर का कमिटमेंट पैटर्न अस्थिर दिखता है।"
        )

    # Venus indicator (bonding / attraction)
    venus_present = any(
        p.get("name") == "Venus"
        for ps in partner_houses.values()
        for p in ps
    )

    if venus_present:
        score += 1
        bonding_reason = _t(
            lang,
            "Attraction and bonding indicators are active.",
            "आकर्षण और बॉन्डिंग के संकेत सक्रिय हैं।"
        )
    else:
        bonding_reason = _t(
            lang,
            "Emotional bonding requires conscious effort.",
            "भावनात्मक बॉन्डिंग के लिए सचेत प्रयास की आवश्यकता है।"
        )

    # ----------------------------
    # FINAL VERDICT
    # ----------------------------
    verdict = "TRUTH" if score >= 2 else "DARE"
    confidence = "high" if not fallback_mode else "low"

    # Describes the chart indicators only -- never a judgement that the relationship is "safe" or "risky".
    verdict_line = _t(
        lang,
        f"Verdict: {verdict} — "
        f"{'the chart indicators look supportive for this relationship.' if verdict == 'TRUTH' else 'the chart indicators point to areas that need extra care and honest conversation.'}",
        f"निर्णय: {verdict} — "
        f"{'कुंडली के संकेत इस रिश्ते के लिए सहायक दिखते हैं।' if verdict == 'TRUTH' else 'कुंडली के संकेत कुछ ऐसे पहलू दिखाते हैं जिन पर अतिरिक्त ध्यान और खुली बातचीत ज़रूरी है।'}"
    )

    # ----------------------------
    # BLOCKS (FIXED & SAFE)
    # ----------------------------
    blocks = [
        {
            "id": "partner_romantic_nature",
            "title": _t(lang, "Romantic Nature", "रोमांटिक स्वभाव"),
            "text": romance_reason,
        },
        {
            "id": "partner_commitment_intent",
            "title": _t(lang, "Commitment Intent", "कमिटमेंट की मंशा"),
            "text": commitment_reason,
        },
        {
            "id": "bonding_attraction",
            "title": _t(lang, "Bonding & Attraction", "बॉन्डिंग और आकर्षण"),
            "text": bonding_reason,
        },
        {
            "id": "current_phase",
            "title": _t(lang, "Current Relationship Phase", "वर्तमान रिलेशनशिप चरण"),
            "text": _t(
                lang,
                "Relationship outcome depends strongly on timing and emotional maturity.",
                "रिश्ते का परिणाम समय और भावनात्मक परिपक्वता पर निर्भर करता है।"
            ),
        },
    ]

    # ----------------------------
    # DISCLAIMERS
    # ----------------------------
    disclaimers = [
        _t(
            lang,
            "This tool evaluates partner suitability for love relationships.",
            "यह टूल प्रेम संबंधों के लिए पार्टनर की उपयुक्तता आंकता है।"
        )
    ]

    if fallback_mode:
        disclaimers.append(
            _t(
                lang,
                "Result is based on Moon and 5th-house fallback due to limited birth details.",
                "सीमित जन्म विवरण के कारण परिणाम चंद्रमा और पंचम भाव पर आधारित है।"
            )
        )

    return {
        "type": "tool",
        "tool_id": "truth_or_dare",
        "generated_at": _utc_iso(),
        "verdict": verdict,
        "confidence": confidence,
        "verdict_line": verdict_line,
        "score": score,
        "blocks": blocks,
        "disclaimers": disclaimers,
        "meta": {
            "case": case,
            "fallback_mode": fallback_mode,
            "effective_lagna_house": effective_lagna_house,
        },
        "version": "1.0"
    }
