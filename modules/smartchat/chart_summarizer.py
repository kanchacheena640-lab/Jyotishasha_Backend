# modules/smartchat/chart_summarizer.py

"""
Chart Summarizer (SmartChat)
----------------------------

This file converts raw kundali into short, clean, astrologer-style lines
which prompt_builder uses to create the GPT prompt.

It does NOT generate predictions — only structured summary text.

OUTPUT (chart dict):
{
    "asc": "...",
    "lagna_line": "...",
    "house_lord_line": "...",
    "planets_in_house_line": "...",
    "aspects_on_house_line": "...",
    "aspects_on_lord_line": "...",
    "conjunctions_line": "...",
    "dasha_line": "...",
    "transit_line": "..."
}
"""

def summarize_chart(kundali: dict, house_number: int, transit: dict):
    chart = {}

    # -----------------------------------------------------------------
    # 1) BASIC ASCENDANT LINE
    # -----------------------------------------------------------------
    asc = kundali.get("lagna_sign", "")
    chart["asc"] = asc or ""

    lagna_lord = kundali.get("lagna_lord", "")
    lagna_house = kundali.get("lagna_lord_house", "")

    chart["lagna_line"] = (
        f"Ascendant lord {lagna_lord} is placed in {lagna_house} house."
        if lagna_lord and lagna_house else ""
    )

    # -----------------------------------------------------------------
    # 2) HOUSE LORD DETAILS FOR DETECTED HOUSE
    # -----------------------------------------------------------------
    house_lord_key = f"house_{house_number}_lord"
    house_lord_house_key = f"house_{house_number}_lord_house"
    house_lord_dignity_key = f"house_{house_number}_lord_dignity"

    lord = kundali.get(house_lord_key, "")
    lord_house = kundali.get(house_lord_house_key, "")
    lord_dignity = kundali.get(house_lord_dignity_key, "")

    if lord:
        chart["house_lord_line"] = (
            f"{house_number}th house lord {lord} is in the {lord_house} house "
            f"with {lord_dignity} dignity."
        )
    else:
        chart["house_lord_line"] = ""

    # -----------------------------------------------------------------
    # 3) PLANETS IN THAT HOUSE
    # -----------------------------------------------------------------
    planets_in_house = kundali.get("planets_in_houses", {}).get(str(house_number), [])
    chart["planets_in_house_line"] = (
        f"Planets in {house_number}th house: {', '.join(planets_in_house)}."
        if planets_in_house else f"No planet is placed in the {house_number}th house."
    )

    # -----------------------------------------------------------------
    # 4) ASPECTS ON THAT HOUSE
    # -----------------------------------------------------------------
    aspects_house = kundali.get("aspects_on_houses", {}).get(str(house_number), [])
    chart["aspects_on_house_line"] = (
        f"Aspected by: {', '.join(aspects_house)}."
        if aspects_house else "No major planet aspects this house."
    )

    # -----------------------------------------------------------------
    # 5) ASPECTS ON HOUSE LORD
    # -----------------------------------------------------------------
    lord_aspects = kundali.get("aspects_on_lords", {}).get(str(house_number), [])
    chart["aspects_on_lord_line"] = (
        f"House lord aspected by: {', '.join(lord_aspects)}."
        if lord_aspects else "No direct aspect on house lord."
    )

    # -----------------------------------------------------------------
    # 6) CONJUNCTIONS WITH HOUSE LORD
    # -----------------------------------------------------------------
    lord_conj = kundali.get("conjunctions_with_lords", {}).get(str(house_number), [])
    chart["conjunctions_line"] = (
        f"Conjunctions with house lord: {', '.join(lord_conj)}."
        if lord_conj else "No conjunction with house lord."
    )

    # -----------------------------------------------------------------
    # 7) DASHA LINE (SHORT FORMAT)
    # -----------------------------------------------------------------
    dasha = kundali.get("dasha_summary", {})
    md = dasha.get("current_mahadasha", "")
    ad = dasha.get("current_antardasha", "")
    end = dasha.get("antardasha_end", "")

    chart["dasha_line"] = (
        f"Running Mahadasha: {md}, Antardasha: {ad} till {end}."
        if (md and ad) else "Dasha details unavailable."
    )

    # -----------------------------------------------------------------
    # 8) TRANSIT LINE
    # -----------------------------------------------------------------
    if "error" in transit:
        chart["transit_line"] = "Transit unavailable."
    else:
        lagna_transit = transit.get("lagna", "")
        moon_transit = transit.get("moon", "")
        chart["transit_line"] = (
            f"Lagna transiting: {lagna_transit}. Moon transiting: {moon_transit}."
        )

    return chart
