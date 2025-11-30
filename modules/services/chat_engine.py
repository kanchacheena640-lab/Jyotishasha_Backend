# modules/services/chat_engine.py

"""
Chat Engine (Core logic for ChatPack 51 system)

This engine:
- Generates full kundali
- Gets current transits
- Extracts dasha summary
- Builds GPT prompt
- Calls GPT model
- Returns final astrological answer

Used by:
- routes_chat.py (free + pack)
"""

from openai import OpenAI
import os
from services.full_kundali_service import generate_full_kundali_payload
from transit_engine import get_current_positions


# Initialize OpenAI client once
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def chat_engine(birth_data: dict, question: str) -> dict:
    """
    Core chat engine used by BOTH:
    - Free daily chat
    - ChatPack (8 questions)

    Inputs:
    - birth_data = {
        "name": "",
        "dob": "",
        "tob": "",
        "pob": "",
        "lat": float,
        "lng": float,
        "tz": "+05:30"
    }
    - question = string

    Returns dict:
    {
        "answer": "...",
        "kundali_preview": ...,
        "dasha_preview": ...,
        "transit_preview": ...
    }
    """

    # -----------------------------
    # 1) Generate full kundali
    # -----------------------------
    kundali = generate_full_kundali_payload({
        "name": birth_data["name"],
        "dob": birth_data["dob"],
        "tob": birth_data["tob"],
        "place_name": birth_data["pob"],
        "lat": float(birth_data["lat"]),
        "lng": float(birth_data["lng"]),
        "timezone": str(birth_data.get("tz", "+05:30")),
        "language": "en"
    })

    # -----------------------------
    # 2) Current transit snapshot
    # -----------------------------
    try:
        transit = get_current_positions()
    except Exception as e:
        transit = {"error": str(e)}

    # -----------------------------
    # 3) Dasha summary
    # -----------------------------
    dasha = kundali.get("dasha_summary", {})

    # -----------------------------
    # 4) GPT Prompt
    # -----------------------------
    prompt = f"""
User Question: {question}

Birth Chart Summary:
- Ascendant: {kundali.get('lagna_sign')}
- Key House Summary: {kundali.get('house_summary', {})}

Dasha Summary:
{dasha}

Transit Summary:
{transit}

Follow these rules:
- You are a senior Vedic astrologer.
- Answer in 4–6 focused lines.
- DO NOT mention houses where no planet exists.
- Include transit + dasha + birth chart insights.
- Avoid health, legal or medical advice.
- End every answer with: "This answer is for astrological guidance only."
"""

    # -----------------------------
    # 5) GPT Call
    # -----------------------------
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a senior Vedic astrologer."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.65,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        answer = f"AI temporarily unavailable. Error: {e}"

    # -----------------------------
    # 6) Return final JSON
    # -----------------------------
    return {
        "answer": answer,
        "kundali_preview": kundali.get("chart_data", {}).get("ascendant"),
        "dasha_preview": dasha,
        "transit_preview": transit,
        "disclaimer": "This answer is for astrological guidance only.",
    }
