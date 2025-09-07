# mangalik_dosh_logic.py
# Generate structured, human-friendly Mangal Dosh (Kuja Dosha) report in English/Hindi.
# Drop-in helper: call generate_mangal_dosh_report(kundali, language="en"|"hi")

from typing import Any, Dict, List, Optional, Tuple

MD_HOUSES = {1, 2, 4, 7, 8, 12}
KENDRA_HOUSES = {1, 4, 7, 10}

SIGN_HI = {
    "Aries": "मेष", "Taurus": "वृषभ", "Gemini": "मिथुन", "Cancer": "कर्क",
    "Leo": "सिंह", "Virgo": "कन्या", "Libra": "तुला", "Scorpio": "वृश्चिक",
    "Sagittarius": "धनु", "Capricorn": "मकर", "Aquarius": "कुम्भ", "Pisces": "मीन"
}

LANG = {
    "en": {
        "heading": "Mangal Dosh Analysis",
        "human_status": {
            "Strong": "Yes, you are Mangalic",
            "Partial": "Yes, you are Mangalic (Mitigated/Partial)",
            "Cancelled": "Mangal Dosh is not present (Cancelled due to special combinations)",
            "None": "You are not Mangalic"
        },
        "paragraphs": {
            "lagna_trigger": "Mars is in the {mars_house_from_lagna} house from Lagna in {mars_sign}, which is traditionally considered a Mangal Dosh position and may influence partnerships, timing of marriage, and domestic harmony.",
            "moon_trigger": "From the Moon, Mars occupies the {mars_house_from_moon} house in {mars_sign}. This placement can sensitize emotional responses and may contribute to Mangal Dosh indications if not otherwise balanced.",
            "own_or_exalted_cancellation": "Because Mars is in {mars_sign}, which counts as own/exalted dignity, the harsher side of Mangal Dosh is significantly reduced, often converting sharpness into constructive drive.",
            "jupiter_kendra_cancellation": "Protective influence: Jupiter positioned in a Kendra (houses 1/4/7/10) from Lagna ({jupiter_house_from_lagna}) or Moon ({jupiter_house_from_moon}) tends to neutralize Mangal Dosh by adding wisdom, patience, and grace to relationships.",
            "benefic_on_mars_cancellation": "Benefic support is present: {benefics_aspecting} aspect(s) or {benefics_conjunct} conjunction(s) with Mars soften the intensity, encouraging cooperative problem‑solving and balanced commitments."
        },
        "summary_heading": "Mangal Dosh Summary",
        "summary_points": [
            "Trigger status: {trigger_status_text}.",
            "Mitigations: {mitigations_joined}.",
            "Overall severity: {final_strength}."
        ],
        "general_explanation": (
            "According to Vedic Astrology, Mangal Dosh (Kuja Dosha) is indicated when Mars occupies the 1st, 2nd, 4th, "
            "7th, 8th, or 12th house from Lagna or the Moon. Potential challenges relate to timing and harmony in marriage, "
            "temper, and domestic peace. However, dignities (own/exalted), Jupiter’s placement in Kendra, and benefic aspect/"
            "conjunction can reduce or cancel the Dosha. Practical remedies include patience in commitments, counseling, and "
            "spiritual observances tailored to the native’s chart."
        ),
        "labels": {
            "Strong": "Strong", "Partial": "Partial", "Cancelled": "Cancelled", "None": "None",
            "none": "None"
        }
    },
    "hi": {
        "heading": "मंगल दोष विश्लेषण",
        "human_status": {
            "Strong": "हाँ, आप मंगलीक हैं",
            "Partial": "हाँ, आप मंगलीक हैं (शमन/आंशिक)",
            "Cancelled": "विशेष संयोजन के कारण मंगल दोष उपस्थित नहीं है",
            "None": "आप मंगलीक नहीं हैं"
        },
        "paragraphs": {
            "lagna_trigger": "लग्न से मंगल {mars_house_from_lagna} भाव में {mars_sign} राशि में है। यह स्थान परम्परागत रूप से मंगल दोष का कारक माना जाता है और विवाह, साझेदारी तथा घरेलू सामंजस्य को प्रभावित कर सकता है।",
            "moon_trigger": "चंद्र से मंगल {mars_house_from_moon} भाव में {mars_sign} राशि में स्थित है। यह स्थिति भावनात्मक प्रतिक्रिया को संवेदनशील बनाती है और यदि संतुलन न हो तो मंगल दोष को बल दे सकती है।",
            "own_or_exalted_cancellation": "चूंकि मंगल {mars_sign} राशि में है, जो इसकी स्वयं की अथवा उच्च राशि मानी जाती है, इसलिए मंगल दोष का तीव्र प्रभाव कम होकर ऊर्जा सकारात्मक दिशा में रूपांतरित हो जाता है।",
            "jupiter_kendra_cancellation": "रक्षक प्रभाव: गुरु लग्न ({jupiter_house_from_lagna}) अथवा चंद्र ({jupiter_house_from_moon}) से केन्द्र (1/4/7/10) में स्थित है। यह मंगल दोष को काफी हद तक शान्त करता है और वैवाहिक जीवन में धैर्य व सौम्यता लाता है।",
            "benefic_on_mars_cancellation": "शुभ प्रभाव उपस्थित है: {benefics_aspecting} दृष्टि या {benefics_conjunct} की युति मंगल पर है, जिससे दोष का प्रभाव नरम होकर सामंजस्य और संतुलन बढ़ता है।"
        },
        "summary_heading": "मंगल दोष सारांश",
        "summary_points": [
            "दोष स्थिति: {trigger_status_text}.",
            "शमन कारण: {mitigations_joined}.",
            "समग्र तीव्रता: {final_strength}."
        ],
        "general_explanation": (
            "वैदिक ज्योतिष के अनुसार मंगल दोष तब बनता है जब मंगल लग्न या चंद्र से 1, 2, 4, 7, 8 या 12 भाव में होता है। "
            "इसका प्रभाव विवाह, पारिवारिक जीवन और स्वभाव में जल्दबाजी के रूप में देखा जाता है। परन्तु यदि मंगल अपनी ही राशि "
            "(मेष, वृश्चिक) या उच्च राशि (मकर) में हो, अथवा बृहस्पति केन्द्र में हो या मंगल पर शुभ दृष्टि/युति हो, तो यह दोष रद्द "
            "हो सकता है। व्यावहारिक उपायों में संयम, वैवाहिक परामर्श और धार्मिक उपाय शामिल हैं।"
        ),
        "labels": {
            "Strong": "उच्च", "Partial": "मध्यम", "Cancelled": "रद्द", "None": "न्यून",
            "none": "नहीं"
        }
    }
}

