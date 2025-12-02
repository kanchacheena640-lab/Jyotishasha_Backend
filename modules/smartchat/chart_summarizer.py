# modules/smartchat/chart_summarizer.py

"""
Final SmartChat Chart Summarizer
--------------------------------
Extract EXACT values needed for the placeholder prompt.

OUTPUT FIELDS:
    lagna_rashi
    lagna_lord
    lagna_lord_house
    lagna_lord_dignity
    lagna_lord_degree
    lagna_lord_nakshatra

    house_number
    house_lord
    house_lord_house
    house_lord_sign
    house_lord_degree
    house_lord_nakshatra

    planets_in_house
    aspected_planets_on_house
    aspected_planets_on_lord
    conjunctions_here

    mahadasha
    antardasha

    transit_house_of_lord
    planets_transiting_house
    planets_transiting_8th_house
"""

from typing import Dict, Any, Optional, List


# ---------------------------
# Safe Getter
# ---------------------------
def _get(data: Dict, *keys, default=None):
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


# ---------------------------
# Helper: find house lord
# ---------------------------
HOUSE_MAIN = {
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

HOUSE_ALT = {
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


def _get_house_lord(kundali, house):
    lords = _get(kundali, "chart_data", "lords", default={}) or {}
    lord = lords.get(HOUSE_MAIN.get(house)) or lords.get(HOUSE_ALT.get(house))
    return lord


def _get_lagna_lord(kundali):
    lords = _get(kundali, "chart_data", "lords", default={}) or {}
    return lords.get("lagna_lord") or lords.get("first_house_lord")


# ---------------------------
# Helper: planet details
# ---------------------------
def _planet_details(kundali, planet_name):
    planets = _get(kundali, "chart_data", "planets", default=[])
    for p in planets:
        if p.get("name") == planet_name:
            return p
    return {}


# ---------------------------
# Helper: planets in house
# ---------------------------
def _planets_in_house(kundali, house):
    out = []
    planets = _get(kundali, "chart_data", "planets", default=[])
    for p in planets:
        if p.get("house") == house:
            text = f"{p.get('name')} in {p.get('sign')} ({p.get('nakshatra')} nakshatra, {p.get('degree')}°)"
            out.append(text)
    return ", ".join(out) if out else "None"


# ---------------------------
# Helper: Aspects (light)
# ---------------------------
def _aspected_on_house(kundali, house):
    yogas = kundali.get("yogas") or {}
    hits = []
    needle = f"house {house}"
    for key, block in yogas.items():
        if not isinstance(block, dict):
            continue
        if block.get("is_active"):
            reasons = " ".join(block.get("reasons") or [])
            if needle in reasons:
                hits.append(block.get("name"))
    return ", ".join(hits) if hits else "None"


def _aspected_on_lord(kundali, lord):
    if not lord:
        return "None"
    yogas = kundali.get("yogas") or {}
    hits = []
    for key, block in yogas.items():
        if not isinstance(block, dict):
            continue
        if block.get("is_active"):
            desc = (block.get("description") or "") + " " + " ".join(block.get("reasons") or [])
            if lord in desc:
                hits.append(block.get("name"))
    return ", ".join(hits) if hits else "None"


def _conjunctions(kundali):
    yogas = kundali.get("yogas") or {}
    hits = []
    for key, block in yogas.items():
        if block.get("is_active"):
            if "conjunction" in " ".join(block.get("reasons") or "").lower():
                hits.append(block.get("name"))
    return ", ".join(hits) if hits else "None"


# ---------------------------
# Helper: Dasha
# ---------------------------
def _extract_dasha(kundali):
    d = kundali.get("dasha_summary") or {}

    maha = d.get("current_mahadasha", {}).get("mahadasha")
    antar = d.get("current_antardasha", {}).get("planet")

    return maha or "Unknown", antar or "Unknown"


# ---------------------------
# Helper: Transit
# ---------------------------
def _transit_house_of_lord(transit, lord):
    if not lord:
        return "Unknown"
    lord_block = transit.get(lord)
    if not lord_block:
        return "Unknown"
    return lord_block.get("house", "Unknown")


def _transiting_planets_in_house(transit, house):
    hits = []
    for planet, block in transit.items():
        if isinstance(block, dict) and block.get("house") == house:
            hits.append(planet)
    return ", ".join(hits) if hits else "None"


# ---------------------------
# MAIN ENTRY
# ---------------------------
def summarize_chart(kundali: Dict[str, Any], house_number: int, transit: Dict[str, Any]):
    """
    Return EXACT fields needed by SmartChat Prompt Builder.
    """

    # -------- Lagna block --------
    lagna_rashi = kundali.get("lagna_sign", "Unknown")
    lagna_lord = _get_lagna_lord(kundali)
    lagna_lord_details = _planet_details(kundali, lagna_lord)

    # -------- House lord block --------
    house_lord = _get_house_lord(kundali, house_number)
    house_lord_details = _planet_details(kundali, house_lord)

    # -------- Dasha --------
    maha, antar = _extract_dasha(kundali)

    # -------- Transit --------
    transit_house_for_lord = _transit_house_of_lord(transit, house_lord)
    planets_trans_house = _transiting_planets_in_house(transit, house_number)
    planets_trans_8 = _transiting_planets_in_house(transit, 8)

    # -------- Final dict --------
    return {
        "lagna_rashi": lagna_rashi,
        "lagna_lord": lagna_lord,
        "lagna_lord_house": lagna_lord_details.get("house"),
        "lagna_lord_dignity": lagna_lord_details.get("dignity"),
        "lagna_lord_degree": lagna_lord_details.get("degree"),
        "lagna_lord_nakshatra": lagna_lord_details.get("nakshatra"),

        "house_number": house_number,
        "house_lord": house_lord,
        "house_lord_house": house_lord_details.get("house"),
        "house_lord_sign": house_lord_details.get("sign"),
        "house_lord_degree": house_lord_details.get("degree"),
        "house_lord_nakshatra": house_lord_details.get("nakshatra"),

        "planets_in_house": _planets_in_house(kundali, house_number),
        "aspected_planets_on_house": _aspected_on_house(kundali, house_number),
        "aspected_planets_on_lord": _aspected_on_lord(kundali, house_lord),
        "conjunctions_here": _conjunctions(kundali),

        "mahadasha": maha,
        "antardasha": antar,

        "transit_house_of_lord": transit_house_for_lord,
        "planets_transiting_house": planets_trans_house,
        "planets_transiting_8th_house": planets_trans_8,
    }
