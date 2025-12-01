# modules/services/chat_requirement_engine.py

import os
import json
from openai import OpenAI

print("🔥 chat_requirement_engine imported")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

REQUIREMENT_PROMPT = """
You are an expert Vedic astrologer.

User question: "{question}"

Your ONLY job:
Return the list of EXACT astrological data required to answer this question.

STRICT RULES:
- Output MUST be ONLY valid JSON.
- No explanation.
- No markdown.
- No text before or after JSON.
- Format MUST match:

{
  "required_data": ["data_key_1", "data_key_2"]
}
"""

def get_required_data(question: str):
    prompt = REQUIREMENT_PROMPT.format(question=question)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You must output ONLY valid JSON which can be parsed by json.loads. "
                    "Do not add newlines before keys. Do not add comments. Do not indent excessively."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()

    print("\n===== GPT RAW REQUIREMENT OUTPUT =====")
    print(raw)
    print("======================================\n")

    # FIRST: try native JSON parse
    try:
        return json.loads(raw)
    except:
        pass

    # SECOND: auto-fix common issues
    fixed = raw.replace("\n", " ").replace("\r", " ").strip()
    fixed = fixed.replace("“", '"').replace("”", '"')

    try:
        return json.loads(fixed)
    except Exception as e:
        print("⚠️ JSON PARSE FAILED:", e)

        return {
            "error": "invalid_json_from_gpt",
            "raw": raw,
            "cleaned": fixed,
        }

