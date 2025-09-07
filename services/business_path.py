# services/business_favorability.py

from typing import Dict, Any, List, Tuple, Optional

BENEFICS = {"Jupiter", "Venus", "Mercury"}  # classical benefics for commerce
MALefics = {"Saturn", "Mars", "Rahu", "Ketu", "Sun"}  # keep simple; used only for light checks

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}

EXALTED = {
    "Sun": "Aries", "Moon": "Taurus", "Mars": "Capricorn", "Mercury": "Virgo",
    "Jupiter": "Cancer", "Venus": "Pisces", "Saturn": "Libra"
}
DEBILITATED = {
    "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer", "Mercury": "Pisces",
    "Jupiter": "Capricorn", "Venus": "Virgo", "Saturn": "Aries"
}

PLANET_HI = {
    "Sun": "सूर्य",
    "Moon": "चंद्र",
    "Mars": "मंगल",
    "Mercury": "बुध",
    "Jupiter": "गुरु",
    "Venus": "शुक्र",
    "Saturn": "शनि",
    "Rahu": "राहु",
    "Ketu": "केतु"
}

SIGNS_HI = {
    "Aries": "मेष",
    "Taurus": "वृषभ",
    "Gemini": "मिथुन",
    "Cancer": "कर्क",
    "Leo": "सिंह",
    "Virgo": "कन्या",
    "Libra": "तुला",
    "Scorpio": "वृश्चिक",
    "Sagittarius": "धनु",
    "Capricorn": "मकर",
    "Aquarius": "कुंभ",
    "Pisces": "मीन"
}

STATUS_HI = {
    "exalted": "उच्च",
    "own": "स्वराशि",
    "debilitated": "नीच",
    "neutral": "सामान्य",
}

HOUSE_HI = {
    1: "लग्न", 2: "द्वितीय", 3: "तृतीय", 4: "चतुर्थ",
    5: "पंचम", 6: "षष्ठ", 7: "सप्तम", 8: "अष्टम",
    9: "नवम", 10: "दशम", 11: "एकादश", 12: "द्वादश",
}
def _get_status(planet: str, sign: str) -> str:
    if sign == EXALTED.get(planet): return "exalted"
    if sign == DEBILITATED.get(planet): return "debilitated"
    if SIGN_LORDS.get(sign) == planet: return "own"
    return "neutral"

