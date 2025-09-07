import json
import os
from typing import List, Dict

SIGN_LORDS = {
    "Sun": ["Leo"],
    "Moon": ["Cancer"],
    "Mars": ["Aries", "Scorpio"],
    "Mercury": ["Gemini", "Virgo"],
    "Jupiter": ["Sagittarius", "Pisces"],
    "Venus": ["Taurus", "Libra"],
    "Saturn": ["Capricorn", "Aquarius"]
}

STRONG_HOUSES = [1, 4, 7, 10]
PLANET_RULES = {
    "Mars": ["Aries", "Scorpio"],
    "Mercury": ["Gemini", "Virgo"],
    "Jupiter": ["Sagittarius", "Pisces"],
    "Venus": ["Taurus", "Libra"],
    "Saturn": ["Capricorn", "Aquarius"]
}

def load_panch_mahapurush_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "panch-mahapurush-rajyog.json"), encoding="utf-8") as f:
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
            "heading": "Panch Mahapurush Rajyog",
            "description": "Content not found.",
            "strength": "Moderate",
            "emoji": "🌟",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }

def evaluate_panch_mahapurush_yog(planets: List[Dict], language: str = "en") -> dict:
    content = load_panch_mahapurush_content(language)
    kendra_houses = [1, 4, 7, 10]
    found = False
    planet_yog_map = {
        "Mars": "Ruchaka Yog",
        "Mercury": "Bhadra Yog",
        "Jupiter": "Hamsa Yog",
        "Venus": "Malavya Yog",
        "Saturn": "Shasha Yog"
    }

    sub_yogs = []
    reasons = []

    for p in planets:
        name = p["name"]
        if name not in planet_yog_map:
            continue
        if p["house"] not in kendra_houses:
            continue
        if p["sign"] in SIGN_LORDS.get(name, []):  # own sign
            sub_yogs.append(planet_yog_map[name])
            reasons.append(f"{name} is in its own sign in {p['house']}th house ⇒ {planet_yog_map[name]}")
            found = True
        elif (name == "Mars" and p["sign"] == "Capricorn") or \
             (name == "Mercury" and p["sign"] == "Virgo") or \
             (name == "Jupiter" and p["sign"] == "Cancer") or \
             (name == "Venus" and p["sign"] == "Pisces") or \
             (name == "Saturn" and p["sign"] == "Libra"):
            sub_yogs.append(planet_yog_map[name])
            reasons.append(f"{name} is exalted in {p['house']}th house ⇒ {planet_yog_map[name]}")
            found = True

    if not sub_yogs:
        return {
            "id": "panch_mahapurush_rajyog",
            "name": "Panch Mahapurush Rajyog",
            "heading": "Panch Mahapurush Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "पंच महापुरुष राजयोग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "sub_yogs": [],
            "reasons": ["No Mahapurush Yog found in your chart."],
            "description": "None of the five Panch Mahapurush Yogas are active.",
            "positives": ["❌ This Yog is not active in your chart."],
            "challenge": "❌ No major challenge from this Yog.",
            "upsell": content["upsell"]
        }

    return {
        "id": "panch_mahapurush_rajyog",
        "name": "Panch Mahapurush Rajyog",
        "heading": content["heading"],
        "is_active": True,
        "strength": content["strength"],
        "emoji": content["emoji"],
        "sub_yogs": sub_yogs,
        "reasons": reasons,
        "description": content["description"],
        "positives": [f"✔️ {p}" for p in content["positives"]],
        "challenge": f"⚠️ {content['challenge']}",
        "upsell": content["upsell"]
    }
