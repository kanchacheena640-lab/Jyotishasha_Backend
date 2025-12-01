# modules/services/chat_requirement_engine.py

import os
import json
from openai import OpenAI

print("🔥 chat_requirement_engine imported")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_required_data(question: str):
    """
    Extract ASTROLOGICAL requirements (house, lord, yogas, dasha, transit)
    based on the user's specific question.
    """

    SYSTEM_PROMPT = (
        "You are a senior Vedic astrologer with decades of experience. "
        "Your job is to read the user’s question carefully and identify EXACTLY which "
        "planetary factors, house analysis, yogas, dasha elements, and transit influences "
        "you would examine in a real birth chart to answer that specific question accurately.\n\n"

        "Guidelines:\n"
        "- Think like a real astrologer, not a generic AI.\n"
        "- Consider the intention behind the question (marriage, love, breakup, reconciliation, "
        "career, job timing, finance, health, childbirth, travel, emotions, spiritual progress, etc.)\n"
        "- Identify the specific birth-chart details needed for THIS question only.\n"
        "- Identify necessary Mahadasha/Antardasha factors.\n"
        "- Identify relevant transit checks.\n"
        "- Identify important yogas, strengths, aspects, house lords.\n"
        "- DO NOT ask for DOB/TOB/POB — we already generate the chart.\n"
        "- Only list what YOU (as an astrologer) would check.\n"
        "- Keep the list concise, relevant, and question-specific.\n\n"

        "Output must strictly follow:\n"
        "{\n"
        "  \"required_data\": [\"detail_1\", \"detail_2\", \"detail_3\"]\n"
        "}\n"
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": f"User question: \"{question}\". List the required astrological combinations only."
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "requirements_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "required_data": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["required_data"],
                    "additionalProperties": False
                }
            }
        },
        temperature=0
    )

    raw = response.choices[0].message.content
    return json.loads(raw)
