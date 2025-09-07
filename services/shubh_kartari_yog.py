import json
import os
from typing import List, Dict

BENEFICS = {"Jupiter", "Venus", "Mercury", "Moon"}

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

def load_shubh_kartari_content(language: str) -> dict:
    try:
        with open("data/rajyog_content/shubh-kartari-yog.json", encoding="utf-8") as f:
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
            "heading": "Shubh Kartari Yog",
            "description": "Unable to load content.",
            "strength": "Moderate",
            "emoji": "🌿",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }

def evaluate_shubh_kartari_yog(planets: List[Dict], language: str) -> dict:
    content = load_shubh_kartari_content(language)
    reasons = []
    found = False

    # House-based: 1 to 12 map
    house_map = {i: [] for i in range(1, 13)}
    for p in planets:
        house_map[p["house"]].append(p["name"])

    for house in range(1, 13):
        prev_house = 12 if house == 1 else house - 1
        next_house = 1 if house == 12 else house + 1

        if house_map[prev_house] and house_map[next_house]:
            if all(p in BENEFICS for p in house_map[prev_house]) and all(p in BENEFICS for p in house_map[next_house]):
                found = True
                reasons.append(
                    f"House {house} is enclosed by benefics: {', '.join(house_map[prev_house])} in house {prev_house} and {', '.join(house_map[next_house])} in house {next_house}."
                )

    return {
        "id": "shubh_kartari_yog",
        "name": "Shubh Kartari Yog",
        "heading": content["heading"] if found else (
            "Shubh Kartari Yog is NOT present in your Birth Chart (Kundali)."
            if language == "en" else "शुभ कर्तरी योग आपकी कुंडली में मौजूद नहीं है।"
        ),
        "is_active": found,
        "strength": content["strength"] if found else "None",
        "emoji": content["emoji"],
        "reasons": reasons if found else ["No enclosing benefic planets found in 2nd and 12th from any house."],
        "description": content["description"] if found else "This Yog is not currently active.",
        "positives": [f"✔️ {p}" for p in content["positives"]] if found else [],
        "challenge": f"⚠️ {content['challenge']}" if found else "No challenge.",
        "upsell": content["upsell"]
    }
