# modules/ai_report_engine/response_builder.py

"""
Turns a validated AI text output into the existing `GeneratedReport`
object already used by the Lifecycle Manager (Phase 2) -- no new
response model is introduced here, per instruction.

The wrapping shape (`{"content": text}`) deliberately mirrors the AI
Prediction Lab's own report envelope pattern
(`services/ai_prediction_lab/report_response.py`'s `sections.<key>.content`),
so a future consumer of `ai_reports.content_json` sees the same shape it
would from the Lab.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from modules.ai_report_engine.generator_interface import GeneratedReport


class ResponseBuilder:
    def build(
        self,
        *,
        text: str,
        model_version: Optional[str],
        prompt_version: Optional[str],
        generator_version: Optional[str],
        expires_at: Optional[datetime],
    ) -> GeneratedReport:
        content_json: Dict[str, Any] = {"content": text}

        return GeneratedReport(
            content_json=content_json,
            expires_at=expires_at,
            model_version=model_version,
            prompt_version=prompt_version,
            generator_version=generator_version,
        )