def _safe_planets(k: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = (k or {}).get("planets", [])
    planets = {}
    for item in raw:
        pname = item.get("name")  # ✅ Important: not "planet"
        if pname:
            planets[pname] = {
                "house": item.get("house"),
                "sign": item.get("sign")
            }
    return planets

def _lagna_index(k: Dict[str, Any]) -> int:
    lagna_sign = (k or {}).get("lagna_sign")
    return SIGNS.index(lagna_sign) if lagna_sign in SIGNS else 0  # default Aries if missing

def _house_rashi(lagna_index: int, house_number: int) -> str:
    # house_number: 1..12
    idx = (lagna_index + house_number - 1) % 12
    return SIGNS[idx]

def _house_lord(lagna_index: int, house_number: int) -> str:
    rashi = _house_rashi(lagna_index, house_number)
    return SIGN_LORDS[rashi]

def _planets_in_house(planets: Dict[str, Dict[str, Any]], house_no: int) -> List[str]:
    out = []
    for p, info in planets.items():
        try:
            if int(info.get("house")) == house_no:
                out.append(p)
        except Exception:
            continue
    return out

def _planet_info(planets: Dict[str, Dict[str, Any]], planet: str) -> Tuple[Optional[str], Optional[int]]:
    info = planets.get(planet, {})
    return info.get("sign"), info.get("house")

def _is_benefic_support_on_house(planets: Dict[str, Dict[str, Any]], house_no: int) -> bool:
    for p in BENEFICS:
        if planets.get(p, {}).get("house") == house_no:
            return True
    return False

def _is_rahu_supporting(planets: Dict[str, Dict[str, Any]], houses: List[int]) -> bool:
    sign, house = _planet_info(planets, "Rahu")
    return bool(house in houses) if house is not None else False

def _is_afflicted_for_business(planets: Dict[str, Dict[str, Any]], houses_key: List[int]) -> bool:
    """
    Light-touch affliction: 7th/11th lords debilitated OR Ketu in 7th or 10th.
    """
    afflicted = False
    for h in houses_key:
        # check lord debilitation
        # Note: we need lagna index in outer scope to compute lord; handled by caller.
        pass
    # Simple direct checks:
    if planets.get("Ketu", {}).get("house") in (7, 10):
        afflicted = True
    return afflicted

def build_business_path(kundali_data: Dict[str, Any], lang: str = "en") -> Dict[str, Any]:
    lang = "hi" if str(lang).lower().startswith("hi") else "en"
    planets = _safe_planets(kundali_data)
    lagna_idx = _lagna_index(kundali_data)

    H7, H11 = 7, 11

    # Lords
    lord7 = _house_lord(lagna_idx, H7)
    lord11 = _house_lord(lagna_idx, H11)

    # Info
    l7_sign, l7_house = _planet_info(planets, lord7)
    l11_sign, l11_house = _planet_info(planets, lord11)

    l7_status = _get_status(lord7, l7_sign) if l7_sign else "neutral"
    l11_status = _get_status(lord11, l11_sign) if l11_sign else "neutral"

    in7 = _planets_in_house(planets, H7)
    in11 = _planets_in_house(planets, H11)

    positive, negative = [], []
    score = 0

    # ---- 7th House Evaluation ----
    if l7_status in {"own", "exalted"}:
        score += 2
        positive.append({
            "en": f"7th lord ({lord7}) strong ({l7_status}) partnerships favored.",
            "hi": f"सप्तमेश ({PLANET_HI.get(lord7, lord7)}) {STATUS_HI[l7_status]} पार्टनरशिप से लाभ देगा।"
        })
    elif l7_status == "debilitated" or (l7_house in [6, 8, 12]):
        score -= 1
        negative.append({
            "en": f"7th lord ({lord7}) weak (debilitated or in dusthana) challenges in business alliances.",
            "hi": f"सप्तमेश ({PLANET_HI.get(lord7, lord7)}) नीच/दुष्ट भाव में व्यापारिक संबंधों में कठिनाई दे सकता है।"
        })

    if any(p in BENEFICS for p in in7):
        score += 1
        positive.append({
            "en": "Benefic planet in 7th strengthens partnerships.",
            "hi": "सप्तम भाव में शुभ ग्रह यह संकेत देता है कि आपकी पार्टनरशिप मज़बूत और लाभदायक होगी।"
        })
    if any(p in {"Saturn", "Mars", "Ketu"} for p in in7) and not any(p in BENEFICS for p in in7):
        score -= 1
        negative.append({
            "en": "Malefic influence in 7th house create struggles in partnerships.",
            "hi": "सप्तम भाव में पाप ग्रह स्थित है इसलिए पार्टनरशिप में संघर्ष है।"
        })
    if "Rahu" in in7:
        score += 1
        positive.append({
            "en": "Rahu in 7th gives you innovative marketing and risk-taking approach.",
            "hi": "सप्तम भाव में राहु आपको मार्केटिंग और जोखिम लेने की क्षमता देता है।"
        })

    # ---- 11th House Evaluation ----
    if l11_status in {"own", "exalted"}:
        score += 2
        positive.append({
            "en": f"11th lord ({lord11}) strong ({l11_status}) — gains & networks favorable.",
            "hi": f"11वें भाव का स्‍वामी ({PLANET_HI.get(lord11, lord11)}) {STATUS_HI[l11_status]} — लाभ व नेटवर्क अनुकूल।"
        })
    elif l11_status == "debilitated" or (l11_house in [6, 8, 12]):
        score -= 1
        negative.append({
            "en": f"11th lord ({lord11}) weak (debilitated or in dusthana) — obstacles in profits.",
            "hi": f"11वें भाव का स्‍वामी ({PLANET_HI.get(lord11, lord11)}) अशुभ भाव में है इसलिए लाभ में रुकावट संभव है।"
        })

    if any(p in BENEFICS for p in in11):
        score += 1
        positive.append({
            "en": "Benefic planet in 11th ensures steady profits.",
            "hi": "एकादश भाव में शुभ ग्रह — लाभ सुनिश्चित।"
        })
    if any(p in {"Saturn", "Mars", "Ketu"} for p in in11) and not any(p in BENEFICS for p in in11):
        score -= 1
        negative.append({
            "en": "Malefic influence in 11th — profit delays possible.",
            "hi": "एकादश भाव में पाप ग्रह — लाभ में देरी।"
        })
    if "Rahu" in in11:
        score += 1
        positive.append({
            "en": "Rahu in 11th — scope for expansion and large-scale growth.",
            "hi": "एकादश भाव में राहु — विस्तार और बड़े स्तर पर वृद्धि।"
        })

    # ---- Verdict ----
    if score >= 3:
        verdict, dom = "Highly supportive for business growth", "Business"
    elif score == 2:
        verdict, dom = "Mixed signals — proceed strategically", "Mixed"
    else:
        verdict, dom = "Needs caution & remedies for success", "Job-leaning"

    result = {
        "heading": {"en": "business_path", "hi": "बिज़नेस अनुकूलता"}[lang],
        "verdict": verdict,
        "dominant_influence": dom,
        "positive_points": positive,
        "negative_points": negative,
        "cta": {
            "en": "Want a step-by-step business roadmap? Get your detailed PDF.",
            "hi": "कदम-दर-कदम बिज़नेस रोडमैप चाहिए? अपना विस्तृत PDF लें।"
        }[lang]
    }

    return result
