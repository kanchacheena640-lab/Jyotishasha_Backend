"""
SmartChat Prompt Builder (FINAL — Stable + Paragraph Mode)
---------------------------------------------------------

Case A) If house_number = 0 → fallback mode (your existing working prompt)
Case B) If 1–12 → NEW paragraph-based prompt
"""


def build_chat_prompt(question: str, house_number: int, chart: dict):
    """
    chart fields expected:
        asc
        lagna_sign
        lagna_lord
        lagna_lord_house
        lagna_lord_sign
        lagna_lord_degree
        lagna_lord_dignity

        house_lord
        house_lord_house
        house_lord_sign
        house_lord_degree
        house_lord_dignity

        house_planet_list
        aspect_planet_list
        relevant_transit_planets
    """

    # ----------- FETCH ALL FIELDS SAFELY -----------
    asc = chart.get("asc", "")

    lagna_sign = chart.get("lagna_sign", "")
    lagna_lord = chart.get("lagna_lord", "")
    lagna_lord_house = chart.get("lagna_lord_house", "")
    lagna_lord_sign = chart.get("lagna_lord_sign", "")
    lagna_lord_degree = chart.get("lagna_lord_degree", "")
    lagna_lord_dignity = chart.get("lagna_lord_dignity", "")

    house_lord = chart.get("house_lord", "")
    house_lord_house = chart.get("house_lord_house", "")
    house_lord_sign = chart.get("house_lord_sign", "")
    house_lord_degree = chart.get("house_lord_degree", "")
    house_lord_dignity = chart.get("house_lord_dignity", "")

    house_planet_list = chart.get("house_planet_list", "None")
    aspect_planet_list = chart.get("aspect_planet_list", "None")
    relevant_transit_planets = chart.get("relevant_transit_planets", "None")

    dasha = chart.get("dasha_line", "")
    transit = chart.get("transit_line", "")

    # ======================================================
    # 1) FALLBACK MODE (NO HOUSE DETECTED)
    # ======================================================
    if house_number == 0:
        return f"""
You are a Senior Vedic Astrologer.
Give a clear, meaningful 5–8 line astrological answer.
Avoid long theory, but give proper reasoning.

User Question:
"{question}"

Birth Chart:
- Ascendant: {asc}
- {chart.get("lagna_line", "")}
- {chart.get("aspects_on_house_line", "")}

Dasha:
{dasha}

Transit:
{transit}

Give the final answer ONLY based on these planetary placements.
Do NOT repeat input lines. Only conclusion.
"""

    # ======================================================
    # 2) HOUSE-FOCUSED MODE → NEW FULL PARAGRAPH PROMPT
    # ======================================================

    paragraph = (
        f"Your Ascendant is {lagna_sign}, ruled by {lagna_lord}, currently placed in the "
        f"{lagna_lord_house} house in {lagna_lord_sign} at {lagna_lord_degree}°, "
        f"showing {lagna_lord_dignity} strength. "
        f"The lord of the {house_number} house is {house_lord}, placed in the {house_lord_house} house "
        f"in {house_lord_sign} at {house_lord_degree}°, showing {house_lord_dignity} dignity. "
        f"The {house_number} house contains {house_planet_list}. "
        f"The {house_number} house is aspected by {aspect_planet_list}. "
        f"Current relevant transits affecting this house involve {relevant_transit_planets}."
    )

    return f"""
You are a Senior Vedic Astrologer.
Give a clear, meaningful 5–8 line astrological answer.
Avoid long theory, but give proper reasoning.

User Question:
"{question}"

Astrological Summary:
{paragraph}

Dasha:
{dasha}

Transit Influence (Today):
{chart.get("relevant_transit_planets", "")}

Give the result ONLY based given prompt. Use the current transit influence ONLY to understand the present timeline, activation of events, short-term mood shifts, and how strongly the situation is getting triggered right now. The core judgement must always come from the birth chart placements, and transit should be treated as an activator or amplifier.
Do NOT repeat the lines. Give the final astrological conclusion in 5–8 lines.
"""
