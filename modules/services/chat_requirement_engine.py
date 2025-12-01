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
                    "You are a senior Vedic astrologer. "
                    "Your job is to identify EXACT birth-chart, house-specific and planet-specific "
                    "factors needed to answer the user's question. "
                    "NEVER ask for DOB, TOB, or POB — we already generate the Kundali. "
                    "ONLY list astrological combinations relevant to the query type. "
                    "Marriage → 7th house, 7th lord, Venus, Jupiter aspects, marriage yogas, dasha & transit of 7th lord/Venus. "
                    "Career → 10th house, 10th lord, Sun, Saturn, 2nd/6th/11th, career yogas, dasha & transit on 10th. "
                    "Childbirth → 5th house, 5th lord, Jupiter, Moon, putra yogas, dasha & transit on 5th. "
                    "Finance → 2nd/11th house, their lords, Jupiter/Rahu effects, dhan yogas. "
                    "Health → 1st/6th/8th/12th houses, their lords, Mars/Saturn influence. "
                    "Output must be SPECIFIC astro factors — NOT generic items like lagna or moon sign unless needed. "
                    "Return concise, event-focused astro parameters only."
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
