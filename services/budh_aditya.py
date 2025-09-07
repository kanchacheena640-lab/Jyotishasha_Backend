# services/budh_aditya.py

import json
import os
from typing import List, Dict


def load_budh_aditya_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "rajyog_content", "budh-aditya-yog.json"), encoding="utf-8") as f:
            data = json.load(f)
            return {
                "heading": data["heading"].get(language, data["heading"]["en"]),
                "description": data["description"].get(language, data["description"]["en"]),
                "strength": data["strength"]["value"],
                "positives": data["positives"].get(language, []),
                "challenge": data["challenge"].get(language, ""),
                "upsell": data["upsell"]
            }
    except Exception:
        return {
            "heading": "Budh-Aditya Yog",
            "description": "Content not found.",
            "strength": "Moderate",
            "positives": [],
            "challenge": "",
            "upsell": {}
        }


def evaluate_budh_aditya_from_planets(planets: List[Dict], language: str = "en") -> dict:
    sun = next((p for p in planets if p["name"].lower() == "sun"), None)
    mercury = next((p for p in planets if p["name"].lower() == "mercury"), None)

    content = load_budh_aditya_content(language)
    reasons: List[str] = []

    # ❌ Case: Sun or Mercury missing
    if not sun or not mercury:
        return {
            "id": "budh_aditya_yog",
            "name": "Budh-Aditya Yog",
            "heading": "Budh-Aditya Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
                       else "बुध-आदित्य योग आपकी कुंडली में मौजूद नहीं है।",
            "is_active": False,
            "strength": "None",
            "reasons": ["Sun or Mercury not found in chart."],
            "description": "This Yog is not present in your chart. Explore other Rajyogs or get the full PDF report for ₹199.",
            "positives": ["❌ This Yog is not active in your chart."],
            "challenge": "❌ No major challenge from this Yog.",
            "upsell": content["upsell"]
        }

    # ✅ Evaluation logic
    sun_house = sun.get("house")
    merc_house = mercury.get("house")

    same_house = sun_house == merc_house
    degree_gap = abs(sun.get("degree", 0.0) - mercury.get("degree", 0.0))
    close_conjunction = degree_gap <= 14.0  # common rule-of-thumb window

    if same_house:
        reasons.append(f"Sun and Mercury are in the same house ({sun_house}).")
    else:
        reasons.append("Sun and Mercury are not in the same house.")

    if close_conjunction:
        reasons.append(f"Sun and Mercury are within {degree_gap:.1f}° of each other.")
    elif same_house:
        reasons.append("Sun and Mercury are in the same house but more than 14° apart.")

    triggered = same_house and close_conjunction

    return {
        "id": "budh_aditya_yog",
        "name": "Budh-Aditya Yog",
        "heading": content["heading"] if triggered else (
            "Budh-Aditya Yog is NOT present in your Birth Chart (Kundali)." if language == "en"
            else "बुध-आदित्य योग आपकी कुंडली में मौजूद नहीं है।"
        ),
        "is_active": triggered,
        "strength": content["strength"] if triggered else "None",
        "reasons": reasons,
        "description": content["description"] if triggered else "This Yog is not present in your chart. Explore other Rajyogs or get the full PDF report for ₹199.",
        "positives": [f"✔️ {p}" for p in content["positives"]] if triggered else ["❌ This Yog is not active in your chart."],
        "challenge": f"⚠️ {content['challenge']}" if triggered else "❌ No major challenge from this Yog.",
        "upsell": content["upsell"]
    }
