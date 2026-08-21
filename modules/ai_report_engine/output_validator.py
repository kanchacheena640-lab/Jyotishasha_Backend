# modules/ai_report_engine/output_validator.py

"""
Centralized output validation for the AI Generation Pipeline. Every
concrete generator's output passes through this ONE validator inside
the Base AI Generator's fixed workflow -- a concrete generator has no
way to skip it, since `generate()` is not overridable (see
base_generator.py). On failure, `OutputValidationError` propagates out
of `generate()`, is caught by `ReportLifecycleManager.get_report()`,
which marks the existing cache row FAILED (or leaves a missing row
absent) and re-raises -- content that fails this validator is NEVER
persisted as READY. See lifecycle_manager.py's `get_report()`.

Deliberately generic: these checks apply to any segment/report_type and
know nothing about Love/Career/Finance/etc content itself. Segment-
specific *content quality* (e.g. "a Love DNA report must mention X") is
out of scope here. What IS in scope, added by the P0 fix below, is
structure/format/language sanity that is explicitly, verifiably part of
every report type's own prompt contract (see
services/ai_prediction_lab/prompts/*.txt) -- never invented beyond it.

P0 FIX -- AI drafting/meta text leaking into persisted output
---------------------------------------------------------------
Root cause (proven by audit): the model occasionally emits its own
internal drafting/self-correction commentary (planning what to write,
word-count bookkeeping, discussing the language/format requirements,
announcing a "corrected"/"final" answer, evaluating its own draft)
inside the normal message content returned by the OpenAI call. Every
Prediction Lab prompt (see e.g. love_profile_v1.txt, career_profile_v1.txt)
explicitly asks the model to run a "FINAL QUALITY CHECK (INTERNAL --
DO NOT OUTPUT)" self-review step before answering -- this validator
exists because the model does not always honor "DO NOT OUTPUT" for
that step. The three checks below (meta-leak detection, structural
validation, Hindi sanity) are the smallest safe boundary that catches
this class of corruption before it reaches the cache.
"""

from __future__ import annotations

import re
from typing import Optional

from modules.ai_report_engine.exceptions import OutputValidationError

# Generous, generic safety net against a runaway/looping generation --
# not a content-quality rule, purely a sanity bound.
_MAX_WORDS = 2000

# Catches literal, unresolved template placeholders (e.g. "{relationship_dna}")
# leaking into the final text -- a real defect class already seen in this
# project's prompt work this session (a template placeholder not being
# substituted, or the model echoing one back verbatim).
_PLACEHOLDER_PATTERN = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


