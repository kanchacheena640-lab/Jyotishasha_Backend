"""
services/ai_prediction_lab/openai_client.py
----------------------------------------------
Isolated OpenAI client for the AI Prediction Lab ONLY.

This does not import from, share state with, or modify any production
OpenAI integration (report_writer.py, modules/love/love_premium_task.py,
modules/services/chat_engine.py, modules/services/chat_requirement_engine.py,
modules/smartchat/smartchat_engine.py, routes/routes_free_consult.py).
It mirrors their existing client-init pattern for consistency, but is a
separate client instance scoped to this package alone.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_MODEL = "gpt-5.6-luna"

# Models known NOT to support a custom `temperature` value. Confirmed
# directly against the live OpenAI API: gpt-5.6-luna rejects
# temperature=0.7 with a 400 "Unsupported value... Only the default (1)
# value is supported" error -- verified by a real call before this
# change was made, not assumed. Only listed models have `temperature`
# omitted (falling back to the API's own default); every other model
# keeps the exact 0.7 this file has always used.
_MODELS_WITHOUT_CUSTOM_TEMPERATURE = {"gpt-5.6-luna"}


def _call(prompt: str):
    kwargs = dict(
        model=_MODEL,
        messages=[
            {"role": "system", "content": "You are a senior Vedic astrologer."},
            {"role": "user", "content": prompt},
        ],
    )
    if _MODEL not in _MODELS_WITHOUT_CUSTOM_TEMPERATURE:
        kwargs["temperature"] = 0.7
    return _client.chat.completions.create(**kwargs)


def generate(prompt: str) -> str:
    """Send `prompt` to OpenAI and return only the assistant response text."""
    response = _call(prompt)
    return response.choices[0].message.content.strip()


def generate_with_raw(prompt: str):
    """
    Send `prompt` to OpenAI and return (text, raw_dict), where raw_dict is
    the full API response as a JSON-serializable dict -- for callers that
    need to persist the raw OpenAI response (e.g. raw_openai.json).
    """
    response = _call(prompt)
    text = response.choices[0].message.content.strip()
    raw_dict = response.model_dump()
    return text, raw_dict
