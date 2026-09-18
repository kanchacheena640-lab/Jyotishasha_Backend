import os
import json
from smart_transit_engine import (
    get_next_transits,
    get_prev_transits,
    get_current_sign_residency,
)
# U4B.1 -- the core 12th/natal/2nd-sign -> 1st/2nd/3rd-Phase rule now
# lives in exactly ONE place, services/sadhesati_classifier.py (U4B.0
# proved this exact rule correct for all 144 Moon x Saturn sign
# combinations). SATURN_RASHIS below is kept as a name-compatible alias
# to SADE_SATI_SIGN_ORDER (nothing outside this file ever imported
# SATURN_RASHIS directly, verified by repo-wide search, but the alias
# costs nothing and removes any risk for a future importer).
from services.sadhesati_classifier import (
    SADE_SATI_SIGN_ORDER,
    classify_sade_sati,
    STATE_NOT_CALCULATED,
    STATE_SATURN_UNAVAILABLE,
)

SATURN_RASHIS = SADE_SATI_SIGN_ORDER

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

    # Timezone-correctness fix -- the current Saturn sign now comes
    # from the SAME canonical, timezone-aware transit authority
    # (transit_engine.py's Asia/Kolkata-based get_current_sign_
    # residency(), reached here via smart_transit_engine's forwarder)
    # the verified-correct Saturn Transit report already uses, instead
    # of this function's former get_planet_position_on(today_str, ...)
    # call, whose `today_str` came from a NAIVE datetime.now() read --
    # silently assumed to already be IST civil time regardless of the
    # host OS clock's own timezone (a real, previously-documented risk
    # on a UTC-clocked server; see services/current_saturn_resolver.py's
    # own module docstring). Never invents a Saturn sign: if the
    # canonical function cannot resolve a residency (its own documented
    # "should not happen in practice" case), saturn_rashi is left None,
    # which classify_sade_sati() below already turns into the EXISTING
    # STATE_SATURN_UNAVAILABLE -> "Error"/"Invalid Rashi" response --
    # no new failure path introduced.
    #
    # Reusing this ONE residency read for the active phase's own
    # phase_dates further down (instead of calling get_current_sign_
    # residency("Saturn") a second time) also removes a second,
    # separate live-clock read from this function entirely -- one
    # canonical instant, used consistently throughout.
    current_saturn_residency = get_current_sign_residency("Saturn")
    saturn_rashi = current_saturn_residency["to_rashi"] if current_saturn_residency else None

    # U4B.1 -- status/phase now come from the ONE shared pure classifier
    # (services/sadhesati_classifier.py) instead of this function's own
    # former inline delta computation. classify_sade_sati() returns the
    # SAME "invalid sign" outcome (as two distinguishable states) for
    # what this function's original bare `except:` treated as one
    # generic case -- both are mapped back to the EXACT SAME "Error"/
    # "Invalid Rashi" output below, so external behavior for this
    # function is unchanged for identical inputs.
    classification = classify_sade_sati(moon_sign, saturn_rashi)
    if classification["state"] in (STATE_NOT_CALCULATED, STATE_SATURN_UNAVAILABLE):
        return {
            "status": "Error",
            "heading": "Invalid Rashi",
            "explanation": "Moon sign or Saturn sign could not be matched."
        }

    status = "Active" if classification["active"] else "Inactive"
    phase = classification["phase"]

    # moon_index is still needed below (rashi_sequence) -- safe to
    # index directly here since classify_sade_sati() already confirmed
    # both signs are valid members of this exact list.
    moon_index = SATURN_RASHIS.index(moon_sign)

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
        # U4C.1A -- the phase whose sign equals Saturn's CURRENT live
        # sign (saturn_rashi) is, by definition, the one presently in
        # progress -- it must use the CURRENT residency (the boundary
        # segment actually containing "now"), never a sign-name search
        # over `combined`. `combined` only ever contains COMPLETED past
        # segments (from get_prev_transits) and NOT-YET-STARTED future
        # segments (from get_next_transits) -- the segment in progress
        # right now never appears there as a "to_rashi" match, so the
        # old code fell through to the next FUTURE re-entry of the same
        # sign (e.g. a retrograde Aries->Pisces re-entry years away)
        # and reported that as if it were the user's current period.
        # See U4C.1A report Sec.1/2 for the reproduced bug and the
        # canonical fix (transit_engine.get_current_sign_residency()).
        if rashi_sequence[i] == saturn_rashi:
            # Reuses the SAME residency instant already captured above
            # (see the timezone-correctness fix comment near the top of
            # this function) -- no second live-clock read.
            phase_dates[label] = {
                "start": current_saturn_residency["entering_date"],
                "end": current_saturn_residency["exit_date"],
            }
            continue
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
        if key in phase_dates:   # 🔥 safe check added
            start_date = phase_dates[key]["start"]
            end_date = phase_dates[key]["end"]
        else:
            start_date = end_date = ""   # fallback if not found

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