# ==================================================================
# A. META/DRAFTING LEAK DETECTION
# ==================================================================
#
# Every pattern below targets vocabulary about the ACT OF WRITING/
# FOLLOWING-INSTRUCTIONS itself -- something no legitimate report ever
# contains, because every prompt in services/ai_prediction_lab/prompts/
# explicitly forbids the model from explaining its reasoning, referring
# to "the format"/"the instructions", or writing in the first person
# about its own task ("Do not explain your reasoning.", "Do not mention
# these instructions.", the person -- never the model -- is always the
# grammatical subject). This is deliberately generic (categories, not
# the literal screenshot phrases) while staying narrow enough that
# ordinary astrology prose -- which is always second-person ("you"),
# concrete, and about the reader's life -- cannot plausibly match it.
_META_LEAK_PATTERNS = [
    # 1) Model planning/narrating what it is about to do, in its own
    #    voice ("I will now write...", "Let me provide...", "Let's
    #    correct...", "I need to revise..."). Legitimate output is
    #    never first-person (or first-person-plural "let's") about the
    #    writing task -- it is always about the reader ("you"). "let's"/
    #    "let us" added (P0 follow-up -- proven gap: row-68's exact
    #    "Let's provide final corrected." used the contraction, which
    #    the original "let me" alternative did not cover).
    (
        "task_planning_narration",
        re.compile(
            r"\b(i will|i'll|i am going to|i'm going to|let me|let's|let us|"
            r"i need to|i should now|i must now)\s+(now\s+)?"
            r"(write|provide|give|generate|produce|create|draft|compose|"
            r"revise|correct|rewrite|ensure|check|verify|count|re-?write)\b",
            re.IGNORECASE,
        ),
    ),
    # 2) Word-count bookkeeping -- a report never talks about its own
    #    word count; the prompts enforce length as an internal
    #    constraint, never a visible statement. Range/imperative forms
    #    added (P0 follow-up -- proven gap: row-68's exact "Ensure
    #    40-60 words. Count 51." used a bare number-range and a bare
    #    "Count <N>" imperative, neither of which "word count"/"X/Y
    #    words" covered). "count <digit>" is safe/narrow: legitimate
    #    prose essentially never follows "count" directly with a
    #    number.
    (
        "word_count_bookkeeping",
        re.compile(
            r"\b(word count|words? so far|total words?|word limit|"
            r"within the word|exceeds? the word|count(?:ing)? the words?|"
            r"\d+\s*/\s*\d+\s*words|approximately \d+ words|"
            r"ensure\s+\d+[\s\-–]+\d+\s*words?|count\s+\d+)\b",
            re.IGNORECASE,
        ),
    ),
    # 3) Discussing language requirements as a meta topic (referring to
    #    "the language instruction/requirement" itself, rather than
    #    simply writing in that language). Terse self-instruction form
    #    added (P0 follow-up -- proven gap: row-68's exact "Need Hindi
    #    only." is a bare imperative note that no existing alternative
    #    covered).
    (
        "language_requirement_discussion",
        re.compile(
            r"\b(the language (requirement|instruction)s?|"
            r"as (per|instructed|required) (by |in )?the (prompt|instructions?)|"
            r"(write|written) (this |the )?(response |answer )?in (hindi|english)"
            r"(,| as| per)? as (required|instructed|requested)|"
            r"need\s+(hindi|english)\s+only)\b",
            re.IGNORECASE,
        ),
    ),
    # 4) Discussing formatting/structure requirements as a meta topic.
    #    "no forbidden X" and "<N> paragraphs exactly" added (P0
    #    follow-up -- proven gap: row-68's exact "No forbidden
    #    markdown. Five paragraphs exactly." matched neither the
    #    existing "no markdown is used" phrasing nor any paragraph-
    #    count self-statement). Both are narrow/safe: legitimate prose
    #    never states its own paragraph count or calls something
    #    "forbidden".
    (
        "formatting_requirement_discussion",
        re.compile(
            r"\b(no markdown (is )?(used|needed|required)|without (using )?markdown|"
            r"following the (output )?format|as (specified|required) in the format|"
            r"the output format (requires|specifies)|"
            r"(plain text only|in plain text format)\s*[:\-]|"
            r"no forbidden \w+|"
            r"(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
            r"paragraphs?\s+exactly)\b",
            re.IGNORECASE,
        ),
    ),
    # 5) Announcing that it will now provide/has corrected the answer
    #    ("Here is the corrected version", "Providing the final
    #    answer") -- a report never introduces itself this way, it
    #    simply begins its content.
    (
        "announcing_corrected_or_final_answer",
        re.compile(
            r"\b(here is the (corrected|final|revised|updated) "
            r"(version|answer|response|text|output)|"
            r"(let me|i will) (provide|give) the (final|corrected|revised) "
            r"(answer|response|version)|"
            r"providing the (final|corrected|revised) (answer|response))\b",
            re.IGNORECASE,
        ),
    ),
    # 6) Evaluating its own draft ("this draft", "my draft", "reviewing
    #    my response", "does this fulfill the requirements") --
    #    matches the exact self-review vocabulary the "FINAL QUALITY
    #    CHECK (INTERNAL -- DO NOT OUTPUT)" section of every prompt
    #    asks the model to perform SILENTLY.
    (
        "self_evaluating_draft",
        re.compile(
            r"\b(this draft|my draft|the draft (above|below)|"
            r"revie?wing my (answer|response|draft)|"
            r"let me (verify|double-check|review) (this|my)|"
            r"does this (fulfill|meet|satisfy) the requirements?|"
            r"final quality check)\b",
            re.IGNORECASE,
        ),
    ),
    # 7) Explicit AI self-reference -- near-zero false-positive risk:
    #    every prompt requires the person, never the model, to be the
    #    subject, and forbids sounding like "an AI describing a
    #    person".
    (
        "explicit_ai_self_reference",
        re.compile(
            r"\b(as an ai( language model)?|i('m| am) an ai|"
            r"as a language model)\b",
            re.IGNORECASE,
        ),
    ),
]


