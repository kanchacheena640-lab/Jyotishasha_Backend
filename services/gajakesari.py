import json
import os
from typing import List, Dict, Optional

KENDRA_HOUSES = [1, 4, 7, 10]

ASPECT_RULES = {
    "Jupiter": [5, 7, 9],
    "Moon": [7]
}


def load_gajakesari_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "gajakesari.json"), encoding="utf-8") as f:
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
            "heading": "Gajakesari Yog",
            "description": "Content not found.",
            "strength": "Moderate",
            "emoji": "🔥",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }


def check_aspect(from_house: int, to_house: int, planet: str) -> bool:
    for aspect in ASPECT_RULES.get(planet, []):
        if ((from_house + aspect - 1) % 12 or 12) == to_house:
            return True
    return False


def evaluate_gajakesari(planets: List[Dict], language: str = "en") -> dict:
    content = load_gajakesari_content(language)
    reasons = []

    moon = next((p for p in planets if p["name"].lower() == "moon"), None)
    jupiter = next((p for p in planets if p["name"].lower() == "jupiter"), None)

    if not moon or not jupiter:
        return {
            "id": "gajakesari_yog",
            "name": "Gajakesari Yog",
            "heading": "Gajakesari Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "गजकेसरी योग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Conditions for Gajakesari Yog not met."],
            "description": "This Yog is not present in your chart.",
            "positives": ["❌ This Yog is not active."],
            "challenge": "❌ No challenge from this Yog.",
            "upsell": content["upsell"]
        }

    same_house = moon["house"] == jupiter["house"]
    aspecting_each_other = check_aspect(moon["house"], jupiter["house"], "Moon") and check_aspect(jupiter["house"], moon["house"], "Jupiter")
    in_kendra = moon["house"] in KENDRA_HOUSES or jupiter["house"] in KENDRA_HOUSES

    if same_house:
        reasons.append(f"Moon and Jupiter are in conjunction in house {moon['house']}.")
    if aspecting_each_other:
        reasons.append(f"Moon and Jupiter are aspecting each other (mutual drishti).")
    if in_kendra:
        reasons.append(f"Moon or Jupiter is in a Kendra house ({moon['house']} or {jupiter['house']}).")

    is_active = (same_house or aspecting_each_other) and in_kendra

    if not is_active:
        return {
            "id": "gajakesari_yog",
            "name": "Gajakesari Yog",
            "heading": "Gajakesari Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "गजकेसरी योग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Conditions for Gajakesari Yog not met."],
            "description": "This Yog is not active in your chart.",
            "positives": ["❌ This Yog is not active."],
            "challenge": "❌ No challenge from this Yog.",
            "upsell": content["upsell"]
        }

    # Shadbala strength logic
    s1 = moon.get("shadbala", 0)
    s2 = jupiter.get("shadbala", 0)
    avg = (s1 + s2) / 2
    if avg >= 100:
        strength = "High"
    elif avg >= 70:
        strength = "Moderate"
    else:
        strength = "Low"

    return {
        "id": "gajakesari_yog",
        "name": content["heading"],
        "is_active": True,
        "strength": strength,
        "emoji": content["emoji"],
        "reasons": reasons,
        "description": content["description"],
        "positives": [f"✔️ {p}" for p in content["positives"]],
        "challenge": f"⚠️ {content['challenge']}",
        "upsell": content["upsell"]
    }
