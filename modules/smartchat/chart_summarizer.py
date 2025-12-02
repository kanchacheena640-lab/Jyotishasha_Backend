# modules/smartchat/chart_summarizer.py

"""
Chart summarizer for SmartChat

Input: full kundali JSON (as returned by calculate_full_kundali)
Output: chart_preview dict used in smartchat_engine + debug prompt chunks.

This file is PURE helper – no external dependencies.
"""

from typing import Any, Dict, List, Optional


# -------------------------------------------------------------------
# Small safe helpers
# -------------------------------------------------------------------


def _get(d: Dict, *keys, default=None):
    """Nested safe getter."""
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
    mapping = {
        1: "1st",
        2: "2nd",
        3: "3rd",
        4: "4th",
        5: "5th",
        6: "6th",
        7: "7th",
        8: "8th",
        9: "9th",
        10: "10th",
        11: "11th",
        12: "12th",
    }
    return mapping.get(n, f"{n}th")


def _get_house_lord(kundali: Dict[str, Any], house: int) -> Optional[str]:
    lords = _get(kundali, "chart_data", "lords", default={}) or {}

    key_main = HOUSE_KEY_MAP.get(house)
    key_alt = HOUSE_ALT_KEY_MAP.get(house)

    lord = lords.get(key_main)
    if not lord:
        lord = lords.get(key_alt)
    return lord


def _get_lagna_lord(kundali: Dict[str, Any]) -> Optional[str]:
    lords = _get(kundali, "chart_data", "lords", default={}) or {}
    return lords.get("lagna_lord") or lords.get("first_house_lord")


# -------------------------------------------------------------------
# Planets-in-house + house overview
# -------------------------------------------------------------------


def _planets_in_house_line(kundali: Dict[str, Any], house: Optional[int]) -> str:
    if not house:
        return "No specific house selected; focusing on overall chart balance."

    planets = _get(kundali, "chart_data", "planets", default=[]) or []
    in_house: List[Dict[str, Any]] = [p for p in planets if p.get("house") == house]

    if not in_house:
        return f"No planet is placed in the {_ordinal(house)} house."

    parts = []
    for p in in_house:
        name = p.get("name") or "Planet"
        sign = p.get("sign") or ""
        nak = p.get("nakshatra") or ""
        if sign and nak:
            parts.append(f"{name} in {sign} ({nak} nakshatra)")
        elif sign:
            parts.append(f"{name} in {sign}")
        else:
            parts.append(name)

    joined = ", ".join(parts)
    return f"In the {_ordinal(house)} house you have: {joined}."


def _house_focus_line(kundali: Dict[str, Any], house: Optional[int]) -> str:
    if not house:
        return ""

    overview = kundali.get("houses_overview") or []
    for h in overview:
        if h.get("house") == house:
            # Example: "Focus: Wealth, family, speech. Notable placements: Saturn."
            summary = h.get("summary") or ""
            focus = h.get("focus") or ""
            if summary:
                return summary
            if focus:
                return f"This house highlights: {focus}."
            break

    return f"This {_ordinal(house)} house covers its usual areas for your ascendant."


