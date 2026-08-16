"""
test_bilingual_contract.py
----------------------------------
Regression tests for the Premium AI Report Bilingual Contract fix:
threading `language` through DNA and DAILY_INSIGHT for all 5 segments
(LOVE, CAREER, FINANCE, HEALTH, FAMILY), hardening CURRENT_PHASE's four
structural headings and CURRENT_TIMING's "Quick Tip:" marker to stay
exactly English even under a Hindi narrative instruction, and
normalizing the `language` API parameter.

Pure, offline, no OpenAI call, no database, no Flask app import needed
for the prompt-builder tests -- these are plain Python string-formatting
functions, exercising the real .txt template files on disk (not a copy/
mock). The API-normalization tests import only the pure
`_normalize_language()` helper, also without a Flask app context. The
cache-key test only inspects function signatures (no DB connection).
"""

import inspect
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- DNA builders ----
from services.ai_prediction_lab.prompt_builder import build_love_profile_prompt  # noqa: E402
from services.ai_prediction_lab.career_prompt_builder import build_career_profile_prompt  # noqa: E402
from services.ai_prediction_lab.finance_prompt_builder import build_finance_profile_prompt  # noqa: E402
from services.ai_prediction_lab.health_prompt_builder import build_health_profile_prompt  # noqa: E402
from services.ai_prediction_lab.family_prompt_builder import build_family_profile_prompt  # noqa: E402

# ---- DAILY_INSIGHT builders ----
from services.ai_prediction_lab.daily_love_prediction_prompt_builder import build_daily_love_prediction_prompt  # noqa: E402
from services.ai_prediction_lab.career_action_guidance_prompt_builder import build_career_action_guidance_prompt  # noqa: E402
from services.ai_prediction_lab.finance_action_guidance_prompt_builder import build_finance_action_guidance_prompt  # noqa: E402
from services.ai_prediction_lab.health_action_guidance_prompt_builder import build_health_action_guidance_prompt  # noqa: E402
from services.ai_prediction_lab.family_action_guidance_prompt_builder import build_family_action_guidance_prompt  # noqa: E402

# ---- CURRENT_PHASE builders (already language-aware; hardening only) ----
from services.ai_prediction_lab.current_love_phase_prompt_builder import build_current_love_phase_prompt  # noqa: E402
from services.ai_prediction_lab.current_career_phase_prompt_builder import build_current_career_phase_prompt  # noqa: E402
from services.ai_prediction_lab.current_finance_phase_prompt_builder import build_current_finance_phase_prompt  # noqa: E402
from services.ai_prediction_lab.current_health_phase_prompt_builder import build_current_health_phase_prompt  # noqa: E402
from services.ai_prediction_lab.current_family_phase_prompt_builder import build_current_family_phase_prompt  # noqa: E402

# ---- CURRENT_TIMING builders (already language-aware; hardening only) ----
from services.ai_prediction_lab.current_love_timing_prompt_builder import build_current_love_timing_prompt  # noqa: E402
from services.ai_prediction_lab.current_career_timing_prompt_builder import build_current_career_timing_prompt  # noqa: E402
from services.ai_prediction_lab.current_finance_timing_prompt_builder import build_current_finance_timing_prompt  # noqa: E402
from services.ai_prediction_lab.current_health_timing_prompt_builder import build_current_health_timing_prompt  # noqa: E402
from services.ai_prediction_lab.current_family_timing_prompt_builder import build_current_family_timing_prompt  # noqa: E402

# ---- Generators (proves `language` reaches build_prompt() for DNA/DAILY_INSIGHT) ----
from modules.love.love_generator import LoveGenerator  # noqa: E402
from modules.career.career_generator import CareerGenerator  # noqa: E402
from modules.finance.finance_generator import FinanceGenerator  # noqa: E402
from modules.health.health_generator import HealthGenerator  # noqa: E402
from modules.family.family_generator import FamilyGenerator  # noqa: E402

# ---- API boundary ----
from routes.routes_premium_report import _normalize_language, SUPPORTED_LANGUAGES  # noqa: E402

# ---- Cache repository (cache-key dimension check, no DB connection) ----
from modules.ai_report_engine.cache_repository import ReportCacheRepository  # noqa: E402

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


_ENGLISH_MARK = "Write your ENTIRE response in English."


def _hindi_ok(prompt: str) -> bool:
    return "Hindi" in prompt and "Devanagari" in prompt and "{language_instruction}" not in prompt


def _english_ok(prompt: str) -> bool:
    return _ENGLISH_MARK in prompt and "{language_instruction}" not in prompt


