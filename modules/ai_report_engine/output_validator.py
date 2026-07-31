# modules/ai_report_engine/output_validator.py

"""
Centralized output validation for the AI Generation Pipeline. Every
concrete generator's output passes through this ONE validator inside
the Base AI Generator's fixed workflow -- a concrete generator has no
way to skip it, since `generate()` is not overridable (see
base_generator.py).

Deliberately generic: these checks apply to any segment/report_type and
know nothing about Love/Career/Finance/etc. Segment-specific validation
(e.g. "a Love DNA report must mention X") does not belong here and is
out of scope for this phase.
"""

from __future__ import annotations

import re

from modules.ai_report_engine.exceptions import OutputValidationError

# Generous, generic safety net against a runaway/looping generation --
# not a content-quality rule, purely a sanity bound.
_MAX_WORDS = 2000

# Catches literal, unresolved template placeholders (e.g. "{relationship_dna}")
# leaking into the final text -- a real defect class already seen in this
# project's prompt work this session (a template placeholder not being
# substituted, or the model echoing one back verbatim).
_PLACEHOLDER_PATTERN = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


class OutputValidator:
    def validate(self, text: str) -> str:
        """Returns the (possibly whitespace-trimmed) text if valid;
        raises OutputValidationError otherwise."""
        if text is None:
            raise OutputValidationError("AI output is None")

        cleaned = text.strip()

        if not cleaned:
            raise OutputValidationError("AI output is empty")

        if len(cleaned.split()) > _MAX_WORDS:
            raise OutputValidationError(
                f"AI output exceeds the generic safety limit of {_MAX_WORDS} words"
            )

        placeholder_match = _PLACEHOLDER_PATTERN.search(cleaned)
        if placeholder_match:
            raise OutputValidationError(
                f"AI output contains an unresolved placeholder-like token: "
                f"{placeholder_match.group(0)!r}"
            )

        return cleaned
