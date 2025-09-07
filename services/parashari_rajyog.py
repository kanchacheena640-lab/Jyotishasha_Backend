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

def load_parashari_content(language: str) -> dict:
    try:
        with open("data/rajyog_content/parashari-rajyog.json", encoding="utf-8") as f:
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
            "heading": "Parashari Rajyog",
            "description": "Unable to load content.",
            "strength": "Moderate",
            "emoji": "🔱",
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

def check_sambandh(p1: Dict, p2: Dict, lagna_sign: str) -> Optional[str]:
    if p1["house"] == p2["house"]:
        return "Conjunction"
    if check_aspect(p1["house"], p2["house"], p1["name"]) and check_aspect(p2["house"], p1["house"], p2["name"]):
        return "Mutual Aspect"
    if p1["house"] in get_lord_of(p2["name"], lagna_sign) and p2["house"] in get_lord_of(p1["name"], lagna_sign):
        return "Parivartan"
    return None

def evaluate_parashari_rajyog(planets: List[Dict], language: str, lagna_sign: str) -> dict:
    content = load_parashari_content(language)
    reasons = []

    kendra = [1, 4, 7, 10]
    trikona = [1, 5, 9]
    house_lords = get_house_lords(planets, lagna_sign)

    found = False
    for h1 in kendra:
        for h2 in trikona:
            if h1 == h2: continue
            p1 = house_lords.get(h1)
            p2 = house_lords.get(h2)
            if not p1 or not p2 or p1 == p2:
                continue
            planet1 = next(p for p in planets if p["name"] == p1)
            planet2 = next(p for p in planets if p["name"] == p2)
            relation = check_sambandh(planet1, planet2, lagna_sign)
            if relation:
                found = True
                reasons.append(f"{p1} and {p2} have {relation} between Kendra ({h1}) and Trikona ({h2}).")

    return {
        "id": "parashari_rajyog",
        "name": "Parashari Rajyog",
        "heading": content["heading"] if found else (
                "Parashari RajYog is NOT present in your Birth Chart (Kundali)."
                if language == "en" else "पराशरी राजयोग आपकी कुंडली में मौजूद नहीं है।"
            ),
        "is_active": found,
        "strength": content["strength"] if found else "None",
        "emoji": content["emoji"],
        "reasons": reasons if found else ["No sambandh found between Kendra and Trikona lords."],
        "description": content["description"] if found else "This Rajyog is not currently active.",
        "positives": [f"✔️ {p}" for p in content["positives"]] if found else [],
        "challenge": f"⚠️ {content['challenge']}" if found else "No challenge.",
        "upsell": content["upsell"]
    }