def _detect_meta_leak(text: str) -> Optional[str]:
    """Returns a human-readable failure reason if `text` contains
    unmistakable model drafting/meta commentary, else None."""
    for _label, pattern in _META_LEAK_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"meta/drafting leak detected ({_label}): {match.group(0)!r}"
    return None


# ==================================================================
# B. STRUCTURAL VALIDATION
# ==================================================================
#
# Only enforces structure explicitly, verbatim proven by the actual
# prompt contracts in services/ai_prediction_lab/prompts/ (audited
# across all five segments -- Love, Career, Finance, Health, Family --
# before writing these checks; see this phase's implementation report
# for the exact grep evidence). Nothing here is a guess.

# CURRENT_PHASE: every segment's current_*_phase_v1.txt prompt requires
# EXACTLY these four Markdown headings, verbatim, in this order, in
# English regardless of report language (an explicit "STRUCTURAL
# MARKER... exempt from the language instruction" in every one of
# those prompts). Confirmed identical across love/career/finance/
# health/family templates.
_CURRENT_PHASE_HEADINGS = [
    "## Current Phase",
    "## Next Phase Change",
    "## Watch Out For",
    "## Remedy For This Phase",
]

# CURRENT_TIMING: every segment's current_*_timing_v1.txt prompt
# requires this exact literal delimiter (also an explicit "STRUCTURAL
# MARKER... exempt from the language instruction"). Confirmed
# identical across all five segments.
_QUICK_TIP_MARKER = "Quick Tip:"

# DNA and DAILY_INSIGHT: every segment's *_profile_v1.txt /
# *_action_guidance_v1.txt / daily_love_prediction_v1.txt prompt
# explicitly forbids ANY Markdown or heading of any kind ("Do NOT use
# any Markdown or formatting characters... No heading of any kind,
# anywhere in the output."). Confirmed identical across all five
# segments for both report types.
_MARKDOWN_MARKER_PATTERN = re.compile(
    r"(^#{1,6}\s|\*\*|__|`{1,3}|^>\s|^-{3,}$|^\s*[-*]\s|^\s*\d+\.\s)",
    re.MULTILINE,
)

# DAILY_INSIGHT: every segment's prompt states "Maximum 100 words. This
# is a hard limit, not a guideline -- the response must never exceed
# 100 words under any circumstance." A generous buffer is used here
# (not a stricter number than the prompt specifies -- looser, to avoid
# rejecting a borderline-legitimate response) purely to catch GROSS
# violations (corrupted output tends to be far longer, not marginally
# longer).
_DAILY_INSIGHT_WORD_CEILING = 150


