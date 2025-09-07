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


def load_dhan_yog_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "dhan-yog.json"), encoding="utf-8") as f:
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
            "heading": "Dhan Yog",
            "description": "Content not found.",
            "strength": "Moderate",
            "emoji": "💰",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }


def get_lord_of(planet: str, lagna_sign: str) -> List[int]:
    lagna_index = SIGNS.index(lagna_sign)
    sign_to_house = {SIGNS[(lagna_index + i) % 12]: i + 1 for i in range(12)}

    return [
        sign_to_house[s]
        for s in SIGN_LORDS.get(planet, [])
        if s in sign_to_house
    ]


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


def check_sambandh(p1: Dict, p2: Dict, lagna_sign: str) -> Optional[str]:
    # Conjunction
    if p1["house"] == p2["house"]:
        return "Conjunction"

    # Mutual Aspect
    if check_aspect(p1["house"], p2["house"], p1["name"]) and check_aspect(p2["house"], p1["house"], p2["name"]):
        return "Mutual Aspect"

    # Parivartan
    if p1["house"] in get_lord_of(p2["name"], lagna_sign) and p2["house"] in get_lord_of(p1["name"], lagna_sign):
        return "Parivartan (Exchange)"

    return None


def evaluate_dhan_yog_from_planets(planets: List[Dict], language: str = "en", lagna_sign: str = None) -> dict:
    content = load_dhan_yog_content(language)
    reasons = []

    if not lagna_sign:
        return {
            "id": "dhan_yog",
            "name": "Dhan Yog",
            "heading": "Dharma-Karmadhipati Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "धर्म-कर्माधिपति राजयोग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Lagna sign not provided."],
            "description": "Cannot evaluate Dhan Yog without Lagna.",
            "positives": ["❌ This Yog cannot be evaluated."],
            "challenge": "❌ Missing required info.",
            "upsell": content["upsell"]
        }

    dhan_houses = [2, 5, 9, 11]
    house_lords = get_house_lords(planets, lagna_sign)
    dhan_lords = {h: house_lords[h] for h in dhan_houses if h in house_lords}

    sambandh_found = []
    checked_pairs = set()

    for h1, p1 in dhan_lords.items():
        for h2, p2 in dhan_lords.items():
            if h1 >= h2 or (p1, p2) in checked_pairs or p1 == p2:
                continue
            checked_pairs.add((p1, p2))
            planet1 = next(p for p in planets if p["name"] == p1)
            planet2 = next(p for p in planets if p["name"] == p2)
            relation = check_sambandh(planet1, planet2, lagna_sign)
            if relation:
                sambandh_found.append((p1, p2, relation))
                reasons.append(f"{p1} and {p2} have {relation} between dhan houses {h1} and {h2}.")

    if not sambandh_found:
        return {
            "id": "dhan_yog",
            "name": "Dhan Yog",
            "heading": "Dharma-Karmadhipati Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "धर्म-कर्माधिपति राजयोग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["No sambandh (conjunction/aspect/exchange) found between dhan lords."],
            "description": "Dhan Yog not found based on planetary connections.",
            "positives": ["❌ This Yog is not active in your chart."],
            "challenge": "❌ No major challenge from this Yog.",
            "upsell": content["upsell"]
        }

    # Evaluate strength
    shadbalas = []
    for (p1, p2, _) in sambandh_found:
        s1 = next(p for p in planets if p["name"] == p1).get("shadbala", 0)
        s2 = next(p for p in planets if p["name"] == p2).get("shadbala", 0)
        shadbalas.extend([s1, s2])

    avg_sb = sum(shadbalas) / len(shadbalas)
    if avg_sb >= 100:
        strength = "High"
    elif avg_sb >= 70:
        strength = "Moderate"
    else:
        strength = "Low"

    return {
        "id": "dhan_yog",
        "name": "Dhan Yog",
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