def _life_aspect_for_house(kundali: Dict[str, Any], house: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    life_aspects[].houses is like '7th' or '2nd, 4th'
    We try to match the detected house.
    """
    if not house:
        return None

    life_aspects = kundali.get("life_aspects") or []
    needle = _ordinal(house)
    for block in life_aspects:
        houses_str = (block.get("houses") or "").replace(" ", "")
        pieces = [h.strip() for h in houses_str.split(",") if h.strip()]
        if needle in pieces:
            return block
    return None


# -------------------------------------------------------------------
# Dasha + transit summarizers
# -------------------------------------------------------------------


def _dasha_line(kundali: Dict[str, Any]) -> str:
    d = kundali.get("dasha_summary") or {}

    current_block = d.get("current_block") or {}
    cur_maha = d.get("current_mahadasha") or {}
    cur_antar = d.get("current_antardasha") or {}

    maha_name = current_block.get("mahadasha") or cur_maha.get("mahadasha")
    antar_name = cur_antar.get("planet")
    period = current_block.get("period")

    maha_start = cur_maha.get("start")
    maha_end = cur_maha.get("end")
    antar_start = cur_antar.get("start")
    antar_end = cur_antar.get("end")

    parts = []

    if maha_name:
        if maha_start and maha_end:
            parts.append(f"Mahadasha: {maha_name} ({maha_start} → {maha_end})")
        else:
            parts.append(f"Mahadasha: {maha_name}")

    if antar_name:
        if antar_start and antar_end:
            parts.append(f"Antardasha: {antar_name} ({antar_start} → {antar_end})")
        else:
            parts.append(f"Antardasha: {antar_name}")

    if not parts and period:
        parts.append(f"Current dasha period: {period}")

    impact = current_block.get("impact_snippet")
    if impact:
        parts.append(impact)

    if not parts:
        return "No active dasha information could be summarized."

    return " | ".join(parts)


def _transit_line(kundali: Dict[str, Any]) -> str:
    """
    Use sadhesati + grah_dasha_block as a simple 'transit flavour' line.
    transit_analysis list is currently empty in your sample.
    """
    yogas = kundali.get("yogas") or {}
    sadhesati = yogas.get("sadhesati") or {}
    grah_dasha_block = kundali.get("grah_dasha_block") or {}

    pieces = []

    # Saturn / Sadhesati status
    saturn_rashi = sadhesati.get("saturn_rashi")
    moon_rashi = sadhesati.get("moon_rashi")
    status = sadhesati.get("status")
    short_desc = sadhesati.get("short_description")

    if status or saturn_rashi or moon_rashi:
        base = "Saturn Transit / Sadhesati: "
        details = []
        if status:
            details.append(f"Status – {status}")
        if saturn_rashi:
            details.append(f"Saturn in {saturn_rashi}")
        if moon_rashi:
            details.append(f"Moon sign {moon_rashi}")
        pieces.append(base + ", ".join(details))

    if short_desc:
        pieces.append(short_desc)

    # Grah dasha focus (in Hindi, already nicely written)
    grah_text = grah_dasha_block.get("grah_dasha_text")
    if grah_text:
        pieces.append(f"Grah-dasha focus: {grah_text}")

    if not pieces:
        return "No special transit or Sadhesati effect is currently highlighted."

    return " | ".join(pieces)


# -------------------------------------------------------------------
# Yogas / aspects helpers (light-weight)
# -------------------------------------------------------------------


def _yogas_touching_house(kundali: Dict[str, Any], house: Optional[int]) -> List[str]:
    if not house:
        return []

    yogas = kundali.get("yogas") or {}
    active = []
    for key, block in yogas.items():
        if not isinstance(block, dict):
            continue
        if not block.get("is_active"):
            continue
        reasons = " ".join(block.get("reasons") or [])
        # simple heuristic: look for 'house X' pattern
        token = f"house {house}"
        if token in reasons:
            active.append(block.get("name") or key)
    return active


def _yogas_for_lord(kundali: Dict[str, Any], lord: Optional[str]) -> List[str]:
    if not lord:
        return []
    yogas = kundali.get("yogas") or {}
    active = []
    for key, block in yogas.items():
        if not isinstance(block, dict):
            continue
        if not block.get("is_active"):
            continue
        reasons = " ".join(block.get("reasons") or [])
        desc = (block.get("description") or "") + " " + reasons
        if lord in desc:
            active.append(block.get("name") or key)
    return active


def _conjunction_yogas(kundali: Dict[str, Any]) -> List[str]:
    yogas = kundali.get("yogas") or {}
    hits = []
    for key, block in yogas.items():
        if not isinstance(block, dict):
            continue
        if not block.get("is_active"):
            continue
        reasons = " ".join(block.get("reasons") or [])
        if "same house" in reasons or "Conjunction" in reasons or "conjunction" in reasons:
            hits.append(block.get("name") or key)
    return hits


# -------------------------------------------------------------------
# MAIN ENTRY
# -------------------------------------------------------------------


def build_chart_preview(
    kundali: Dict[str, Any],
    detected_house: Optional[int] = None,
    question_topic: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a compact chart_preview block for SmartChat.

    - kundali: full kundali JSON dict (like sample you shared)
    - detected_house: int (1–12) or None, as decided by requirement engine
    - question_topic: optional string (career, marriage, health, etc.) – currently not hard-used
    """

    asc = kundali.get("lagna_sign") or _get(kundali, "chart_data", "ascendant") or "Unknown"
    lagna_lord = _get_lagna_lord(kundali)
    asc_line = f"Ascendant (Lagna) is {asc}."
    if lagna_lord:
        asc_line = f"Ascendant (Lagna) is {asc}, ruled by {lagna_lord}."

    # Lagna trait – already a beautiful Hindi paragraph, keep short
    lagna_trait = kundali.get("lagna_trait") or ""
    if lagna_trait:
        lagna_line = f"Lagna trait: {lagna_trait}"
    else:
        lagna_line = "Your Lagna sets the overall tone of personality, balance and life direction."

    # House lord line
    if detected_house:
        lord = _get_house_lord(kundali, detected_house)
        if lord:
            house_lord_line = (
                f"The lord of your {_ordinal(detected_house)} house is {lord}. "
                f"It becomes important for this area of life."
            )
        else:
            house_lord_line = f"The {_ordinal(detected_house)} house lord is not clearly specified in this snapshot."
    else:
        house_lord_line = "No single house is highlighted; reading the chart in a holistic way."

    # House focus & planets
    planets_in_house_line = _planets_in_house_line(kundali, detected_house)
    house_focus_line = _house_focus_line(kundali, detected_house)

    # Life aspect line (if we found any matching block)
    aspect_block = _life_aspect_for_house(kundali, detected_house)
    if aspect_block:
        aspect_name = aspect_block.get("aspect") or ""
        aspect_summary = aspect_block.get("summary") or ""
        if aspect_name and aspect_summary:
            aspects_on_house_line = f"{aspect_name}: {aspect_summary}"
        elif aspect_summary:
            aspects_on_house_line = aspect_summary
        else:
            aspects_on_house_line = ""
    else:
        # Fallback generic with yogas
        yogas_for_house = _yogas_touching_house(kundali, detected_house)
        if yogas_for_house:
            joined = ", ".join(yogas_for_house)
            aspects_on_house_line = (
                f"Some active yogas influencing this house include: {joined}."
            )
        elif detected_house:
            aspects_on_house_line = (
                f"No major classical yogas are directly tied to the {_ordinal(detected_house)} house in this snapshot."
            )
        else:
            aspects_on_house_line = "House-wise yogas will be considered contextually in the answer."

    # Aspects on house lord (via yogas)
    lord_for_house = _get_house_lord(kundali, detected_house) if detected_house else None
    lord_yogas = _yogas_for_lord(kundali, lord_for_house)
    if lord_for_house and lord_yogas:
        aspects_on_lord_line = (
            f"House lord {lord_for_house} participates in: {', '.join(lord_yogas)}."
        )
    elif lord_for_house:
        aspects_on_lord_line = (
            f"House lord {lord_for_house} is active but not forming a very sharp classical yog in this summary."
        )
    else:
        aspects_on_lord_line = "No specific lord-based yogas highlighted."

    # Conjunction-based yogas (for conjunctions_line)
    conj_yogas = _conjunction_yogas(kundali)
    if conj_yogas:
        conjunctions_line = (
            "Important conjunction-based yogas in your chart: " + ", ".join(conj_yogas) + "."
        )
    else:
        conjunctions_line = "No major conjunction-based Rajyogs are prominently highlighted."

    # Dasha + transit lines
    dasha_line = _dasha_line(kundali)
    transit_line = _transit_line(kundali)

    # Final dict – keys expected by routes_smartchat response
    chart_preview = {
        "asc": asc,
        "lagna_line": lagna_line,
        "house_lord_line": house_lord_line,
        "planets_in_house_line": planets_in_house_line,
        "aspects_on_house_line": aspects_on_house_line,
        "aspects_on_lord_line": aspects_on_lord_line,
        "conjunctions_line": conjunctions_line,
        "dasha_line": dasha_line,
        "transit_line": transit_line,
        "house_focus_line": house_focus_line,
        # helpful to know which house was used
        "detected_house": detected_house,
        "lagna_lord": lagna_lord,
    }

    return chart_preview
