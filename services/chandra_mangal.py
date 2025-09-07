# services/chandra_mangal.py

import json
import os
from typing import List, Dict


def load_chandra_mangal_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "chandra-mangal-rajyog.json"), encoding="utf-8") as f:
            data = json.load(f)
            return {
                "heading": data["heading"].get(language, data["heading"]["en"]),
                "description": data["description"].get(language, data["description"]["en"]),
                "strength": data["strength"]["value"],
                "positives": data["positives"].get(language, []),
                "challenge": data["challenge"].get(language, ""),
                "upsell": data["upsell"]
            }
    except:
        return {
            "heading": "Chandra-Mangal Yog",
            "description": "Content not found.",
            "strength": "Moderate",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }


def is_aspected_by_mars(mars_house: int, target_house: int) -> bool:
    return any(((mars_house + d - 1) % 12 or 12) == target_house for d in [4, 7, 8])


def is_aspected_by_moon(moon_house: int, target_house: int) -> bool:
    return ((moon_house + 6) % 12 or 12) == target_house


def evaluate_chandra_mangal_from_planets(planets: List[Dict], language: str = "en") -> dict:
    moon = next((p for p in planets if p["name"].lower() == "moon"), None)
    mars = next((p for p in planets if p["name"].lower() == "mars"), None)

    content = load_chandra_mangal_content(language)
    reasons = []

    # ❌ Case: Moon or Mars missing
    if not moon or not mars:
        return {
            "id": "chandra_mangal_yog",
            "name": "Chandra-Mangal Yog",
            "heading": "Chandra-Mangal Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "चंद्र-मंगल योग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "reasons": ["Moon or Mars not found in chart."],
            "description": "This Yog is not present in your chart. Explore other Rajyogs or get the full PDF report for ₹199.",
            "positives": ["❌ This Yog is not active in your chart."],
            "challenge": "❌ No major challenge from this Yog.",
            "upsell": content["upsell"]
        }

    # ✅ Normal evaluation
    moon_house = moon.get("house")
    mars_house = mars.get("house")

    same_house = moon_house == mars_house
    mars_aspects_moon = is_aspected_by_mars(mars_house, moon_house)
    moon_aspects_mars = is_aspected_by_moon(moon_house, mars_house)

    if same_house:
        reasons.append(f"Moon and Mars are in the same house ({moon_house}).")
    if mars_aspects_moon:
        reasons.append(f"Mars aspects Moon from house {mars_house} to {moon_house}.")
    if moon_aspects_mars:
        reasons.append(f"Moon aspects Mars from house {moon_house} to {mars_house}.")
    if not (same_house or mars_aspects_moon or moon_aspects_mars):
        reasons.append("No conjunction or mutual aspect found between Moon and Mars.")

    triggered = same_house or mars_aspects_moon or moon_aspects_mars

    return {
        "id": "chandra_mangal_yog",
        "name": "Chandra-Mangal Yog",
        "heading": content["heading"] if triggered else (
            "Chandra-Mangal Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
            else "चंद्र-मंगल योग आपकी कुंडली में मौजूद नहीं है।"
        ),
        "is_active": triggered,
        "strength": content["strength"] if triggered else "None",
        "reasons": reasons,
        "description": content["description"] if triggered else "This Yog is not present in your chart. Explore other Rajyogs or get the full PDF report for ₹199.",
        "positives": [f"✔️ {p}" for p in content["positives"]] if triggered else ["❌ This Yog is not active in your chart."],
        "challenge": f"⚠️ {content['challenge']}" if triggered else "❌ No major challenge from this Yog.",
        "upsell": content["upsell"]
    }
