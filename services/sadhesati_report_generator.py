import os
import json
from datetime import datetime
from smart_transit_engine import (
    get_planet_position_on,
    get_next_transits,
    get_prev_transits,
    get_transits,   # ⬅️ ensure this exists for Saturn full range
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


# ⬇️ Helper to build full timeline for 120 years
def generate_sadhesati_timeline(moon_sign: str, dob: str) -> list:
    try:
        moon_index = SATURN_RASHIS.index(moon_sign)
    except ValueError:
        return []

    # 3 relevant rashis for sade sati
    phase_rashis = [
        SATURN_RASHIS[(moon_index - 1) % 12],  # 1st phase
        SATURN_RASHIS[moon_index],             # 2nd phase
        SATURN_RASHIS[(moon_index + 1) % 12],  # 3rd phase
    ]

    # Date range: dob → dob + 120 years
    start_date = datetime.strptime(dob, "%Y-%m-%d")
    try:
        end_date = start_date.replace(year=start_date.year + 120)
    except ValueError:  # leap year fix
        end_date = start_date.replace(month=2, day=28, year=start_date.year + 120)

    # All Saturn transits
    all_transits = get_transits("Saturn", start_date, end_date)
    relevant = [t for t in all_transits if t["to_rashi"] in phase_rashis]
    relevant = sorted(relevant, key=lambda x: x["entering_date"])

    # Group into full cycles (1st+2nd+3rd)
    blocks = []
    i = 0
    while i < len(relevant) - 2:
        r1, r2, r3 = relevant[i:i+3]
        if [r1["to_rashi"], r2["to_rashi"], r3["to_rashi"]] == phase_rashis:
            blocks.append({
                "first_phase": {"start": r1["entering_date"], "end": r1["exit_date"]},
                "second_phase": {"start": r2["entering_date"], "end": r2["exit_date"]},
                "third_phase": {"start": r3["entering_date"], "end": r3["exit_date"]},
            })
            i += 3
        else:
            i += 1

    return blocks


def generate_sadhesati_report(kundali_data: dict) -> dict:
    moon_sign = kundali_data.get("moon_sign") or kundali_data.get("rashi")
    language = kundali_data.get("language", "en")
    dob = kundali_data.get("dob", "1900-01-01")  # safe fallback

    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    current_saturn_pos = get_planet_position_on(today_str, "Saturn")
    saturn_rashi = current_saturn_pos["rashi"]

    try:
        moon_index = SATURN_RASHIS.index(moon_sign)
        saturn_index = SATURN_RASHIS.index(saturn_rashi)
    except ValueError:
        return {
            "status": "Error",
            "heading": "Invalid Rashi",
            "explanation": "Moon sign or Saturn sign could not be matched."
        }

    # Active / Inactive phase detection
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

    # Nearby transits (old flow safe)
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
        phase_dates[label] = []
        for t in combined:
            if t["to_rashi"] == rashi_sequence[i]:
                phase_dates[label].append({
                    "start": t["entering_date"],
                    "end": t["exit_date"]
                })
        if not phase_dates[label]:
            phase_dates[label] = [{"start": "", "end": ""}]
            break

    impact_level = "Moderate"
    template = load_template(language)

    # Build current report content
    if status == "Active":
        key = phase.lower().replace(" ", "_")
        if key in phase_dates:
            start_date = phase_dates[key][0]["start"]
            end_date = phase_dates[key][0]["end"]
        else:
            start_date = end_date = ""

        short_description = (
            f"You are currently in the {phase} of Sade Sati."
            if language == "en"
            else f"आप वर्तमान में साढ़े साती के {phase} में हैं।"
        )
        paragraph_source = template["report_paragraphs"]
        summary_source = template["summary_block"]
    else:
        phase = None
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

    # ⬇️ NEW timeline attach
    timeline = generate_sadhesati_timeline(moon_sign, dob)

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
        "explanation": general_explanation,
        "timeline": timeline   # 🔥 extra but non-breaking
    }
