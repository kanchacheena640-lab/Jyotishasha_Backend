import os
import json
from datetime import datetime
from smart_transit_engine import (
    get_planet_position_on,
    get_next_transits,
    get_prev_transits
)

SATURN_RASHIS = [
    "Capricorn", "Aquarius", "Pisces", "Aries", "Taurus", "Gemini",
    "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius"
]

def load_template(language):
    file_path = f"data/sadhesati_report_{language}.json"
    if not os.path.exists(file_path):
        language = "en"
        file_path = "data/sadhesati_report_en.json"
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)

def generate_sadhesati_report(kundali_data: dict) -> dict:
    moon_sign = kundali_data.get("moon_sign") or kundali_data.get("rashi")
    language = kundali_data.get("language", "en")

    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    current_saturn_pos = get_planet_position_on(today_str, "Saturn")
    saturn_rashi = current_saturn_pos["rashi"]

    try:
        moon_index = SATURN_RASHIS.index(moon_sign)
        saturn_index = SATURN_RASHIS.index(saturn_rashi)
    except:
        return {
            "status": "Error",
            "heading": "Invalid Rashi",
            "explanation": "Moon sign or Saturn sign could not be matched."
        }

    delta = (saturn_index - moon_index) % 12
    phase = None
    status = "Inactive"
    if delta == 11:
        phase = "1st Phase"
        status = "Active"
    elif delta == 0:
        phase = "2nd Phase"
        status = "Active"
    elif delta == 1:
        phase = "3rd Phase"
        status = "Active"

    prev_transits = get_prev_transits("Saturn", 12)
    next_transits = get_next_transits("Saturn", 12)

    rashi_sequence = [
        SATURN_RASHIS[(moon_index - 1) % 12],
        SATURN_RASHIS[moon_index],
        SATURN_RASHIS[(moon_index + 1) % 12]
    ]

    combined = sorted(prev_transits + next_transits, key=lambda x: x["entering_date"])
    phase_dates = {}
    for i, label in enumerate(["first_phase", "second_phase", "third_phase"]):
        for t in combined:
            if t["to_rashi"] == rashi_sequence[i]:
                phase_dates[label] = {
                    "start": t["entering_date"],
                    "end": t["exit_date"]
                }
                break

    impact_level = "Moderate"
    template = load_template(language)

    if status == "Active":
        key = phase.lower().replace(" ", "_")
        start_date = phase_dates[key]["start"]
        end_date = phase_dates[key]["end"]
        short_description = (
            f"You are currently in the {phase} of Sade Sati."
            if language == "en"
            else f"आप वर्तमान में साढ़े साती के {phase} में हैं।"
        )
        paragraph_source = template["report_paragraphs"]
        summary_source = template["summary_block"]
    else:
        phase = None  # ensure not set
        future_phase = next((t for t in next_transits if t["to_rashi"] == rashi_sequence[0]), None)
        if future_phase:
            start_date = future_phase["entering_date"]
            end_date = future_phase["exit_date"]
            short_description = (
                f"Your Sade Sati will begin when Saturn enters {rashi_sequence[0]} on {start_date}."
                if language == "en"
                else f"आपकी साढ़े साती {rashi_sequence[0]} में शनि के प्रवेश के साथ {start_date} से शुरू होगी।"
            )
            phase_dates["first_phase"] = {"start": start_date, "end": end_date}
        else:
            start_date = end_date = ""
            short_description = (
                "You are currently not under Sade Sati."
                if language == "en"
                else "आप वर्तमान में साढ़े साती के प्रभाव में नहीं हैं।"
            )

        paragraph_source = template["inactive_block"]["report_paragraphs"]
        summary_source = template["inactive_block"]["summary_block"]

    placeholder_data = {
        "current_phase": phase or "None",
        "start_date": start_date,
        "end_date": end_date,
        "moon_sign": moon_sign,
        "saturn_sign": saturn_rashi,
        "impact_level": impact_level,
        "future_start_date": start_date,
        "moon_sign_minus_one": rashi_sequence[0],
        "moon_sign_plus_one": rashi_sequence[2],
    }

    def inject(text):
        for key, val in placeholder_data.items():
            text = text.replace(f"{{{key}}}", val)
        return text

    report_paragraphs = [inject(p) for p in paragraph_source]
    summary_points = [inject(p) for p in summary_source["points"]]
    general_explanation = inject(template.get("general_explanation", ""))

    return {
        "status": status,
        "moon_rashi": moon_sign,
        "saturn_rashi": saturn_rashi,
        "phase": phase,
        "phase_dates": phase_dates,
        "short_description": short_description,
        "report_paragraphs": report_paragraphs,
        "summary_block": {
            "heading": summary_source["heading"],
            "points": summary_points
        },
        "explanation": general_explanation
    }
