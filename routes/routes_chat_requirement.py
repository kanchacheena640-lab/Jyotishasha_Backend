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
            {"role": "system", "content": "Return ONLY JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()

    # 🔥 DEBUG PRINT (critical)
    print("\n\n===== GPT RAW REQUIREMENT OUTPUT =====")
    print(raw)
    print("======================================\n\n")

    try:
        return json.loads(raw)
    except:
        return raw   # return as string so we can see it in API response

