# modules/services/chat_requirement_engine.py

import os
import re
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

REQUIREMENT_PROMPT = """
You are an expert Vedic astrologer.

User question: "{question}"

Your ONLY job:
Extract the exact astrological data points needed to answer this question.

STRICT RULES:
- Return ONLY pure JSON.
- NO explanation.
- NO text before or after.
- NO sentences in the array.
- Use only machine-friendly keys.
- ALWAYS follow this format:

{
  "required_data": [
      "some_data_key",
      "another_key"
  ]
}
"""

def extract_json_block(text: str):
    """Extract only the JSON object from GPT output."""
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return match.group(0)
    return text  # fallback


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

    # Clean JSON block for safety
    cleaned_json = extract_json_block(raw)

    # Return raw + cleaned version so route can decide
    return cleaned_json
