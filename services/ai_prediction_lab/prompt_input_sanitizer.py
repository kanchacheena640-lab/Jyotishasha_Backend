# services/ai_prediction_lab/prompt_input_sanitizer.py

"""
Prompt Input Sanitizer -- defensive hardening only.

Free-text profile fields (birth place, and any similar user-entered
text) reach the CURRENT_PHASE-layer prompt builders
(current_love_phase_prompt_builder.py, current_career_phase_prompt_builder.py,
current_finance_phase_prompt_builder.py, current_health_phase_prompt_builder.py,
current_family_phase_prompt_builder.py) as plain strings, sourced from a
free-text database column with no format guarantee beyond "some text a
user or an external place-lookup entered". This module gives each of
those call sites one small, shared, pure function to run that text
through immediately before it enters the `values` dict a prompt
template is `.format()`-ed with -- nothing else in this package changes.

This is NOT a general-purpose prompt-injection framework and does not
attempt to understand or block "instructions" semantically -- it only
does the four concrete things asked of it:
  - normalize whitespace (any run of whitespace, including newlines/
    tabs, collapses to a single space, so a value can never introduce a
    new line into a prompt that wasn't there before)
  - remove control characters
  - enforce a maximum length
  - strip repeated `=`/`#`/backtick sequences -- the exact characters
    every prompt template in this package already uses as its own
    section-divider convention (e.g. "=================================================="
    and "SECTION NAME" headers), so an inserted value can't visually
    impersonate a new section boundary

For ordinary, legitimate input (a real place name, a real date/time
string) none of these ever fire -- the function returns the input
unchanged. It is not a translation, rewrite, or content-quality check
of any kind.
"""

from __future__ import annotations

import re

# ASCII control characters, excluding none -- all whitespace variants
# among them (tab, newline, etc.) are separately normalized by
# _WHITESPACE_RE below, so stripping them here first is harmless and
# keeps this pass simple: "any C0 control byte or DEL is never valid
# inside a person's place/date/time text".
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

_WHITESPACE_RE = re.compile(r"\s+")

# The specific characters this project's own prompt templates use as
# structural dividers (see e.g. services/ai_prediction_lab/prompts/*.txt's
# "==================================================" section rules),
# plus the two other characters commonly read as document structure
# (Markdown headings/code fences) regardless of template. Deliberately
# narrow -- ordinary punctuation a real place name might contain (a
# single hyphen, an apostrophe) is left untouched; only RUNS of 2+ of
# these specific characters are collapsed, which legitimate place/date/
# time text never naturally contains. Collapsing them to a single space
# stops an inserted value from visually mimicking a new section.
_STRUCTURAL_MARKER_RE = re.compile(r"[=#`]{2,}")

# AppUser.pob (and every other free-text profile column this reaches)
# is itself capped at 200 characters at the database level -- this cap
# is enforced here too, independently, as defense in depth rather than
# assuming the DB constraint alone is sufficient.
DEFAULT_MAX_LENGTH = 200


def sanitize_prompt_text(
    value: object,
    *,
    max_length: int = DEFAULT_MAX_LENGTH,
    fallback: str = "Not specified",
) -> str:
    """Returns `value` cleaned for safe insertion into a prompt
    template's `values` dict, or `fallback` if `value` isn't usable
    text at all (None, empty, or entirely control/whitespace
    characters). Ordinary legitimate text is returned unchanged except
    for trimming to `max_length`."""
    if not isinstance(value, str) or not value:
        return fallback

    cleaned = _CONTROL_CHARS_RE.sub("", value)
    cleaned = _STRUCTURAL_MARKER_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()

    if not cleaned:
        return fallback

    return cleaned[:max_length]
