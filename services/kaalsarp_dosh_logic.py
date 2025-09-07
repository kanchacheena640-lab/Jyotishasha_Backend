import json
import os
from typing import List, Dict


def load_kaalsarp_dosh_content(language: str) -> dict:
    try:
        with open(os.path.join("data", "kaalsarp_dosh_content.json"), encoding="utf-8") as f:
            data = json.load(f)
            return data.get(language, data["en"])
    except:
        return {
            "heading_present": "Kaalsarp Dosh Detected",
            "report_paragraph_present": "Details missing.",
            "general_explanation_present": "Explanation missing.",
            "remedies_present": [],
            "heading_absent": "Kaalsarp Dosh Not Found",
            "report_paragraph_absent": "Details missing.",
            "general_explanation_absent": "Explanation missing.",
            "remedies_absent": [],
            "summary_block": "Kaalsarp Dosh explanation missing."
        }


def generate_kaalsarp_dosh_report(planets: List[Dict], language: str = "en") -> Dict:
    rahu = next((p for p in planets if p["name"].lower() == "rahu"), None)
    ketu = next((p for p in planets if p["name"].lower() == "ketu"), None)

    content = load_kaalsarp_dosh_content(language)

    if not rahu or not ketu:
        return {
            "heading": content.get("heading_absent", "Kaalsarp Dosh Not Found"),
            "report_paragraphs": ["Rahu or Ketu data not found."],
            "summary_block": content.get("summary_block", ""),
            "general_explanation": content.get("general_explanation_absent", ""),
            "remedies": content.get("remedies_absent", [])
        }

    rahu_house = rahu.get("house")
    ketu_house = ketu.get("house")

    blocked_houses = [(h % 12) or 12 for h in range(rahu_house + 1, rahu_house + 12)]
    blocked_houses = blocked_houses[:11]
    blocked_houses_set = set(blocked_houses)

    planets_between = [
        p for p in planets
        if p["name"].lower() not in ["rahu", "ketu"] and p.get("house") in blocked_houses_set
    ]

    planets_outside = [
        p for p in planets
        if p["name"].lower() not in ["rahu", "ketu"] and p.get("house") not in blocked_houses_set
    ]

    triggered = len(planets_outside) == 0

    if triggered:
        heading = content["heading_present"]
        raw_report = content["report_paragraph_present"]
        if isinstance(raw_report, list):
            report = [
                p.replace("{dosh_type}", "Kaalsarp Dosh")
                 .replace("{rahu_house}", str(rahu_house))
                 .replace("{ketu_house}", str(ketu_house))
                 .replace("{planets_between}", str(len(planets_between)))
                for p in raw_report
            ]
        else:
            report = [raw_report
                .replace("{dosh_type}", "Kaalsarp Dosh")
                .replace("{rahu_house}", str(rahu_house))
                .replace("{ketu_house}", str(ketu_house))
                .replace("{planets_between}", str(len(planets_between)))
            ]
        explanation = content["general_explanation_present"]
        remedies = content["remedies_present"]

    else:
        heading = content["heading_absent"]
        raw_report = content["report_paragraph_absent"]
        if isinstance(raw_report, list):
            report = [
                p.replace("{planets_outside}", str(len(planets_outside)))
                 .replace("{rahu_house}", str(rahu_house))
                 .replace("{ketu_house}", str(ketu_house))
                for p in raw_report
            ]
        else:
            report = [raw_report
                .replace("{planets_outside}", str(len(planets_outside)))
                .replace("{rahu_house}", str(rahu_house))
                .replace("{ketu_house}", str(ketu_house))
            ]
        explanation = content["general_explanation_absent"]
        remedies = content["remedies_absent"]

    return {
        "heading": heading,
        "report_paragraphs": report,
        "summary_block": content["summary_block"],
        "general_explanation": explanation,
        "remedies": remedies
    }
