# modules/services/chat_requirement_engine.py

import os
import json
from openai import OpenAI

print("🔥 chat_requirement_engine imported")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_required_data(question: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Extract EXACT astrological data required for the user's question."
            },
            {
                "role": "user",
                "content": question
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

    # Here output is ALWAYS VALID JSON (100% guaranteed)
    raw = response.choices[0].message.content
    return json.loads(raw)
