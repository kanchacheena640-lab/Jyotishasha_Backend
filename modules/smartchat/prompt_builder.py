"""
SmartChat Prompt Builder (FINAL — Stable + Paragraph Mode)
---------------------------------------------------------

Case A) If house_number = 0 → fallback mode
Case B) If 1–12 → paragraph-based short prediction prompt
"""


def build_chat_prompt(question: str, house_number: int, chart: dict):
    """
    chart fields expected:
        lagna_sign, lagna_lord, lagna_lord_house, lagna_lord_sign,
        lagna_lord_degree, lagna_lord_dignity

        house_lord, house_lord_house, house_lord_sign,
        house_lord_degree, house_lord_dignity

        house_planet_list, aspect_planet_list, relevant_transit_planets

        dasha_line, transit_line
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
    current_transit_snapshot = chart.get("transit_line", "")  # FULL today's transit snapshot

    # ======================================================
    # 1) FALLBACK MODE (NO HOUSE DETECTED)
    # ======================================================
    if house_number == 0:
        return f"""
You are a Senior Vedic Astrologer.
Give a meaningful 5–8 line astrological answer.
Avoid long theory; give direct conclusion.

User Question:
\"{question}\"

Birth Chart:
- Ascendant: {asc}
- {chart.get("lagna_line", "")}
- {chart.get("aspects_on_house_line", "")}

Dasha:
{dasha}

Current Transit (Today):
{current_transit_snapshot}

Give the final answer ONLY based on these placements.
Do NOT repeat input lines.
"""

    # ======================================================
    # 2) HOUSE-FOCUSED PARAGRAPH MODE
    # ======================================================

    paragraph = (
        f"Your Ascendant is {lagna_sign}, ruled by {lagna_lord}, currently placed in the "
        f"{lagna_lord_house} house in {lagna_lord_sign} at {lagna_lord_degree}°, showing "
        f"{lagna_lord_dignity} strength. "
        f"The lord of the {house_number} house is {house_lord}, positioned in the {house_lord_house} house "
        f"in {house_lord_sign} at {house_lord_degree}°, indicating {house_lord_dignity} dignity. "
        f"The {house_number} house contains {house_planet_list}, and receives aspects from "
        f"{aspect_planet_list}. "
        f"Current transits activating this house include: {relevant_transit_planets}."
    )

    return f"""
You are a Senior Vedic Astrologer.
Give a meaningful 5–8 line astrological answer with proper reasoning.
Avoid long theory; give direct conclusions.

User Question:
\"{question}\"

Astrological Summary:
{paragraph}

Dasha:
{dasha}

Current Transit (Today):
{current_transit_snapshot}

RULE FOR TRANSIT:
Use the current transit influence ONLY to understand the present timeline,
short-term activation, mood shifts, and how strongly the issue is triggered right now.
Birth chart decides the actual outcome; transit only amplifies or activates.
(Do NOT mention this rule in the answer.)

Give the final conclusion in 5–8 lines.
Do NOT repeat any input lines.
"""
