import json
import os
from typing import List, Dict, Optional

ASPECT_RULES = {
    "Saturn": [3, 7, 10],
    "Mars": [4, 7, 8],
    "Jupiter": [5, 7, 9],
    "Rahu": [5, 7, 9],
    "Ketu": [5, 7, 9]
}

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

def load_rajya_sambandh_content(language: str) -> dict:
    try:
        with open("data/rajyog_content/rajya-sambandh-rajyog.json", encoding="utf-8") as f:
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
            "heading": "Rajya Sambandh Rajyog",
            "description": "Unable to load content.",
            "strength": "Moderate",
            "emoji": "🏛️",
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

def check_sambandh(p1: Dict, p2: Dict) -> Optional[str]:
    if p1["house"] == p2["house"]:
        return "Conjunction"
    if check_aspect(p1["house"], p2["house"], p1["name"]) or check_aspect(p2["house"], p1["house"], p2["name"]):
        return "Aspect"
    return None

def evaluate_rajya_sambandh_rajyog(planets: List[Dict], language: str, lagna_sign: str) -> dict:
    content = load_rajya_sambandh_content(language)
    reasons = []

    key_houses = [4, 5, 9, 10]
    house_lords = get_house_lords(planets, lagna_sign)
    lagna_lord = house_lords.get(1)
    tenth_lord = house_lords.get(10)

    if not lagna_lord or not tenth_lord:
        return {
            "id": "rajya_sambandh_rajyog",
            "name": "Rajya Sambandh Rajyog",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Missing Lagna or 10th house lord."],
            "description": "This Rajyog is not currently active.",
            "positives": [],
            "challenge": "No challenge.",
            "upsell": content["upsell"]
        }

    lagna_planet = next(p for p in planets if p["name"] == lagna_lord)
    tenth_planet = next(p for p in planets if p["name"] == tenth_lord)

    found = False
    for h in key_houses:
        if h in [1, 10]:
            continue
        yog_lord_name = house_lords.get(h)
        if not yog_lord_name:
            continue
        yog_planet = next((p for p in planets if p["name"] == yog_lord_name), None)
        if not yog_planet:
            continue

        # Check sambandh with Lagna Lord or 10th Lord
        if check_sambandh(yog_planet, lagna_planet) or check_sambandh(yog_planet, tenth_planet):
            found = True
            relation_with = lagna_lord if check_sambandh(yog_planet, lagna_planet) else tenth_lord
            reasons.append(f"{yog_lord_name} is connected with {relation_with} via aspect or conjunction.")

    return {
        "id": "rajya_sambandh_rajyog",
        "name": "Rajya Sambandh Rajyog",
        "heading": content["heading"] if found else (
                "Rajya Sambandh Yog is NOT present in your Birth Chart (Kundali)."
                if language == "en" else "राज्‍य संबंध योग आपकी कुंडली में मौजूद नहीं है।"
            ),
        "is_active": found,
        "strength": content["strength"] if found else "None",
        "emoji": content["emoji"],
        "reasons": reasons if found else ["No sambandh found with Lagna or 10th lord."],
        "description": content["description"] if found else "This Rajyog is not currently active.",
        "positives": [f"✔️ {p}" for p in content["positives"]] if found else [],
        "challenge": f"⚠️ {content['challenge']}" if found else "No challenge.",
        "upsell": content["upsell"]
    }
