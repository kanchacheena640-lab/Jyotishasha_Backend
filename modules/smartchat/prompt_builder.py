# modules/services/smart_chat/prompt_builder.py

"""
SmartChat Prompt Builder (FINAL)
--------------------------------

This file builds the final GPT prompt:

Case A) If house_number = 0 → fallback mode (full-chart snapshot)
Case B) If 1–12 → house-focused short-chat prompt

This file does NOT calculate anything — all text is passed from chart_summarizer.
"""

def build_chat_prompt(question: str, house_number: int, chart: dict):
    """
    chart fields expected:
        asc
        lagna_lord_line
        house_line
        aspect_line
        dasha_line
        transit_line
    """

    asc = chart.get("asc", "")
    lagna_line = chart.get("lagna_lord_line", "")
    house_line = chart.get("house_line", "")
    aspects = chart.get("aspect_line", "")
    dasha = chart.get("dasha_line", "")
    transit = chart.get("transit_line", "")

    # -----------------------------------------
    # 1) FALLBACK MODE (no house detected)
    # -----------------------------------------
    if house_number == 0:
        return f"""
You are a Senior Vedic Astrologer.
Give a short, sharp 4–6 line practical answer.
No long theory.

User Question:
"{question}"

Birth Chart:
- Ascendant: {asc}
- {lagna_line}
- {aspects}

Dasha:
{dasha}

Transit:
{transit}

Give the final answer ONLY based on these planetary placements.
Do NOT repeat input lines. Only conclusion.
"""

    # -----------------------------------------
    # 2) HOUSE-FOCUSED PROMPT (SmartChat mode)
    # -----------------------------------------
    return f"""
You are a Senior Vedic Astrologer.
Give a short, clear 2–4 line answer only.
Avoid theory. Only final conclusion.

User Question:
"{question}"

Ascendant:
- {asc}
- {lagna_line}

House Focus → {house_number}th house:
{house_line}

Dasha:
{dasha}

Transit Influence:
{transit}

Give the result directly based on these placements and their links to other houses.
Do NOT repeat the above lines. Only give the final astrological conclusion.
"""