# ----------------------------
# Utilities
# ----------------------------

def _get_planet(planets: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for p in planets or []:
        if p.get("name", "").lower() == name.lower():
            return p
    return {}

def _to_int(x: Any) -> Optional[int]:
    try:
        v = int(x)
        return v if 1 <= v <= 12 else None
    except Exception:
        return None

def _compute_house_from_moon_fallback(planets: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
    """Return (mars_from_lagna, mars_from_moon) using available fields. If moon-based missing,
    derive via lagna houses if both Mars & Moon have 'house_from_lagna'."""
    mars = _get_planet(planets, "Mars")
    moon = _get_planet(planets, "Moon")
    m_lagna = _to_int(mars.get("house_from_lagna") or mars.get("house"))
    m_moon = _to_int(mars.get("house_from_moon"))
    if not m_moon:
        moon_lagna = _to_int(moon.get("house_from_lagna") or moon.get("house"))
        if m_lagna and moon_lagna:
            diff = (m_lagna - moon_lagna) % 12
            m_moon = diff if diff != 0 else 12
    return m_lagna, m_moon

def _mars_own_or_exalted(sign: str) -> bool:
    return sign in {"Aries", "Scorpio", "Capricorn"}

def _is_kendra(h: Optional[int]) -> bool:
    return bool(h and h in KENDRA_HOUSES)

def _collect_names(entries: Any) -> List[str]:
    out = []
    for e in entries or []:
        if isinstance(e, str):
            out.append(e)
        elif isinstance(e, dict):
            n = e.get("name")
            if n: out.append(n)
    return out

def _benefic_support_flags(mars: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    asp = _collect_names(mars.get("aspected_by"))
    conj = _collect_names(mars.get("conjunct"))
    has_benefic = any(n in {"Jupiter", "Venus", "Mercury"} for n in set(asp + conj))
    return has_benefic, asp, conj

def _trigger_text(lang: str, from_lagna: bool, from_moon: bool) -> str:
    if lang == "hi":
        if from_lagna and from_moon: return "लग्न और चंद्र – दोनों से सक्रिय"
        if from_lagna: return "केवल लग्न से सक्रिय"
        if from_moon: return "केवल चंद्र से सक्रिय"
        return "कोई सक्रिय ट्रिगर नहीं"
    else:
        if from_lagna and from_moon: return "Triggered from both Lagna and Moon"
        if from_lagna: return "Triggered from Lagna only"
        if from_moon: return "Triggered from Moon only"
        return "No active trigger"

def _strength_label(lang: str, strength: str) -> str:
    return LANG[lang]["labels"].get(strength, strength)

def _format_list(items: List[str], lang: str) -> str:
    if not items:
        return "None" if lang == "en" else "कोई नहीं"
    return ", ".join(items)

# ----------------------------
# Scoring & Decision
# ----------------------------

def _severity_score(from_lagna: bool, from_moon: bool,
                    own_exalted: bool, jup_kendra: bool, benefic_support: bool) -> Tuple[str, List[str]]:
    """Return (final_strength, mitigation_reasons) using a simple transparent scoring."""
    triggers = int(bool(from_lagna)) + int(bool(from_moon))  # 0..2
    mit_reasons = []
    cancel_score = 0

    if own_exalted:
        cancel_score += 1
        mit_reasons.append("Mars in own/exalted sign")
    if jup_kendra:
        cancel_score += 1
        mit_reasons.append("Jupiter in Kendra (from Lagna/Moon)")
    if benefic_support:
        cancel_score += 1
        mit_reasons.append("Benefic aspect/conjunction on Mars")

    if triggers == 0:
        return "None", []

    # Convert trigger minus mitigation to final strength
    severity_raw = max(0, triggers - cancel_score)
    if severity_raw == 0:
        return "Cancelled", mit_reasons
    if severity_raw == 1:
        return "Partial", mit_reasons
    return "Strong", mit_reasons

# ----------------------------
# Main API
# ----------------------------

def generate_mangal_dosh_report(kundali: Dict[str, Any], language: str = "en") -> Dict[str, Any]:
    """
    kundali expects:
      {
        "lagna_sign": "Libra", "moon_sign": "Cancer",
        "planets": [
           {
             "name":"Mars","sign":"Scorpio",
             "house_from_lagna":7,"house_from_moon":12,
             "aspected_by":[{"name":"Jupiter"}],
             "conjunct":[]
           },
           {"name":"Jupiter","house_from_lagna":4,"house_from_moon":10}
        ]
      }
    """
    lang = "hi" if language.lower() == "hi" else "en"
    L = LANG[lang]

    planets = kundali.get("planets", [])
    mars = _get_planet(planets, "Mars")
    jup = _get_planet(planets, "Jupiter")

    mars_sign_en = mars.get("sign") or "Unknown"
    mars_sign_hi = SIGN_HI.get(mars_sign_en, mars_sign_en)
    mars_sign = mars_sign_hi if lang == "hi" else mars_sign_en

    m_lagna, m_moon = _compute_house_from_moon_fallback(planets)

    from_lagna = bool(m_lagna and m_lagna in MD_HOUSES)
    from_moon = bool(m_moon and m_moon in MD_HOUSES)

    own_exalted = _mars_own_or_exalted(mars_sign_en)
    j_lagna = _to_int(jup.get("house_from_lagna"))
    j_moon = _to_int(jup.get("house_from_moon"))
    jup_kendra = _is_kendra(j_lagna) or _is_kendra(j_moon)
    benefic_ok, asp_list, conj_list = _benefic_support_flags(mars)

    final_strength, mitigations = _severity_score(from_lagna, from_moon, own_exalted, jup_kendra, benefic_ok)
    human_status = L["human_status"][final_strength]

    # Build condition paragraphs (active ones only)
    P = L["paragraphs"]
    paragraphs: List[str] = []

    if from_lagna:
        paragraphs.append(
            P["lagna_trigger"].format(
                mars_house_from_lagna=m_lagna or "",
                mars_sign=mars_sign
            )
        )
    if from_moon:
        paragraphs.append(
            P["moon_trigger"].format(
                mars_house_from_moon=m_moon or "",
                mars_sign=mars_sign
            )
        )

    if own_exalted:
        paragraphs.append(
            P["own_or_exalted_cancellation"].format(
                mars_sign=mars_sign
            )
        )

    if jup_kendra:
        paragraphs.append(
            P["jupiter_kendra_cancellation"].format(
                jupiter_house_from_lagna=j_lagna or "",
                jupiter_house_from_moon=j_moon or ""
            )
        )

    if benefic_ok:
        paragraphs.append(
            P["benefic_on_mars_cancellation"].format(
                benefics_aspecting=_format_list(asp_list, lang),
                benefics_conjunct=_format_list(conj_list, lang)
            )
        )

    # Summary block
    trigger_status_text = _trigger_text(lang, from_lagna, from_moon)
    mitigations_joined = _format_list(mitigations, lang)
    summary_points = [
        L["summary_points"][0].format(trigger_status_text=trigger_status_text),
        L["summary_points"][1].format(mitigations_joined=mitigations_joined),
        L["summary_points"][2].format(final_strength=_strength_label(lang, final_strength))
    ]

    # Compose final structure
    result: Dict[str, Any] = {
        "tool": "mangal-dosh",
        "language": lang,
        "heading": L["heading"],
        "status": {
            "is_mangalic": human_status,
            "strength": final_strength
        },
        "context": {
            "lagna_sign": kundali.get("lagna_sign"),
            "moon_sign": kundali.get("moon_sign"),
            "mars_sign": mars_sign_en if lang == "en" else mars_sign_hi,
            "mars_house_from_lagna": m_lagna or 0,
            "mars_house_from_moon": m_moon or 0,
            "benefic_aspects_on_mars": asp_list,
            "benefic_conjunctions_with_mars": conj_list,
            "jupiter_house_from_lagna": j_lagna or 0,
            "jupiter_house_from_moon": j_moon or 0,
            "cancellation_flags": {
                "mars_own_or_exalted": own_exalted,
                "jupiter_in_kendra_from_lagna_or_moon": bool(jup_kendra),
                "benefic_aspect_or_conjunction_on_mars": bool(benefic_ok)
            }
        },
        "evaluation": {
            "triggers": {
                "from_lagna": from_lagna,
                "from_moon": from_moon
            },
            "mitigations": mitigations,
            "final_strength": final_strength
        },
        "report_paragraphs": paragraphs,  # rendered personalized paragraphs (order: triggers → cancellations)
        "summary_block": {
            "heading": L["summary_heading"],
            "points": summary_points
        },
        "general_explanation": L["general_explanation"]
    }

    return result

# ----------------------------
# (Optional) Quick self-test
# ----------------------------
if __name__ == "__main__":
    sample = {
        "lagna_sign": "Libra",
        "moon_sign": "Cancer",
        "planets": [
            {"name": "Mars", "sign": "Scorpio", "house_from_lagna": 7, "house_from_moon": 12,
             "aspected_by": [{"name": "Jupiter"}], "conjunct": []},
            {"name": "Jupiter", "sign": "Taurus", "house_from_lagna": 4, "house_from_moon": 10},
            {"name": "Moon", "sign": "Cancer", "house_from_lagna": 10, "house_from_moon": 1}
        ]
    }
    from pprint import pprint
    print("\n--- EN ---")
    pprint(generate_mangal_dosh_report(sample, "en"))
    print("\n--- HI ---")
    pprint(generate_mangal_dosh_report(sample, "hi"))

# ✅ EXPORT for backend use
build_manglik_dosh = generate_mangal_dosh_report
