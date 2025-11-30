# modules/services/chat_requirement_engine.py

import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

REQUIREMENT_PROMPT = """
You are an expert Vedic astrologer.

User asked: "{question}"

List EXACTLY the astrological data you need from the user's 
birth chart, dasha, and transits to answer the question accurately.

IMPORTANT RULES:
- Return ONLY JSON.
- No explanation.
- No extra text.
- If some data is optional, still include it.
- Use short, machine-friendly data keywords.
- Do not include sentences.
- Example:
{
  "required_data": [
      "5th_lord_position",
      "venus_transit_status"
  ]
}
"""

def get_required_data(question: str):
    prompt = REQUIREMENT_PROMPT.format(question=question)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a Vedic astrology requirement extractor."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()

    return raw  # raw JSON string (frontend/backend will parse)
