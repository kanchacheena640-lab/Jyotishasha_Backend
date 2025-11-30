# modules/services/chat_requirement_engine.py

import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

REQUIREMENT_PROMPT = """
You are an expert Vedic astrologer.

User question: "{question}"

Your ONLY job:
List EXACT astrological data needed to answer this question.

STRICT RULES:
- Return ONLY pure JSON
- No explanation
- No text before or after
- JSON must match EXACTLY this structure:

{
  "required_data": [
      "data_key_1",
      "data_key_2"
  ]
}

- Do NOT wrap JSON in quotes.
- Do NOT escape characters.
- Do NOT use markdown.
"""

def get_required_data(question: str):
    prompt = REQUIREMENT_PROMPT.format(question=question)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON. Never return text outside JSON."},
            {"role": "user",  "content": prompt}
        ],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()

    # 🔥 Direct JSON parse — no regex needed
    try:
        parsed = json.loads(raw)
        return parsed   # ALWAYS Python dict
    except json.JSONDecodeError:
        raise Exception("GPT did not return valid JSON → " + raw)
