"""
SmartChat Engine (FINAL CLEAN OUTPUT)
-------------------------------------
GPT ko poora data milta rahega, 
BUT frontend ko sirf clean answer milega.
"""

import os
from openai import OpenAI

from services.full_kundali_service import generate_full_kundali_payload
from modules.smartchat.keyword_map import detect_house
from modules.smartchat.chart_summarizer import summarize_chart
from modules.smartchat.prompt_builder import build_chat_prompt
from transit_engine import get_current_positions


# ----------------------------------------------------------
# Initialize OpenAI client
# ----------------------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ----------------------------------------------------------
# CLEAN ONLY ANSWER
# ----------------------------------------------------------
def clean_answer(text: str) -> str:
    """
    Removes preview/debug/dasha/chart lines and keeps only GPT’s
    final astrology answer.
    """
    banned_keywords = [
        "Ascendant", "Lagna",
        "Dasha", "Mahadasha", "Antardasha",
        "Transit", "Chart", "Preview",
        "house", "detected", "debug", "{", "}"
    ]

    cleaned = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue

        # skip unwanted info lines
        if any(s.startswith(b) for b in banned_keywords):
            continue

        cleaned.append(s)

    return "\n".join(cleaned)


# ----------------------------------------------------------
# MAIN ENGINE
# ----------------------------------------------------------
def run_smartchat(birth: dict, question: str) -> dict:
    """
    Returns ONLY the final astrology answer.
    Backend still uses full kundali + transit for GPT.
    """

    # 1) Detect house
    house_number = detect_house(question)

    # 2) Generate kundali
    kundali = generate_full_kundali_payload({
        "name": birth.get("name", ""),
        "dob": birth["dob"],
        "tob": birth["tob"],
        "place_name": birth["pob"],
        "lat": float(birth["lat"]),
        "lng": float(birth["lng"]),
        "timezone": birth.get("tz", "+05:30"),
        "language": "en",
    })

    # 3) Transit
    try:
        transit = get_current_positions()
    except Exception as e:
        transit = {"positions": {}, "error": str(e)}

    # 4) Chart summarizer
    chart_summary = summarize_chart(
        kundali=kundali,
        detected_house=house_number,
        transit=transit
    )

    # 5) GPT Prompt
    gpt_prompt = build_chat_prompt(
        question=question,
        house_number=house_number,
        chart=chart_summary
    )

    # 6) GPT Call
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a senior Vedic astrologer."},
                {"role": "user", "content": gpt_prompt}
            ],
            temperature=0.55,
        )

        raw_answer = response.choices[0].message.content.strip()
        answer = clean_answer(raw_answer)

    except Exception as e:
        answer = f"AI temporarily unavailable. Error: {e}"

    # 7) Return ONLY answer
    return {
        "answer": answer
    }
