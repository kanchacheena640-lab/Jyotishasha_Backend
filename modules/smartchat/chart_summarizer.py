# modules/smartchat/chart_summarizer.py

from typing import Any, Dict, List, Optional

# -------------------------------------------------------------------
# Small safe helpers
# -------------------------------------------------------------------

def _get(d: Dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur

# -------------------------------------------------------------------
# House / lord helpers
# -------------------------------------------------------------------

HOUSE_KEY_MAP = {
    1: "1_house_lord",
    2: "2_house_lord",
    3: "3_house_lord",
    4: "4_house_lord",
    5: "5_house_lord",
    6: "6_house_lord",
    7: "7_house_lord",
    8: "8_house_lord",
    9: "9_house_lord",
    10: "10_house_lord",
    11: "11_house_lord",
    12: "12_house_lord",
}

HOUSE_ALT_KEY_MAP = {
    1: "first_house_lord",
    2: "second_house_lord",
    3: "third_house_lord",
    4: "fourth_house_lord",
    5: "fifth_house_lord",
    6: "sixth_house_lord",
    7: "seventh_house_lord",
    8: "eighth_house_lord",
    9: "ninth_house_lord",
    10: "tenth_house_lord",
    11: "eleventh_house_lord",
    12: "twelfth_house_lord",
}

def _ordinal(n: int) -> str:
    return {
        1:"1st",2:"2nd",3:"3rd",4:"4th",5:"5th",6:"6th",
        7:"7th",8:"8th",9:"9th",10:"10th",11:"11th",12:"12th"
    }.get(n,f"{n}th")

def _get_house_lord(kundali, house):
    lords = _get(kundali, "chart_data", "lords", default={}) or {}
    return lords.get(HOUSE_KEY_MAP.get(house)) or lords.get(HOUSE_ALT_KEY_MAP.get(house))

def _get_lagna_lord(kundali):
    lords = _get(kundali, "chart_data", "lords", default={}) or {}
    return lords.get("lagna_lord") or lords.get("first_house_lord")

# -------------------------------------------------------------------
# Planets + positions
# -------------------------------------------------------------------

def _find_planet_details(kundali, planet_name):
    """Return dict: {house, sign, degree, dignity}"""
    planets = _get(kundali, "chart_data", "planets", default=[]) or []

    for p in planets:
        if p.get("name") == planet_name:
            return {
                "house": p.get("house"),
                "sign": p.get("sign"),
                "degree": p.get("degree"),
                "dignity": p.get("dignity") or p.get("strength") or "",
            }
    return {"house": None, "sign": "", "degree": "", "dignity": ""}

# -------------------------------------------------------------------
# Planets in target house
# -------------------------------------------------------------------

def _planets_in_house_list(kundali, house):
    if not house:
        return ""
    planets = _get(kundali, "chart_data", "planets", default=[]) or []
    names = [p["name"] for p in planets if p.get("house") == house]
    return ", ".join(names) if names else "None"

# -------------------------------------------------------------------
# Drishti Aspect (simple)
# -------------------------------------------------------------------

def _aspect_planets_on_house(kundali, target_house):
    if not target_house:
        return ""

    planets = _get(kundali, "chart_data", "planets", default=[]) or []
    hit = []

    for p in planets:
        name = p.get("name")
        house = p.get("house")

        if not house: 
            continue

        # 7th aspect
        if (house + 7) % 12 == target_house % 12:
            hit.append(name)

        # Jupiter 5/9
        if name == "Jupiter":
            if (house + 5) % 12 == target_house % 12 or (house + 9) % 12 == target_house % 12:
                hit.append(name)

        # Mars 4/8
        if name == "Mars":
            if (house + 4) % 12 == target_house % 12 or (house + 8) % 12 == target_house % 12:
                hit.append(name)

        # Saturn 3/10
        if name == "Saturn":
            if (house + 3) % 12 == target_house % 12 or (house + 10) % 12 == target_house % 12:
                hit.append(name)

    return ", ".join(sorted(set(hit))) if hit else "None"

# -------------------------------------------------------------------
# Relevant transit planets affecting house
# -------------------------------------------------------------------

def _relevant_transits(kundali, target_house):
    if not target_house:
        return ""

    planets = _get(kundali, "chart_data", "planets", default=[])
    transits = _get(kundali, "transits", default={}) or {}

    names = []

    # 1) transit planet in that house
    for name, t in transits.items():
        if t.get("house") == target_house:
            names.append(name)

    # 2) transit planets aspecting that house
    for name, t in transits.items():
        h = t.get("house")
        if not h:
            continue

        if (h + 7) % 12 == target_house % 12:
            names.append(name)

        if name == "Jupiter" and (
            (h + 5) % 12 == target_house % 12 or (h + 9) % 12 == target_house % 12
        ):
            names.append(name)

        if name == "Mars" and (
            (h + 4) % 12 == target_house % 12 or (h + 8) % 12 == target_house % 12
        ):
            names.append(name)

        if name == "Saturn" and (
            (h + 3) % 12 == target_house % 12 or (h + 10) % 12 == target_house % 12
        ):
            names.append(name)

    return ", ".join(sorted(set(names))) if names else "None"

# -------------------------------------------------------------------
# Dasha & Transit (old logic kept)
# -------------------------------------------------------------------

def _dasha_line(kundali):
    d = kundali.get("dasha_summary") or {}
    cur_blk = d.get("current_block") or {}
    cur_maha = d.get("current_mahadasha") or {}
    cur_antar = d.get("current_antardasha") or {}

    maha = cur_blk.get("mahadasha") or cur_maha.get("mahadasha")
    antar = cur_antar.get("planet")

    parts = []
    if maha:
        parts.append(f"Mahadasha: {maha}")
    if antar:
        parts.append(f"Antardasha: {antar}")

    return " | ".join(parts) if parts else "No active dasha information."

def _transit_line(kundali):
    return kundali.get("transit_summary") or "General transit phase active."

def _get_dignity_from_overview(kundali, planet_name):
    overview = kundali.get("planet_overview") or []
    for block in overview:
        if block.get("planet") == planet_name:
            summary = block.get("summary", "")
            # Example: "• Dignity: Exalted"
            for line in summary.split("\n"):
                if "Dignity:" in line:
                    return line.replace("•", "").replace("Dignity:", "").strip()
    return ""

# -------------------------------------------------------------------
# MAIN — build_chart_preview
# -------------------------------------------------------------------

def build_chart_preview(kundali, detected_house=None, question_topic=None):

    asc = kundali.get("lagna_sign") or "Unknown"
    lagna_lord = _get_lagna_lord(kundali)

    # Extract full planet details for lagna lord
    lagna_lord_details = _find_planet_details(kundali, lagna_lord)

    # House lord
    house_lord = _get_house_lord(kundali, detected_house)
    house_lord_details = _find_planet_details(kundali, house_lord) if house_lord else {}

    # planets in that house
    house_planet_list = _planets_in_house_list(kundali, detected_house)

    # aspects
    aspect_planet_list = _aspect_planets_on_house(kundali, detected_house)

    # transits
    relevant_transit_planets = _relevant_transits(kundali, detected_house)

    # OLD SUMMARY FIELDS ARE UNTOUCHED
    chart_preview = {
        "lagna_sign": asc,
        "lagna_lord": lagna_lord,

        # NEW required block for your paragraph
        "lagna_lord_house": lagna_lord_details.get("house"),
        "lagna_lord_sign": lagna_lord_details.get("sign"),
        "lagna_lord_degree": lagna_lord_details.get("degree"),
        "lagna_lord_dignity": _get_dignity_from_overview(kundali, lagna_lord),

        "house_lord": house_lord,
        "house_lord_house": house_lord_details.get("house"),
        "house_lord_sign": house_lord_details.get("sign"),
        "house_lord_degree": house_lord_details.get("degree"),
        "house_lord_dignity": _get_dignity_from_overview(kundali, house_lord),

        "house_planet_list": house_planet_list,
        "aspect_planet_list": aspect_planet_list,
        "relevant_transit_planets": relevant_transit_planets,

        # OLD FIELDS (kept exactly same)
        "lagna_line": f"Ascendant (Lagna) is {asc}, ruled by {lagna_lord}.",
        "dasha_line": _dasha_line(kundali),
        "transit_line": _transit_line(kundali),
        "detected_house": detected_house,
    }

    return chart_preview


def summarize_chart(kundali, detected_house=None, house_number=None, transit=None, question_topic=None):
    house = house_number if house_number is not None else detected_house
    return build_chart_preview(kundali, detected_house=house, question_topic=question_topic)
