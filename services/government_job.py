from typing import Dict, Any, List, Optional

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}

EXALTED = {"Sun": "Aries", "Mars": "Capricorn", "Jupiter": "Cancer", "Saturn": "Libra"}
DEBILITATED = {"Sun": "Libra", "Mars": "Cancer", "Jupiter": "Capricorn", "Saturn": "Aries"}

PLANET_HI = {"Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
             "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि", "Rahu": "राहु", "Ketu": "केतु"}

STATUS_HI = {"exalted": "उच्च", "own": "स्वराशि", "debilitated": "नीच", "neutral": "सामान्य"}

HOUSE_HI = {
    1: "लग्न", 2: "द्वितीय", 3: "तृतीय", 4: "चतुर्थ", 5: "पंचम",
    6: "षष्ठ", 7: "सप्तम", 8: "अष्टम", 9: "नवम", 10: "दशम",
    11: "एकादश", 12: "द्वादश",
}

def _safe_planets(k: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = (k or {}).get("planets", [])
    planets = {}
    for item in raw:
        pname = item.get("name")
        if pname:
            planets[pname] = {"house": item.get("house"), "sign": item.get("sign")}
    return planets

def _lagna_index(k: Dict[str, Any]) -> int:
    lagna_sign = (k or {}).get("lagna_sign")
    return SIGNS.index(lagna_sign) if lagna_sign in SIGNS else 0

def _house_rashi(lagna_index: int, house_number: int) -> str:
    idx = (lagna_index + house_number - 1) % 12
    return SIGNS[idx]

def _house_lord(lagna_index: int, house_number: int) -> str:
    return SIGN_LORDS[_house_rashi(lagna_index, house_number)]

def _planet_info(planets: Dict[str, Dict[str, Any]], planet: str):
    info = planets.get(planet, {})
    return info.get("sign"), info.get("house")

def _get_status(planet: str, sign: Optional[str]) -> str:
    if not sign: return "neutral"
    if sign == EXALTED.get(planet): return "exalted"
    if sign == DEBILITATED.get(planet): return "debilitated"
    if SIGN_LORDS.get(sign) == planet: return "own"
    return "neutral"


# ---------------------- MAIN BUILDER -------------------------
def build_government_job(kundali_data: Dict[str, Any], lang: str = "en") -> Dict[str, Any]:
    lang = "hi" if str(lang).lower().startswith("hi") else "en"
    planets = _safe_planets(kundali_data)
    lagna_idx = _lagna_index(kundali_data)

    # Key houses for service/govt jobs: 6th (competition), 10th (career)
    lord6 = _house_lord(lagna_idx, 6)
    lord10 = _house_lord(lagna_idx, 10)

    l6_sign, l6_house = _planet_info(planets, lord6)
    l10_sign, l10_house = _planet_info(planets, lord10)

    l6_status = _get_status(lord6, l6_sign)
    l10_status = _get_status(lord10, l10_sign)

    positive, negative = [], []

    # ---- Positive conditions ----
    if l10_status in {"own", "exalted"}:
        positive.append({
            "en": f"Strong 10th lord ({lord10}) indicates career stability and chances of government role.",
            "hi": f"मज़बूत दशमेश ({PLANET_HI.get(lord10, lord10)}) करियर स्थिरता और सरकारी भूमिका के अवसर देता है।"
        })
    if l6_status in {"own", "exalted"}:
        positive.append({
            "en": f"Strong 6th lord ({lord6}) shows ability to face competition and exams.",
            "hi": f"मज़बूत षष्ठेश ({PLANET_HI.get(lord6, lord6)}) प्रतियोगिता और परीक्षाओं का सामना करने की क्षमता दर्शाता है।"
        })

    # ---- Negative / obstacles ----
    if l10_status == "debilitated":
        negative.append({
            "en": f"Weak 10th lord ({lord10}) may bring obstacles in achieving authority.",
            "hi": f"कमज़ोर दशमेश ({PLANET_HI.get(lord10, lord10)}) सरकारी पद में बाधाएँ ला सकता है।"
        })
    if l6_status == "debilitated":
        negative.append({
            "en": f"Weak 6th lord ({lord6}) shows struggle in competitive exams.",
            "hi": f"कमज़ोर षष्ठेश ({PLANET_HI.get(lord6, lord6)}) प्रतियोगी परीक्षाओं में संघर्ष दिखाता है।"
        })

    # Always add a normalized line if nothing got appended
    if not positive:
        positive.append({
            "en": "Neither your 6th house lord nor your 10th house lord is exalted or in its own sign, so this check found no special strength for a government career.",
            "hi": "आपके छठे और दसवें भाव के स्वामी न उच्च के हैं न स्वराशि में, इसलिए इस जाँच में सरकारी करियर के लिए कोई विशेष बल नहीं मिला।"
        })
    if not negative:
        negative.append({
            "en": "Neither your 6th house lord nor your 10th house lord is debilitated, so this check found no specific weakness.",
            "hi": "आपके छठे और दसवें भाव के स्वामियों में से कोई भी नीच का नहीं है, इसलिए इस जाँच में कोई विशेष कमज़ोरी नहीं मिली।"
        })

    result = {
        "heading": {"en": "Government Job Potential", "hi": "सरकारी नौकरी की संभावना"}[lang],
        "positive_points": positive,
        "negative_points": negative,
        "verdict": {
            "en": "A quick check of your 6th and 10th house lords",
            "hi": "आपके छठे और दसवें भाव के स्वामियों की एक त्वरित जाँच"
        }[lang],
        "cta": {
            "en": "Get a detailed government job report based on your birth chart and current dasha period.",
            "hi": "अपनी जन्म कुंडली और वर्तमान दशा अवधि पर आधारित सरकारी नौकरी की विस्तृत रिपोर्ट पाएँ।"
        }[lang]
    }

    return result
