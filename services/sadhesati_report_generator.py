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

    # collect transit data
    prev_transits = get_prev_transits("Saturn", 12)
    next_transits = get_next_transits("Saturn", 12)
    combined = sorted(prev_transits + next_transits, key=lambda x: x["entering_date"])

    # --- Build Phase Blocks (multiple entries allowed) ---
    phase_dates = {"first_phase": [], "second_phase": [], "third_phase": []}
    rashi_sequence = [
        SATURN_RASHIS[(moon_index - 1) % 12],  # 1st Phase
        SATURN_RASHIS[moon_index],             # 2nd Phase
        SATURN_RASHIS[(moon_index + 1) % 12]   # 3rd Phase
    ]

    for idx, label in enumerate(["first_phase", "second_phase", "third_phase"]):
        entries = [t for t in combined if t["to_rashi"] == rashi_sequence[idx]]
        for e in entries:
            phase_dates[label].append({
                "start": e["entering_date"],
                "end": e["exit_date"]
            })

    # --- Total Sade Sati Period ---
    start_date = phase_dates["first_phase"][0]["start"] if phase_dates["first_phase"] else ""
    end_date = phase_dates["third_phase"][-1]["end"] if phase_dates["third_phase"] else ""

    # --- Status Detection ---
    today = datetime.now().date()
    status = "Inactive"
    active_phase = None

    def in_range(d1, d2):
        return datetime.strptime(d1, "%Y-%m-%d").date() <= today <= datetime.strptime(d2, "%Y-%m-%d").date()

    for label in ["first_phase", "second_phase", "third_phase"]:
        for block in phase_dates[label]:
            if block["start"] and block["end"] and in_range(block["start"], block["end"]):
                status = "Active"
                active_phase = label
                break
        if status == "Active":
            break

    if status == "Inactive":
        if start_date and today < datetime.strptime(start_date, "%Y-%m-%d").date():
            status = "Upcoming"
        elif end_date and today > datetime.strptime(end_date, "%Y-%m-%d").date():
            status = "Ended"

    # --- Template Load ---
    template = load_template(language)
    if status == "Active":
        short_description = (
            f"You are currently in the {active_phase.replace('_', ' ')} of Sade Sati."
            if language == "en"
            else f"आप वर्तमान में साढ़े साती के {active_phase.replace('_', ' ')} में हैं।"
        )
        paragraph_source = template["report_paragraphs"]
        summary_source = template["summary_block"]
    elif status == "Upcoming":
        short_description = (
            f"Your Sade Sati will begin from {start_date}."
            if language == "en"
            else f"आपकी साढ़े साती {start_date} से शुरू होगी।"
        )
        paragraph_source = template["inactive_block"]["report_paragraphs"]
        summary_source = template["inactive_block"]["summary_block"]
    elif status == "Ended":
        short_description = (
            "Your Sade Sati has ended."
            if language == "en"
            else "आपकी साढ़े साती समाप्त हो चुकी है।"
        )
        paragraph_source = template["inactive_block"]["report_paragraphs"]
        summary_source = template["inactive_block"]["summary_block"]
    else:
        short_description = (
            "You are currently not under Sade Sati."
            if language == "en"
            else "आप वर्तमान में साढ़े साती के प्रभाव में नहीं हैं।"
        )
        paragraph_source = template["inactive_block"]["report_paragraphs"]
        summary_source = template["inactive_block"]["summary_block"]

    # --- Placeholders ---
    placeholder_data = {
        "moon_sign": moon_sign,
        "saturn_sign": saturn_rashi,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "active_phase": active_phase or "None",
    }

    def inject(text):
        for key, val in placeholder_data.items():
            text = text.replace(f"{{{key}}}", str(val))
        return text

    report_paragraphs = [inject(p) for p in paragraph_source]
    summary_points = [inject(p) for p in summary_source["points"]]
    general_explanation = inject(template.get("general_explanation", ""))

    return {
        "status": status,
        "moon_rashi": moon_sign,
        "saturn_rashi": saturn_rashi,
        "active_phase": active_phase,
        "phase_blocks": phase_dates,
        "total_period": {"start": start_date, "end": end_date},
        "short_description": short_description,
        "report_paragraphs": report_paragraphs,
        "summary_block": {
            "heading": summary_source["heading"],
            "points": summary_points
        },
        "explanation": general_explanation
    }

