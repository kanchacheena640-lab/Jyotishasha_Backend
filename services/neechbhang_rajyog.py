import json
import os
from typing import List, Dict

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

EXALTATIONS = {
    "Sun": "Aries",
    "Moon": "Taurus",
    "Mars": "Capricorn",
    "Mercury": "Virgo",
    "Jupiter": "Cancer",
    "Venus": "Pisces",
    "Saturn": "Libra"
}

DEBILITATIONS = {
    "Sun": "Libra",
    "Moon": "Scorpio",
    "Mars": "Cancer",
    "Mercury": "Pisces",
    "Jupiter": "Capricorn",
    "Venus": "Virgo",
    "Saturn": "Aries"
}

ASPECT_RULES = {
    "Saturn": [3, 7, 10],
    "Mars": [4, 7, 8],
    "Jupiter": [5, 7, 9],
    "Rahu": [5, 7, 9],
    "Ketu": [5, 7, 9]
}

def load_neechbhang_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "neechbhang-rajyog.json"), encoding="utf-8") as f:
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
            "heading": "Neechbhang Rajyog",
            "description": "Unable to load content.",
            "strength": "Moderate",
            "emoji": "🌟",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }

def get_lord_of_sign(sign: str) -> str:
    for planet, signs in SIGN_LORDS.items():
        if sign in signs:
            return planet
    return ""

def check_aspect(from_house: int, to_house: int, planet: str) -> bool:
    for drishti in ASPECT_RULES.get(planet, [7]):
        if ((from_house + drishti - 1) % 12 or 12) == to_house:
            return True
    return False

def evaluate_neechbhang(planets: List[Dict], language: str = "en") -> dict:
    content = load_neechbhang_content(language)
    reasons = []
    found = []

    for p in planets:
        name = p["name"]
        sign = p["sign"]
        house = p["house"]

        if name not in DEBILITATIONS:
            continue

        if DEBILITATIONS[name] != sign:
            continue  # Not debilitated

        # ✅ Rule 1: Debilitated in Kendra
        if house in [1, 4, 7, 10]:
            reasons.append(f"{name} is debilitated in Kendra (house {house}).")
            found.append(name)

        # ✅ Rule 2: Aspected by own or exaltation lord from Kendra
        lord = get_lord_of_sign(sign)
        exaltation_sign = EXALTATIONS.get(name)
        exalted_lord = get_lord_of_sign(exaltation_sign) if exaltation_sign else None

        for other in planets:
            if other["name"] not in [lord, exalted_lord]:
                continue
            if check_aspect(other["house"], p["house"], other["name"]) and other["house"] in [1, 4, 7, 10]:
                reasons.append(f"{name} is aspected by {other['name']} from Kendra.")
                found.append(name)

        # ✅ Rule 3: Conjunct with exalted planet
        for other in planets:
            if other["sign"] == sign and other["name"] == exalted_lord:
                reasons.append(f"{name} is conjunct with exalted planet {other['name']} in same sign.")
                found.append(name)

        # ✅ Rule 4: Parivartan between debilitated planet and sign lord
        lord_planet = next((pl for pl in planets if pl["name"] == lord), None)
        if lord_planet and lord_planet["sign"] in SIGN_LORDS.get(name, []):
            reasons.append(f"{name} and its sign lord {lord} are in Parivartan Yog (sign exchange).")
            found.append(name)

    if not reasons:
        return {
            "id": "neechbhang_rajyog",
            "name": "Neechbhang Rajyog",
            "heading": content["heading"] if found else (
                "Neechbhang Rajyog is NOT present in your Birth Chart (Kundali)."
                if language == "en" else "नीचभंग राजयोग आपकी कुंडली में मौजूद नहीं है।"
            ),
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["No valid Neechbhang conditions detected."],
            "description": "This Rajyog is not active in your chart.",
            "positives": ["❌ No active Neechbhang Yoga found."],
            "challenge": "❌ No major challenge from this Yog.",
            "upsell": content["upsell"]
        }

    return {
        "id": "neechbhang_rajyog",
        "name": "Neechbhang Rajyog",
        "heading": content["heading"],
        "is_active": True,
        "strength": content["strength"],
        "emoji": content["emoji"],
        "reasons": reasons,
        "description": content["description"],
        "positives": [f"✔️ {p}" for p in content["positives"]],
        "challenge": f"⚠️ {content['challenge']}",
        "upsell": content["upsell"]
    }
