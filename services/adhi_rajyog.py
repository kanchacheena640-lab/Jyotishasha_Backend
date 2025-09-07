import json
import os
from typing import List, Dict


def load_adhi_rajyog_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "adhi-rajyog.json"), encoding="utf-8") as f:
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
            "heading": "Adhi Rajyog",
            "description": "Content not found.",
            "strength": "Moderate",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }


def get_offset_from_moon(moon_house: int, planet_house: int) -> int:
    return ((planet_house - moon_house + 12) % 12) + 1


def ordinal(n: int) -> str:
    return f"{n}{'th' if 11<=n%100<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10, 'th')}"


def evaluate_adhi_rajyog_from_planets(planets: List[Dict], language: str = "en") -> dict:
    content = load_adhi_rajyog_content(language)
    reasons = []

    moon = next((p for p in planets if p["name"].lower() == "moon"), None)
    if not moon:
        return {
            "id": "adhi_rajyog",
            "name": "Adhi Rajyog",
            "heading": "Adhi Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "आधि राजयोग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "reasons": ["Moon not found in chart."],
            "description": "This Yog is not present in your chart. Explore other Rajyogs or get the full PDF report for ₹199.",
            "positives": ["❌ This Yog is not active in your chart."],
            "challenge": "❌ No major challenge from this Yog.",
            "upsell": content["upsell"]
        }

    moon_house = moon.get("house")
    target_houses = [((moon_house + offset - 1) % 12) or 12 for offset in [6, 7, 8]]
    benefics = {"jupiter", "venus", "mercury"}

    matching_planets = [
        p for p in planets
        if p["name"].lower() in benefics and p.get("house") in target_houses
    ]

    for p in matching_planets:
        offset = get_offset_from_moon(moon_house, p["house"])
        reasons.append(
            f"{p['name'].title()} is placed in house {p['house']}, which is the {ordinal(offset)} house from Moon."
        )

    triggered = len(matching_planets) > 0

    if not triggered:
        reasons.append("No benefic planet (Jupiter, Venus, Mercury) found in 6th, 7th, or 8th house from Moon.")

    return {
        "id": "adhi_rajyog",
        "name": "Adhi Rajyog",
        "heading": content["heading"] if triggered else (
            "Adhi Rajyog is NOT present in your Birth Chart (Kundali)." if language == "en"
            else "आधि राजयोग आपकी कुंडली में मौजूद नहीं है।"
        ),
        "is_active": triggered,
        "strength": content["strength"] if triggered else "None",
        "reasons": reasons,
        "description": content["description"] if triggered else "This Yog is not present in your chart. Explore other Rajyogs or get the full PDF report for ₹199.",
        "positives": [f"✔️ {p}" for p in content["positives"]] if triggered else ["❌ This Yog is not active in your chart."],
        "challenge": f"⚠️ {content['challenge']}" if triggered else "❌ No major challenge from this Yog.",
        "upsell": content["upsell"]
    }
 