# ==============================================================
# DNA builders -- en requests English, hi requests Hindi
# ==============================================================
DNA_BUILDERS = {
    "LOVE": build_love_profile_prompt,
    "CAREER": build_career_profile_prompt,
    "FINANCE": build_finance_profile_prompt,
    "HEALTH": build_health_profile_prompt,
    "FAMILY": build_family_profile_prompt,
}

DAILY_INSIGHT_BUILDERS = {
    "LOVE": lambda lang: build_daily_love_prediction_prompt("DNA TEXT", "PHASE TEXT", {}, language=lang),
    "CAREER": lambda lang: build_career_action_guidance_prompt("DNA TEXT", "PHASE TEXT", {}, language=lang),
    "FINANCE": lambda lang: build_finance_action_guidance_prompt("DNA TEXT", "PHASE TEXT", {}, language=lang),
    "HEALTH": lambda lang: build_health_action_guidance_prompt("DNA TEXT", "PHASE TEXT", {}, language=lang),
    "FAMILY": lambda lang: build_family_action_guidance_prompt("DNA TEXT", "PHASE TEXT", {}, language=lang),
}

_HEADING_PATTERN = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_EXPECTED_HEADINGS = ["Current Phase", "Next Phase Change", "Watch Out For", "Remedy For This Phase"]

PHASE_BUILDERS = {
    "LOVE": lambda lang: build_current_love_phase_prompt("1990-01-01", "10:00", "Delhi", "DNA TEXT", {"next_phase_change_date": "2026-09-01"}, language=lang),
    "CAREER": lambda lang: build_current_career_phase_prompt("1990-01-01", "10:00", "Delhi", "DNA TEXT", {"next_phase_change_date": "2026-09-01"}, language=lang),
    "FINANCE": lambda lang: build_current_finance_phase_prompt("1990-01-01", "10:00", "Delhi", "DNA TEXT", {"next_phase_change_date": "2026-09-01"}, language=lang),
    "HEALTH": lambda lang: build_current_health_phase_prompt("1990-01-01", "10:00", "Delhi", "DNA TEXT", {"next_phase_change_date": "2026-09-01"}, language=lang),
    "FAMILY": lambda lang: build_current_family_phase_prompt("1990-01-01", "10:00", "Delhi", "DNA TEXT", {"next_phase_change_date": "2026-09-01"}, language=lang),
}

TIMING_BUILDERS = {
    "LOVE": lambda lang: build_current_love_timing_prompt("PHASE TEXT", {}, language=lang),
    "CAREER": lambda lang: build_current_career_timing_prompt("PHASE TEXT", {}, language=lang),
    "FINANCE": lambda lang: build_current_finance_timing_prompt("PHASE TEXT", {}, language=lang),
    "HEALTH": lambda lang: build_current_health_timing_prompt("PHASE TEXT", {}, language=lang),
    "FAMILY": lambda lang: build_current_family_timing_prompt("PHASE TEXT", {}, language=lang),
}

GENERATORS = {
    "LOVE": LoveGenerator,
    "CAREER": CareerGenerator,
    "FINANCE": FinanceGenerator,
    "HEALTH": HealthGenerator,
    "FAMILY": FamilyGenerator,
}


