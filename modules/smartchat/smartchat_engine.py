# modules/services/smart_chat/smartchat_engine.py

"""
SmartChat Engine (FINAL)
------------------------

FULL FLOW:
1) detect house using keyword_map
2) generate kundali
3) get transit snapshot
4) build house-wise astrology summary
5) build GPT prompt
6) get final 5–8 line answer

USED BY:
- routes_chat.py
- ChatPack (8 questions)
"""

import os
from openai import OpenAI

from services.full_kundali_service import generate_full_kundali_payload
from modules.smartchat.keyword_map import detect_house
from modules.smartchat.chart_summarizer import summarize_chart
from modules.smartchat.prompt_builder import build_chat_prompt
from transit_engine import get_current_positions


# ----------------------------------------------------------
# Initialize OpenAI client (singleton)
# ----------------------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def run_smartchat(birth: dict, question: str) -> dict:
    """
    INPUT:
        birth = {
            "name": "",
            "dob": "",
            "tob": "",
            "pob": "",
            "lat": float,
            "lng": float,
            "tz": "+05:30"
        }
        question = raw user text
    
    OUTPUT:
        {
            "answer": "...",
            "detected_house": int,
            "debug_prompt": "...",   # optional for debugging
            "chart_preview": {...}
        }
    """

    # ---------------------------------------------------------------------
    # 1) Detect house via keywords
    # ---------------------------------------------------------------------
    house_number = detect_house(question)  # 1–12 or 0 fallback

    # ---------------------------------------------------------------------
    # 2) Generate full kundali
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # 3) Transit snapshot
    # ---------------------------------------------------------------------
    try:
        transit = get_current_positions()
    except Exception as e:
        transit = {"error": str(e)}

    # ---------------------------------------------------------------------
    # 4) Summarize chart (house-wise + fallback)
    # ---------------------------------------------------------------------
    chart_summary = summarize_chart(
        kundali=kundali,
        detected_house=house_number
    )

    # ---------------------------------------------------------------------
    # 5) Build prompt
    # ---------------------------------------------------------------------
    gpt_prompt = build_chat_prompt(
        question=question,
        house_number=house_number,
        chart=chart_summary
    )

    # ---------------------------------------------------------------------
    # 6) Call GPT
    # ---------------------------------------------------------------------
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a senior Vedic astrologer."},
                {"role": "user", "content": gpt_prompt}
            ],
            temperature=0.55,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        answer = f"AI temporarily unavailable. Error: {e}"

    # ---------------------------------------------------------------------
    # 7) Final structured output
    # ---------------------------------------------------------------------
    return {
        "answer": answer,
        "detected_house": house_number,
        "chart_preview": chart_summary,      # optional for frontend debug
        "kundali_preview": kundali.get("chart_data", {}),
        "transit_preview": transit,
        "dasha_preview": kundali.get("dasha_summary", {}),
        "debug_prompt": gpt_prompt,          # show only for internal testing
    }