def _detect_structural_violation(text: str, report_type: Optional[str]) -> Optional[str]:
    if report_type == "CURRENT_PHASE":
        missing = [h for h in _CURRENT_PHASE_HEADINGS if h not in text]
        if missing:
            return f"CURRENT_PHASE is missing required heading(s): {missing}"
        # Order check: each heading must appear strictly after the previous one.
        positions = [text.index(h) for h in _CURRENT_PHASE_HEADINGS]
        if positions != sorted(positions):
            return "CURRENT_PHASE headings are present but out of the required order"
        return None

    if report_type == "CURRENT_TIMING":
        if _QUICK_TIP_MARKER not in text:
            return f"CURRENT_TIMING is missing the required {_QUICK_TIP_MARKER!r} marker"
        return None

    if report_type in ("DNA", "DAILY_INSIGHT"):
        markdown_match = _MARKDOWN_MARKER_PATTERN.search(text)
        if markdown_match:
            return (
                f"{report_type} contains a Markdown/heading marker that its prompt "
                f"contract forbids: {markdown_match.group(0)!r}"
            )
        if report_type == "DAILY_INSIGHT" and len(text.split()) > _DAILY_INSIGHT_WORD_CEILING:
            return (
                f"DAILY_INSIGHT exceeds the generous {_DAILY_INSIGHT_WORD_CEILING}-word "
                f"sanity ceiling (prompt's own hard limit is 100 words)"
            )
        return None

    # Unknown/unspecified report_type -- no structural contract proven
    # for it here, so no structural check is enforced (never invent one).
    return None


# ==================================================================
# C. HINDI LANGUAGE SANITY
# ==================================================================
#
# Conservative on purpose (per the prompts' own Hindi instruction: "Do
# not use any English sentence or phrase anywhere in the response
# (except a proper noun that has no Hindi form)."). We do NOT attempt
# real language detection. We only look for a long, unbroken RUN of
# consecutive Latin-script words -- something that only happens when
# actual English prose (a leaked draft, a leaked instruction) is
# present, never from an isolated proper noun, a number, an
# abbreviation, or an occasional loanword sitting inside otherwise
# Devanagari text.
_DEVANAGARI_PATTERN = re.compile(r"[ऀ-ॿ]")
_LATIN_WORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'\-]*$")

# A run this long can only be an actual English sentence/clause, never
# a stray term -- generous on purpose to avoid any false positive on
# legitimate astrology terminology, proper nouns, or a short loanword.
_HINDI_LATIN_RUN_THRESHOLD = 8


def _longest_latin_run(text: str) -> int:
    longest = 0
    current = 0
    for raw_token in text.split():
        token = raw_token.strip(".,!?;:()\"'“”‘’")
        if not token:
            continue
        if _DEVANAGARI_PATTERN.search(token):
            current = 0  # back to Devanagari -- run broken
            continue
        if _LATIN_WORD_PATTERN.match(token):
            current += 1
            longest = max(longest, current)
            continue
        # Numbers, punctuation-only, mixed-script tokens: neutral --
        # neither extends nor resets the run (e.g. a date or a number
        # sitting between two Devanagari words must not be misread as
        # part of an English run).
    return longest


def _detect_hindi_sanity_violation(text: str, language: Optional[str]) -> Optional[str]:
    if language != "hi":
        return None
    run_length = _longest_latin_run(text)
    if run_length >= _HINDI_LATIN_RUN_THRESHOLD:
        return (
            f"Hindi-language report contains a run of {run_length} consecutive "
            f"Latin-script words -- looks like English prose leaked into a "
            f"Hindi-only report (threshold: {_HINDI_LATIN_RUN_THRESHOLD})"
        )
    return None


class OutputValidator:
    def validate(
        self,
        text: str,
        *,
        report_type: Optional[str] = None,
        language: Optional[str] = None,
    ) -> str:
        """Returns the (possibly whitespace-trimmed) text if valid;
        raises OutputValidationError otherwise.

        `report_type` and `language` are optional so existing/future
        callers that don't have them can still get the original
        generic checks -- the new P0 checks (structural, Hindi sanity)
        simply no-op when their inputs aren't supplied. The meta-leak
        check (A) always runs regardless, since it needs neither.
        """
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

        meta_leak_reason = _detect_meta_leak(cleaned)
        if meta_leak_reason:
            raise OutputValidationError(f"AI output failed validation: {meta_leak_reason}")

        structural_reason = _detect_structural_violation(cleaned, report_type)
        if structural_reason:
            raise OutputValidationError(f"AI output failed validation: {structural_reason}")

        hindi_reason = _detect_hindi_sanity_violation(cleaned, language)
        if hindi_reason:
            raise OutputValidationError(f"AI output failed validation: {hindi_reason}")

        return cleaned
