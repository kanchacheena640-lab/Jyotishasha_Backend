import json
import os
from typing import List, Dict, Optional

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

SIGN_LORDS = {
    "Sun": ["Leo"],
    "Moon": ["Cancer"],
    "Mars": ["Aries", "Scorpio"],
    "Mercury": ["Gemini", "Virgo"],
    "Jupiter": ["Sagittarius", "Pisces"],
    "Venus": ["Taurus", "Libra"],
    "Saturn": ["Capricorn", "Aquarius"]
}

ASPECT_RULES = {
    "Saturn": [3, 7, 10],
    "Mars": [4, 7, 8],
    "Jupiter": [5, 7, 9],
    "Rahu": [5, 7, 9],
    "Ketu": [5, 7, 9]
}


def load_dharma_karmadhipati_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "dharma-karmadhipati-rajyog.json"), encoding="utf-8") as f:
            data = json.load(f)
            return {
                "heading": data["heading"].get(language, data["heading"]["en"]),
                "description": data["description"].get(language, data["description"]["en"]),
                "strength": data["strength"]["value"],
                "emoji": data["strength"].get("emoji", ""),
                "positives": data["positives"].get(language, []),
                "challenge": data["challenge"].get(language, ""),
                "upsell": data["upsell"]
            }
    except:
        return {
            "heading": "Dharma-Karmadhipati Rajyog",
            "description": "Content not found.",
            "strength": "Moderate",
            "emoji": "🪔",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }


def get_lord_of(planet: str, lagna_sign: str) -> List[int]:
    lagna_index = SIGNS.index(lagna_sign)
    sign_to_house = {SIGNS[(lagna_index + i) % 12]: i + 1 for i in range(12)}
    return [sign_to_house[s] for s in SIGN_LORDS.get(planet, []) if s in sign_to_house]


def get_house_lords(planets: List[Dict], lagna_sign: str) -> Dict[int, str]:
    house_lords = {}
    for p in planets:
        for house in get_lord_of(p["name"], lagna_sign):
            house_lords[house] = p["name"]
    return house_lords


def check_aspect(from_house: int, to_house: int, planet: str) -> bool:
    for aspect in ASPECT_RULES.get(planet, [7]):
        if ((from_house + aspect - 1) % 12 or 12) == to_house:
            return True
    return False


def check_connection(p1: Dict, p2: Dict, lagna_sign: str) -> Optional[str]:
    if p1["house"] == p2["house"]:
        return "Conjunction"
    if check_aspect(p1["house"], p2["house"], p1["name"]) and check_aspect(p2["house"], p1["house"], p2["name"]):
        return "Mutual Aspect"
    if p1["house"] in get_lord_of(p2["name"], lagna_sign) and p2["house"] in get_lord_of(p1["name"], lagna_sign):
        return "Parivartan (Exchange)"
    return None


def evaluate_dharma_karmadhipati(planets: List[Dict], language: str = "en", lagna_sign: str = None) -> dict:
    content = load_dharma_karmadhipati_content(language)
    reasons = []

    if not lagna_sign:
        return {
            "id": "dharma_karmadhipati_rajyog",
            "name": "Dharma-Karmadhipati Rajyog",
            "heading": "Dharma-Karmadhipati Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "धर्म-कर्माधिपति राजयोग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Lagna sign not provided."],
            "description": "Cannot evaluate without Lagna.",
            "positives": ["❌ Yog evaluation skipped."],
            "challenge": "❌ Missing info.",
            "upsell": content["upsell"]
        }

    house_lords = get_house_lords(planets, lagna_sign)
    p9 = house_lords.get(9)
    p10 = house_lords.get(10)

    if not p9 or not p10 or p9 == p10:
        return {
            "id": "dharma_karmadhipati_rajyog",
            "name": "Dharma-Karmadhipati Rajyog",
            "heading": "Dharma-Karmadhipati Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "धर्म-कर्माधिपति राजयोग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["9th or 10th house lord missing or same planet."],
            "description": "This Yog is not formed in your chart.",
            "positives": ["❌ Yog not active."],
            "challenge": "❌ No challenge from this Yog.",
            "upsell": content["upsell"]
        }

    planet1 = next(p for p in planets if p["name"] == p9)
    planet2 = next(p for p in planets if p["name"] == p10)
    relation = check_connection(planet1, planet2, lagna_sign)

    if not relation:
        return {
            "id": "dharma_karmadhipati_rajyog",
            "name": "Dharma-Karmadhipati Rajyog",
            "heading": "Dharma-Karmadhipati Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "धर्म-कर्माधिपति राजयोग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["No sambandh found between 9th and 10th lords."],
            "description": "Yog not active in your chart.",
            "positives": ["❌ This Yog is not active."],
            "challenge": "❌ No challenge from this Yog.",
            "upsell": content["upsell"]
        }

    # Evaluate strength by shadbala
    sb1 = planet1.get("shadbala", 0)
    sb2 = planet2.get("shadbala", 0)
    avg = (sb1 + sb2) / 2
    if avg >= 100:
        strength = "High"
    elif avg >= 70:
        strength = "Moderate"
    else:
        strength = "Low"

    reasons.append(f"{p9} and {p10} have {relation} between 9th and 10th houses.")

    return {
        "id": "dharma_karmadhipati_rajyog",
        "name": "Dharma-Karmadhipati Rajyog",
        "heading": content["heading"],
        "is_active": True,
        "strength": strength,
        "emoji": content["emoji"],
        "reasons": reasons,
        "description": content["description"],
        "positives": [f"✔️ {p}" for p in content["positives"]],
        "challenge": f"⚠️ {content['challenge']}",
        "upsell": content["upsell"]
    }
