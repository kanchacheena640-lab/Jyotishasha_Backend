# modules/services/chat_requirement_engine.py

import os
import json
import re
from openai import OpenAI

print("🔥 chat_requirement_engine imported")   # DEBUG PRINT

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
- JSON must match EXACT structure:

{
  "required_data": [
      "data_key_1",
      "data_key_2"
  ]
}

- Do NOT wrap JSON in quotes.
- Do NOT escape characters.
- Do NOT add markdown.
"""


def clean_json(raw: str):
    """
    Fix common GPT JSON issues:
    - smart quotes → normal quotes
    - remove trailing commas
    - extract only {...} block
    """
    if not raw:
        return raw

    # 1) Smart quotes → normal
    raw = raw.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    # 2) Extract JSON block
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)

    # 3) Remove trailing commas
    raw = re.sub(r",\s*}", "}", raw)
    raw = re.sub(r",\s*]", "]", raw)

    return raw


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

    # 🔥 CRITICAL DEBUG PRINT FOR RENDER LOGS
    print("\n\n===== GPT RAW REQUIREMENT OUTPUT =====")
    print(raw)
    print("======================================\n\n")

    cleaned = clean_json(raw)

    # Try parsing GPT output directly
    try:
        parsed = json.loads(cleaned)
        return parsed
    except Exception as e:
        print("⚠️ JSON PARSE FAILED:", str(e))
        return {
            "error": "invalid_json_from_gpt",
            "raw": raw,
            "cleaned": cleaned
        }
