"""
services/ai_prediction_lab/report_response.py
-------------------------------------------------------------
Assembles the final Love Engine response envelope. This is a pure
assembly/formatting layer -- it does not generate, alter, or judge the
AI-written report content in any way; it only wraps the three already-
generated section texts (unchanged) together with stable identifiers,
the report_metadata.py footer metadata, and top-level response fields
(version, language, generated_at).

Backend never returns UI labels (e.g. "Relationship DNA") -- only the
stable `type` identifiers from report_metadata.SECTION_TYPES. The
frontend maps `type` -> localized label for the `language` requested.
`language` is currently pass-through only (no translation is performed
here); this exists so the response shape is already multilingual-ready
without a later breaking change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from services.ai_prediction_lab.report_metadata import SECTION_TYPES, build_report_metadata

RESPONSE_VERSION = "love_engine_v1"

# Languages the request shape supports today (no translation implemented
# yet -- see module docstring). Passing an unsupported code still works;
# this list exists only to document intent.
SUPPORTED_LANGUAGES = ["en", "hi", "mr", "ta", "te", "bn"]


def build_report_response(
    *,
    love_phase_context: Dict[str, Any],
    relationship_dna_text: str,
    current_love_phase_text: str,
    daily_love_insight_text: str,
    language: str = "en",
) -> Dict[str, Any]:
    """
    Returns the full response envelope:
        {
          "version": "love_engine_v1",
          "language": "<requested language>",
          "generated_at": "<ISO 8601 UTC timestamp>",
          "sections": {
              "relationship_dna":   {type, stability, content},
              "current_love_phase": {type, stability, content},
              "daily_love_insight": {type, stability, content},
          },
          "metadata": { ...report_metadata.build_report_metadata()... }
        }

    `content` is the untouched AI-generated text for that section --
    identical to what was already being produced and saved to
    response.txt / love_phase_response.txt / daily_love_prediction_response.txt.
    """
    metadata = build_report_metadata(love_phase_context)

    section_texts = {
        "relationship_dna": relationship_dna_text,
        "current_love_phase": current_love_phase_text,
        "daily_love_insight": daily_love_insight_text,
    }

    sections = {
        key: {
            **SECTION_TYPES[key],
            "content": section_texts[key],
        }
        for key in SECTION_TYPES
    }

    return {
        "version": RESPONSE_VERSION,
        "language": language,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "metadata": metadata,
    }
