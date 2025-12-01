# modules/services/chat_requirement_engine.py

import os
import json
from openai import OpenAI

print("🔥 chat_requirement_engine imported")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_required_data(question: str):
    """
    Extract ONLY birth-chart / dasha / transit based requirements.
    Never ask for DOB/TOB/POB because kundali is generated internally.
    JSON schema ensures output is ALWAYS valid.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a Vedic astrologer. "
                    "Your task is to list which ASTROLOGICAL DETAILS "
                    "from the birth chart, dasha or transit are needed "
                    "to answer the user's question. "
                    "Do NOT ask for DOB, TOB or POB. "
                    "Only provide astrological parameters like lagna, moon_sign, "
                    "planet_positions, house_strength, aspects, yogas, "
                    "dasha_summary, transit_planets, current_transit etc. "
                    "Keep list relevant and short."
                )
            },
            {
                "role": "user",
                "content": f"User question: \"{question}\"\n\nList the required astrological combinations only."
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

    # Schema ensures ALWAYS VALID JSON
    raw = response.choices[0].message.content
    return json.loads(raw)