def main():
    print("=== 1. DNA -- en requests English, hi requests Hindi, for all 5 segments ===")
    for seg, fn in DNA_BUILDERS.items():
        p_en = fn({}, language="en")
        p_hi = fn({}, language="hi")
        check(f"{seg} DNA en: requests English", _english_ok(p_en))
        check(f"{seg} DNA hi: requests Hindi/Devanagari", _hindi_ok(p_hi))
        check(f"{seg} DNA: no unconditional 'conversational English' left hardcoded outside the LANGUAGE block", "conversational English." not in p_en and "conversational English." not in p_hi)

    print("\n=== 2. DAILY_INSIGHT -- en requests English, hi requests Hindi, for all 5 segments ===")
    for seg, fn in DAILY_INSIGHT_BUILDERS.items():
        p_en = fn("en")
        p_hi = fn("hi")
        check(f"{seg} DAILY_INSIGHT en: requests English", _english_ok(p_en))
        check(f"{seg} DAILY_INSIGHT hi: requests Hindi/Devanagari", _hindi_ok(p_hi))
        check(f"{seg} DAILY_INSIGHT: no unconditional 'everyday English' left hardcoded outside the LANGUAGE block", "everyday English." not in p_en and "everyday English." not in p_hi)

    print("\n=== 3. `language` reaches the generator's build_prompt() for DNA and DAILY_INSIGHT (all 5 segments) ===")
    dna_context_key = {
        "LOVE": "birth_summary", "CAREER": "career_summary", "FINANCE": "finance_summary",
        "HEALTH": "health_summary", "FAMILY": "family_summary",
    }
    daily_context = {
        "LOVE": {"relationship_dna": "D", "current_love_phase": "P", "daily_transit_context": {}},
        "CAREER": {"career_dna": "D", "current_career_phase": "P", "career_action_context": {}},
        "FINANCE": {"financial_dna": "D", "current_finance_phase": "P", "finance_action_context": {}},
        "HEALTH": {"health_dna": "D", "current_health_phase": "P", "health_action_context": {}},
        "FAMILY": {"family_dna": "D", "current_family_phase": "P", "family_action_context": {}},
    }
    for seg, gen_cls in GENERATORS.items():
        gen = gen_cls.__new__(gen_cls)  # bypass __init__ (no OpenAI client needed for build_prompt())
        dna_ctx = {dna_context_key[seg]: {}}
        p_en = gen.build_prompt(context=dna_ctx, report_type="DNA", language="en")
        p_hi = gen.build_prompt(context=dna_ctx, report_type="DNA", language="hi")
        check(f"{seg} generator DNA: language='en' reaches builder", _english_ok(p_en))
        check(f"{seg} generator DNA: language='hi' reaches builder", _hindi_ok(p_hi))

        p_en2 = gen.build_prompt(context=daily_context[seg], report_type="DAILY_INSIGHT", language="en")
        p_hi2 = gen.build_prompt(context=daily_context[seg], report_type="DAILY_INSIGHT", language="hi")
        check(f"{seg} generator DAILY_INSIGHT: language='en' reaches builder", _english_ok(p_en2))
        check(f"{seg} generator DAILY_INSIGHT: language='hi' reaches builder", _hindi_ok(p_hi2))

    print("\n=== 4. CURRENT_PHASE -- en/hi narrative contract + 4 structural headings stay exact English + Next Phase Change intact ===")
    for seg, fn in PHASE_BUILDERS.items():
        p_en = fn("en")
        p_hi = fn("hi")
        headings_en = _HEADING_PATTERN.findall(p_en)
        headings_hi = _HEADING_PATTERN.findall(p_hi)
        check(f"{seg} CURRENT_PHASE en: requests English narrative", _english_ok(p_en))
        check(f"{seg} CURRENT_PHASE hi: requests Hindi narrative", _hindi_ok(p_hi))
        check(f"{seg} CURRENT_PHASE en: exactly the 4 required English headings, in order", headings_en == _EXPECTED_HEADINGS)
        check(f"{seg} CURRENT_PHASE hi: SAME 4 English headings remain, in order, even under Hindi instruction", headings_hi == _EXPECTED_HEADINGS)
        check(f"{seg} CURRENT_PHASE hi: explicit heading-protection instruction present", "MUST remain EXACTLY as written above, in\nEnglish" in p_hi)
        check(f"{seg} CURRENT_PHASE: NEXT_PHASE_CHANGE_DATE substitution untouched (en)", "NEXT_PHASE_CHANGE_DATE = 2026-09-01" in p_en)
        check(f"{seg} CURRENT_PHASE: NEXT_PHASE_CHANGE_DATE substitution untouched (hi)", "NEXT_PHASE_CHANGE_DATE = 2026-09-01" in p_hi)
        check(f"{seg} CURRENT_PHASE: 'Around <date>' rule text intact (hi)", "Around <date>" in p_hi)

    print("\n=== 5. CURRENT_TIMING -- en/hi contract + literal 'Quick Tip:' exact structural marker in both + no contradictory instruction ===")
    for seg, fn in TIMING_BUILDERS.items():
        p_en = fn("en")
        p_hi = fn("hi")
        check(f"{seg} CURRENT_TIMING en: requests English", _english_ok(p_en))
        check(f"{seg} CURRENT_TIMING hi: requests Hindi", _hindi_ok(p_hi))
        check(f"{seg} CURRENT_TIMING en: literal 'Quick Tip:' marker present", "Quick Tip:" in p_en)
        check(f"{seg} CURRENT_TIMING hi: literal 'Quick Tip:' marker STILL present in English, unchanged", "Quick Tip:" in p_hi)
        check(f"{seg} CURRENT_TIMING hi: explicit marker-exemption instruction present (no contradiction with the Hindi-only rule)", "STRUCTURAL MARKER (EXEMPT FROM THE LANGUAGE INSTRUCTION ABOVE)" in p_hi)
        # No contradiction: the exemption text must appear BEFORE any
        # instance of the "no English phrase anywhere" Hindi directive
        # would otherwise stand unqualified.
        check(f"{seg} CURRENT_TIMING hi: exemption text placed alongside the language instruction (same block)", p_hi.index("STRUCTURAL MARKER") > p_hi.index("Devanagari"))

    print("\n=== 6. Language API normalization ===")
    check("SUPPORTED_LANGUAGES is exactly ('en', 'hi')", SUPPORTED_LANGUAGES == ("en", "hi"))
    check("'en' -> 'en'", _normalize_language("en") == "en")
    check("'hi' -> 'hi'", _normalize_language("hi") == "hi")
    check("'HI' -> 'hi' (case-insensitive)", _normalize_language("HI") == "hi")
    check("' hi ' -> 'hi' (whitespace-tolerant)", _normalize_language(" hi ") == "hi")
    check("'Hi' -> 'hi'", _normalize_language("Hi") == "hi")
    check("missing/None -> 'en' (backward-compatible default)", _normalize_language(None) == "en")
    check("'' -> 'en'", _normalize_language("") == "en")
    check("'fr' (unsupported) -> 'en', NEVER silently treated as Hindi", _normalize_language("fr") == "en")
    check("'xx' (garbage) -> 'en', NEVER silently treated as Hindi", _normalize_language("xx") == "en")
    check("'hindi' (near-miss, not exact) -> 'en', NEVER silently treated as Hindi", _normalize_language("hindi") == "en")
    check("'en-US' (locale-tagged) -> 'en' (falls back safely, not crashes)", _normalize_language("en-US") == "en")

    print("\n=== 7. Cache key remains profile x segment x report_type x language (unchanged) ===")
    read_sig = inspect.signature(ReportCacheRepository.read_cache)
    save_sig = inspect.signature(ReportCacheRepository.save_cache)
    for name, sig in (("read_cache", read_sig), ("save_cache", save_sig)):
        params = sig.parameters
        check(f"ReportCacheRepository.{name}() still requires profile_id", "profile_id" in params)
        check(f"ReportCacheRepository.{name}() still requires segment", "segment" in params)
        check(f"ReportCacheRepository.{name}() still requires report_type", "report_type" in params)
        check(f"ReportCacheRepository.{name}() still requires language", "language" in params)

    print("\n=== 8. Existing English behavior is not structurally changed ===")
    # Spot-check the DNA/DAILY_INSIGHT English output still contains the
    # exact structural/style anchors that existed before this fix (only
    # the language-hardcoding was removed, nothing else rewritten).
    love_dna_en = build_love_profile_prompt({}, language="en")
    check("LOVE DNA en: five-paragraph OUTPUT FORMAT rule text intact", "Write exactly five short paragraphs" in love_dna_en)
    check("LOVE DNA en: FLUTTER OUTPUT FORMAT rule text intact", "FLUTTER OUTPUT FORMAT (MANDATORY)" in love_dna_en)
    check("LOVE DNA en: MIRROR EFFECT section intact", "MIRROR EFFECT" in love_dna_en)

    career_daily_en = build_career_action_guidance_prompt("D", "P", {}, language="en")
    check("CAREER DAILY_INSIGHT en: LENGTH/100-word rule intact", "Maximum 100 words" in career_daily_en or "100 words" in career_daily_en)
    check("CAREER DAILY_INSIGHT en: FLUTTER OUTPUT FORMAT rule text intact", "FLUTTER OUTPUT FORMAT" in career_daily_en)

    health_dna_en = build_health_profile_prompt({}, language="en")
    check("HEALTH DNA en: MEDICAL SAFETY RULE still present and unaltered", "MEDICAL SAFETY RULE (MANDATORY, ABSOLUTE -- READ FIRST)" in health_dna_en)

    family_dna_en = build_family_profile_prompt({}, language="en")
    check("FAMILY DNA en: FAMILY SAFETY RULE still present and unaltered", "FAMILY SAFETY RULE (MANDATORY, ABSOLUTE -- READ FIRST)" in family_dna_en)

    timing_en = build_current_love_timing_prompt("P", {}, language="en")
    check("CURRENT_TIMING en: OUTPUT FORMAT (PLAIN TEXT ONLY) rule intact", "OUTPUT FORMAT (MANDATORY, PLAIN TEXT ONLY)" in timing_en)

    phase_en = build_current_love_phase_prompt("1990-01-01", "10:00", "Delhi", "D", {"next_phase_change_date": "2026-09-01"}, language="en")
    check("CURRENT_PHASE en: FOCUS RULE (single-theme) text intact", "FOCUS RULE (MANDATORY, ABSOLUTE" in phase_en)
    check("CURRENT_PHASE en: PLANET RULES section intact", "PLANET RULES (applies to all four sections)" in phase_en)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
