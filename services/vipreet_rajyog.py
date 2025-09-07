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

def load_vipreet_content(language: str) -> dict:
    try:
        with open("data/rajyog_content/vipreet-rajyog.json", encoding="utf-8") as f:
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
            "heading": "Vipreet Rajyog",
            "description": "Unable to load content.",
            "strength": "Moderate",
            "emoji": "⚡",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }

def get_house_sign_map(lagna_sign: str) -> Dict[int, str]:
    lagna_index = SIGNS.index(lagna_sign)
    return {i + 1: SIGNS[(lagna_index + i) % 12] for i in range(12)}

def get_lord(sign: str) -> str:
    for lord, signs in SIGN_LORDS.items():
        if sign in signs:
            return lord
    return ""

def evaluate_vipreet_rajyog(planets: List[Dict], lagna_sign: str, language: str) -> dict:
    content = load_vipreet_content(language)
    vipreet_houses = {6, 8, 12}
    house_sign_map = get_house_sign_map(lagna_sign)

    # Step 1: Find lords of 6th, 8th, 12th houses
    house_lords = {}
    for h in vipreet_houses:
        sign = house_sign_map[h]
        lord = get_lord(sign)
        if lord:
            planet = next((p for p in planets if p["name"] == lord), None)
            if planet:
                house_lords[h] = planet

    if len(house_lords) < 2:
        return {
            "id": "vipreet_rajyog",
            "name": "Vipreet Rajyog",
            "heading": content["heading"] if found else (
                "Vipreet Raj Yog is NOT present in your Birth Chart (Kundali)."
                if language == "en" else "विपरीत राज योग आपकी कुंडली में मौजूद नहीं है।"
            ),
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["Could not find enough lords for 6th, 8th, or 12th houses."],
            "description": "This Yog is not currently active.",
            "positives": [],
            "challenge": "No challenge.",
            "upsell": content["upsell"]
        }

    # Step 2: Check if 2 or more are placed in 6/8/12
    reasons = []
    count_direct = 0
    placements = {}

    for h, p in house_lords.items():
        placements[p["name"]] = p["house"]
        if p["house"] in vipreet_houses:
            count_direct += 1
            reasons.append(f"{p['name']} (lord of house {h}) is placed in house {p['house']}.")

    # Step 3: If not direct, check for sambandh: same house or mutual exchange
    sambandh_count = 0
    names = list(house_lords.values())

    if count_direct < 2:
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                p1 = names[i]
                p2 = names[j]
                # Conjunction
                if p1["house"] == p2["house"]:
                    sambandh_count += 1
                    reasons.append(f"{p1['name']} and {p2['name']} are conjunct in house {p1['house']}.")
                # Parivartan
                elif p1["house"] in house_lords and house_lords[p1["house"]]["name"] == p2["name"]:
                    sambandh_count += 1
                    reasons.append(f"{p1['name']} and {p2['name']} are in Parivartan Yoga.")

    found = count_direct >= 2 or sambandh_count >= 1

    return {
        "id": "vipreet_rajyog",
        "name": "Vipreet Rajyog",
        "heading": content["heading"],
        "is_active": found,
        "strength": content["strength"] if found else "None",
        "emoji": content["emoji"],
        "reasons": reasons if found else ["No valid sambandh or placement found among 6/8/12 house lords."],
        "description": content["description"] if found else "This Yog is not currently active.",
        "positives": [f"✔️ {p}" for p in content["positives"]] if found else [],
        "challenge": f"⚠️ {content['challenge']}" if found else "No challenge.",
        "upsell": content["upsell"]
    }
