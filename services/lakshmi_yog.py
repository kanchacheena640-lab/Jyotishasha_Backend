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

KENDRA_HOUSES = [1, 4, 7, 10]
TRIKONA_HOUSES = [1, 5, 9]


def load_lakshmi_yog_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "lakshmi-yog.json"), encoding="utf-8") as f:
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
            "heading": "Lakshmi Yog",
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


def evaluate_lakshmi_yog(planets: List[Dict], language: str = "en", lagna_sign: str = None) -> dict:
    content = load_lakshmi_yog_content(language)
    reasons = []

    if not lagna_sign:
        return {
            "id": "lakshmi_yog",
            "name": "Lakshmi Yog",
            "heading": "Lakshmi Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "लक्ष्‍मी योग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Lagna sign not provided."],
            "description": "Cannot evaluate Lakshmi Yog without Lagna.",
            "positives": ["❌ Yog evaluation failed."],
            "challenge": "❌ Missing input data.",
            "upsell": content["upsell"]
        }

    house_lords = get_house_lords(planets, lagna_sign)
    lagna_lord_name = house_lords.get(1)
    ninth_lord_name = house_lords.get(9)

    if not lagna_lord_name or not ninth_lord_name:
        return {
            "id": "lakshmi_yog",
            "name": "Lakshmi Yog",
            "heading": "Lakshmi Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "लक्ष्‍मी योग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Ascendant or 9th house lord not found."],
            "description": "Lakshmi Yog not formed due to missing key planets.",
            "positives": ["❌ Yog conditions not fulfilled."],
            "challenge": "❌ Try exploring other Rajyogs in your chart.",
            "upsell": content["upsell"]
        }

    lagna_lord = next(p for p in planets if p["name"] == lagna_lord_name)
    ninth_lord = next(p for p in planets if p["name"] == ninth_lord_name)

    ninth_lord_own_signs = SIGN_LORDS.get(ninth_lord_name, [])
    own_or_exalted = ninth_lord["sign"] in ninth_lord_own_signs
    in_kendra_or_trikona = ninth_lord["house"] in KENDRA_HOUSES + TRIKONA_HOUSES
    lagna_lord_strong = lagna_lord.get("shadbala", 0) >= 70

    if own_or_exalted and in_kendra_or_trikona and lagna_lord_strong:
        reasons.append(f"{ninth_lord_name} (9th lord) is in own/exalted sign and in house {ninth_lord['house']}.")
        reasons.append(f"{lagna_lord_name} (Ascendant lord) is strong with shadbala {lagna_lord.get('shadbala', 0)}.")

        return {
            "id": "lakshmi_yog",
            "name": "Lakshmi Yog",
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

    return {
        "id": "lakshmi_yog",
        "name": "Lakshmi Yog",
        "heading": "Lakshmi Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "लक्ष्‍मी योग आपकी कुंडली में मौजूद नहीं है।",
        "is_active": False,
        "strength": "None",
        "emoji": content["emoji"],
        "reasons": ["Conditions for Lakshmi Yog not fulfilled."],
        "description": "Lakshmi Yog is not active in your chart.",
        "positives": ["❌ Yog not formed due to lack of required planetary placement."],
        "challenge": "❌ No strong wealth trigger from this Yog.",
        "upsell": content["upsell"]
    }
