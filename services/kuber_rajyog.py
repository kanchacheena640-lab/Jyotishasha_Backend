import json
import os
from typing import List, Dict


def load_kuber_rajyog_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "kuber-rajyog.json"), encoding="utf-8") as f:
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
            "heading": "Kuber Rajyog",
            "description": "Content not found.",
            "strength": "Moderate",
            "emoji": "💰",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }


def evaluate_kuber_rajyog_from_planets(planets: List[Dict], language: str = "en") -> dict:
    wealth_planets = ["Jupiter", "Venus", "Mercury", "Moon"]
    wealth_houses = [2, 5, 9, 11]

    content = load_kuber_rajyog_content(language)
    found = []
    reasons = []

    for p in planets:
        if p["name"] in wealth_planets and p["house"] in wealth_houses:
            if p.get("shadbala", 0) >= 70:
                found.append(p)
                reasons.append(f"{p['name']} is strongly placed in {p['house']}th house.")

    if not found:
        return {
            "id": "kuber_rajyog",
            "name": "Kuber Rajyog",
            "heading": "Kuber Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "कुबेर योग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "emoji": content["emoji"],
            "reasons": ["No strong wealth planets found in finance-related houses."],
            "description": "Kuber Rajyog not active in your Kundali.",
            "positives": ["❌ This Yog is not active in your chart."],
            "challenge": "❌ No major challenge from this Yog.",
            "upsell": content["upsell"]
        }

    avg_sb = sum(p.get("shadbala", 0) for p in found) / len(found)
    if avg_sb >= 100:
        strength = "High"
    elif avg_sb >= 80:
        strength = "Moderate"
    else:
        strength = "Low"

    return {
        "id": "kuber_rajyog",
        "name": "Kuber Rajyog",
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
