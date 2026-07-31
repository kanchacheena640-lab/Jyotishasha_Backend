# modules/ai_report_engine/openai_executor.py

"""
Thin, reusable wrapper around the AI Prediction Lab's existing OpenAI
client -- this is the ONLY place in the AI Generation Pipeline that
calls OpenAI. It does NOT construct a client, pick a model, or
duplicate any of that logic; it delegates entirely to
`services.ai_prediction_lab.openai_client.generate_with_raw()`, which
already owns client construction/model selection (see that module).

Every future generator (Love, Career, Finance, Health, Family, Alerts)
goes through this one executor, so there is exactly one OpenAI call
site for the whole Premium AI Report Engine.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from services.ai_prediction_lab import openai_client

from modules.ai_report_engine.exceptions import OpenAICallError


class OpenAIExecutor:
    def run(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        """
        Returns (text, raw_openai_response). `raw_openai_response` is the
        full API response dict (from `generate_with_raw`), which already
        contains OpenAI's own `model` field -- used by the Base AI
        Generator to record `model_version` without this pipeline having
        to know or duplicate which model string the Lab client uses.
        """
        try:
            return openai_client.generate_with_raw(prompt)
        except Exception as exc:
            raise OpenAICallError("OpenAI call failed") from exc
