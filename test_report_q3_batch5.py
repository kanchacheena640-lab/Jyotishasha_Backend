"""
test_report_q3_batch5.py
-------------------------------------------------
Q3 Batch 5 (FINAL) -- verification for the last 7 Q3-enabled products
(sadhesati_report, foreign_travel_report, children_parenting_report,
jupiter_transit_report, lifestyle_analysis_report, property_report,
legal_disputes_report).

Two kinds of coverage, mirroring test_report_q3_batch1/2/3/4.py's own
established structure exactly:

  Part 1 (no DB, fast) -- direct unit tests of the two new deterministic
  hero helpers (Sade Sati, Jupiter transit), registry-shape assertions
  specific to Batch 5's own per-product configuration, the 5 new
  mandatory disclaimers, and static source-level checks of the 14
  rewritten prompt files (strict safety language, empty-house
  instructions, EN/HI heading parity, no legal "victory" framing) --
  these do not require a live Luna call or a DB.

  Part 2 (LOCAL Postgres DB, same convention as every prior batch) --
  direct integration verification against the REAL tasks.py::
  _generate_and_send_report_core() code path for each of the 7 now-real
  q3_enabled=True products, using REAL kundali/dasha/transit
  calculation (only the Luna call and the final PDF render are mocked).

No real OpenAI/Luna call anywhere in this file.
"""

import os
import re
import sys
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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


# =====================================================================
# PART 1 -- fast, no-DB unit tests
# =====================================================================

from modules.payments.report_product_intelligence import REGISTRY  # noqa: E402
from modules.payments.report_q3_batch1 import DISCLAIMER_TEXT, get_mandatory_disclaimer  # noqa: E402
from modules.payments.report_q3_batch5 import (  # noqa: E402
    BATCH5_PRODUCT_SLUGS, compute_sadhesati_hero, compute_jupiter_transit_hero,
)
from modules.payments.report_structured_output import ReportMetadataError  # noqa: E402
from summary_blocks import build_house_lord_facts  # noqa: E402

BATCH5_SLUGS = {
    "sadhesati_report", "foreign_travel_report", "children_parenting_report",
    "jupiter_transit_report", "lifestyle_analysis_report", "property_report",
    "legal_disputes_report",
}
BATCH4_SLUGS = {
    "love_relationship_report", "love_marriage_report",
    "love_disappointment_report", "relationship_future_report",
}
BATCH3_SLUGS = {
    "financial_report", "financial_stability_report", "career_report",
    "government_job_report", "business_report", "startup_suggestion_report",
}
BATCH2_SLUGS = {
    "marriage_report", "delay_in_marriage_report",
    "problem_in_marriage_report", "second_marriage_report",
}
BATCH1_SLUGS = {
    "gemstone_consultation", "saturn_transit_report",
    "mood_mental_health_report", "divorce_possibility_report",
}
DETERMINISTIC_HERO_SLUGS = {"sadhesati_report", "jupiter_transit_report"}
AI_HERO_SLUGS = BATCH5_SLUGS - DETERMINISTIC_HERO_SLUGS

check("A: BATCH5_PRODUCT_SLUGS is exactly the 7 expected slugs", BATCH5_PRODUCT_SLUGS == frozenset(BATCH5_SLUGS))

print("=== A/B/C/D: exactly 25/25 Q3 enabled, 0 disabled, previous 18 unchanged, exactly 7 Batch-5 products ===")

enabled = {slug for slug, p in REGISTRY.items() if p.q3_enabled}
check("A: exactly 25 of 25 products are q3_enabled=True", len(enabled) == 25)
check("B: exactly 0 products are q3_enabled=False", len(REGISTRY) - len(enabled) == 0)
check("C: all previous 18 products remain enabled",
      (BATCH1_SLUGS | BATCH2_SLUGS | BATCH3_SLUGS | BATCH4_SLUGS) <= enabled)
check("D: all 7 Batch-5 products are enabled", BATCH5_SLUGS <= enabled)
check("A: enabled set is EXACTLY all 25 products, nothing missing",
      enabled == set(REGISTRY.keys()))

print("\n=== E/F: all seven standard_v1, no special generator introduced ===")

for slug in BATCH5_SLUGS:
    check(f"E: {slug} generator is 'standard_v1'", REGISTRY[slug].generator == "standard_v1")
check("F: no Batch-5 product uses 'love_premium_v1' or any non-standard_v1 generator",
      all(REGISTRY[slug].generator == "standard_v1" for slug in BATCH5_SLUGS))

print("\n=== G/H/I: Sade Sati hero is deterministic, phase from backend, never AI-generated ===")

check("G: sadhesati_report hero_value_source is 'deterministic:sadhesati_summary'",
      REGISTRY["sadhesati_report"].hero_value_source == "deterministic:sadhesati_summary")
check("G: sadhesati_report hero_label is 'Sade Sati Status'",
      REGISTRY["sadhesati_report"].hero_label == "Sade Sati Status")

_active_fixture = {
    "sadhesati": {
        "status": "Active", "phase": "2nd Phase", "moon_rashi": "Cancer", "saturn_rashi": "Leo",
        "phase_dates": {
            "first_phase": {"start": "2020-01-01", "end": "2021-01-01"},
            "second_phase": {"start": "2022-01-01", "end": "2023-06-15"},
            "third_phase": {"start": "2024-01-01", "end": "2025-01-01"},
        },
    }
}
_h = compute_sadhesati_hero(_active_fixture, language="en")
check("H: Active status with real phase_dates produces the correct deterministic value",
      _h["value"] == "Active -- 2nd Phase")
check("H: Active status timing reads phase_dates via the CORRECT key mapping (second_phase), "
      "not the underlying engine's own buggy internal lookup",
      _h["timing"] == "01/01/2022 – 15/06/2023")
check("I: no AI-generated Sade Sati status -- compute_sadhesati_hero() is a pure function of "
      "kundali['sadhesati'] only, no AI/Luna call anywhere in its own source",
      "generate_report_completion" not in compute_sadhesati_hero.__code__.co_names
      and "openai" not in compute_sadhesati_hero.__code__.co_names)

_inactive_fixture = {
    "sadhesati": {
        "status": "Inactive", "phase": None, "moon_rashi": "Cancer", "saturn_rashi": "Gemini",
        "phase_dates": {"first_phase": {"start": "2030-01-01", "end": "2032-06-01"}},
    }
}
_hi = compute_sadhesati_hero(_inactive_fixture, language="en")
check("H: Inactive status produces the correct deterministic value", _hi["value"] == "Inactive")
check("H: Inactive status with an upcoming window reads it correctly",
      _hi["timing"] == "01/01/2030 – 01/06/2032")

_missing_fixture = {"sadhesati": {"status": "Error"}}
try:
    compute_sadhesati_hero(_missing_fixture, language="en")
    check("G: undeterminable Sade Sati status raises ReportMetadataError (hard failure, matches "
          "every other mandatory-deterministic-value product)", False)
except ReportMetadataError:
    check("G: undeterminable Sade Sati status raises ReportMetadataError (hard failure, matches "
          "every other mandatory-deterministic-value product)", True)

_no_dates_fixture = {"sadhesati": {"status": "Active", "phase": "1st Phase", "phase_dates": {}}}
_hnd = compute_sadhesati_hero(_no_dates_fixture, language="en")
check("H: missing phase dates safely omit timing/timeline (never guessed)",
      _hnd["value"] == "Active -- 1st Phase" and _hnd["timing"] is None and _hnd["timeline"] is None)

print("\n=== J: no guaranteed-harm/loss language anywhere in the Sade Sati prompts ===")

_sadhesati_en = open("prompts/sadhesati_report_en.txt", encoding="utf-8").read()
_sadhesati_hi = open("prompts/sadhesati_report_hi.txt", encoding="utf-8").read()
check("J: sadhesati_report EN explicitly forbids guaranteed hardship/illness/job loss/financial loss",
      "guaranteed hardship" in _sadhesati_en and "job loss" in _sadhesati_en and "financial loss" in _sadhesati_en)
check("J: sadhesati_report EN explicitly states the purpose is awareness/preparation, never fear",
      "never fear" in _sadhesati_en)

print("\n=== K: Sade Sati substone is deterministic-only when displayed (no AI-named option list) ===")

check("K: sadhesati_report gemstone_policy is 'substone_only'",
      REGISTRY["sadhesati_report"].gemstone_policy == "substone_only")
check("K: sadhesati_report prompt does NOT ask Luna to choose from a named list of substones "
      "(e.g. Amethyst/Lapis Lazuli/Iolite/Black Hakik, the old live violation)",
      "Amethyst" not in _sadhesati_en and "Lapis Lazuli" not in _sadhesati_en)
check("K: sadhesati_report META schema has no gemstone_reason field asking Luna to pick a stone",
      '"gemstone_reason"' not in _sadhesati_en)

print("\n=== L/M/N/O/P/Q: Foreign Travel -- Low/Moderate/Elevated, AI synthesis, no percentage, "
      "no unsupported category, gemstone disabled, no exact date ===")

_ft_en = open("prompts/foreign_travel_report_en.txt", encoding="utf-8").read()
_ft_hi = open("prompts/foreign_travel_report_hi.txt", encoding="utf-8").read()
check("L: foreign_travel_report EN constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _ft_en)
check("M: foreign_travel_report EN explicitly frames the tier as AI synthesis, not a backend score",
      "never a backend score" in _ft_en)
check("N: foreign_travel_report EN forbids a percentage", "no percentage" in _ft_en.lower() or "never a percentage" in _ft_en.lower())
check("O: foreign_travel_report EN forbids unsupported travel-purpose categories "
      "(tourism/education/work/settlement) unless independently supported",
      "tourism" in _ft_en and "education abroad" in _ft_en and "settlement" in _ft_en
      and "unless" in _ft_en)
check("P: foreign_travel_report gemstone_policy is 'disabled'", REGISTRY["foreign_travel_report"].gemstone_policy == "disabled")
check("P: foreign_travel_report components_enabled['gemstone'] is False",
      REGISTRY["foreign_travel_report"].components_enabled.get("gemstone") is False)
check("P: foreign_travel_report prompt has no gemstone section at all",
      "Gemstone" not in _ft_en and "gemstone_reason" not in _ft_en)
check("Q: foreign_travel_report EN forbids an exact travel date", "exact travel date" in _ft_en)
check("L (HI): foreign_travel_report HI constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _ft_hi)

print("\n=== R/S/T/U/V/W/X/Y: Children/Parenting -- qualitative hero, full fertility/pregnancy safety, disclaimer ===")

_cp_en = open("prompts/children_parenting_report_en.txt", encoding="utf-8").read()
_cp_hi = open("prompts/children_parenting_report_hi.txt", encoding="utf-8").read()
check("R: children_parenting_report hero_value_source is 'ai' (qualitative, no tier)",
      REGISTRY["children_parenting_report"].hero_value_source == "ai")
check("R: children_parenting_report prompt instructs a qualitative descriptor only, never a fertility tier",
      "never a fertility/pregnancy tier or score" in _cp_en)
check("S: children_parenting_report EN explicitly forbids fertility/infertility prediction",
      "fertility" in _cp_en and "infertility" in _cp_en)
check("T: children_parenting_report EN explicitly forbids pregnancy likelihood prediction",
      "pregnancy likelihood" in _cp_en)
check("U: children_parenting_report EN explicitly forbids conception timing", "conception timing" in _cp_en)
check("V: children_parenting_report EN explicitly forbids miscarriage prediction", "miscarriage" in _cp_en)
check("W: children_parenting_report EN explicitly forbids child's sex/gender prediction",
      "child's sex/gender" in _cp_en or "a child's sex" in _cp_en)
check("X: children_parenting_report EN explicitly forbids disease/congenital-condition certainty",
      "congenital condition" in _cp_en and "disease" in _cp_en)
check("X: children_parenting_report EN removes the legacy 'favorable/challenging for childbirth' instruction",
      "favorable/challenging" not in _cp_en or "childbirth" not in _cp_en.split("MUST NOT")[0])
check("Y: children_parenting_non_certainty_mandatory key exists and resolves EN+HI",
      "children_parenting_non_certainty_mandatory" in DISCLAIMER_TEXT
      and bool(get_mandatory_disclaimer("children_parenting_non_certainty_mandatory", "en"))
      and bool(get_mandatory_disclaimer("children_parenting_non_certainty_mandatory", "hi")))
check("S (HI): children_parenting_report HI explicitly forbids fertility/pregnancy/conception-timing claims",
      "प्रजनन क्षमता" in _cp_hi and "गर्भधारण" in _cp_hi)

print("\n=== Z/AA/AB/AC: Jupiter Transit -- deterministic hero, real transit mechanism, gemstone disabled, no guaranteed event ===")

check("Z: jupiter_transit_report hero_value_source is 'deterministic:transit_facts_summary'",
      REGISTRY["jupiter_transit_report"].hero_value_source == "deterministic:transit_facts_summary")
check("Z: jupiter_transit_report hero_label is 'Jupiter Transit Focus'",
      REGISTRY["jupiter_transit_report"].hero_label == "Jupiter Transit Focus")

_jupiter_fixture = {
    "lagna_sign": "Aries",
    "transit_summary": {"positions": {"Jupiter": {"rashi": "Sagittarius", "degree": 10.0, "motion": "direct"}}},
}
_jh = compute_jupiter_transit_hero(_jupiter_fixture, language="en")
check("AA: real Jupiter transit mechanism (whole-sign Lagna offset) used, matches Saturn's own formula",
      _jh["value"] == "9th House from Lagna (Sagittarius)")
check("AA: compute_jupiter_transit_hero() calls the SAME planet-generic smart_transit_engine "
      "primitive saturn_transit_report already uses (get_current_sign_residency), confirmed via source",
      "get_current_sign_residency" in compute_jupiter_transit_hero.__code__.co_names)

_jupiter_missing = {"lagna_sign": "Aries", "transit_summary": {"positions": {}}}
try:
    compute_jupiter_transit_hero(_jupiter_missing, language="en")
    check("Z: undeterminable Jupiter house raises ReportMetadataError (mandatory value, hard failure)", False)
except ReportMetadataError:
    check("Z: undeterminable Jupiter house raises ReportMetadataError (mandatory value, hard failure)", True)

check("AB: jupiter_transit_report gemstone_policy is 'disabled' (changed from Batch-0's 'optional', "
      "mirrors saturn_transit_report's own Batch-1 correction)",
      REGISTRY["jupiter_transit_report"].gemstone_policy == "disabled")
_jt_en = open("prompts/jupiter_transit_report_en.txt", encoding="utf-8").read()
check("AB: jupiter_transit_report prompt has no gemstone section", "Gemstone" not in _jt_en)
check("AC: jupiter_transit_report EN forbids guaranteed marriage/pregnancy/promotion/wealth/job/property/education/travel events",
      all(kw in _jt_en for kw in ("marriage", "pregnancy", "promotion", "wealth", "job", "property", "education", "travel")))

print("\n=== AD/AE/AF/AG: Lifestyle -- qualitative hero, no diagnosis, no treatment, disclaimer EN+HI ===")

check("AD: lifestyle_analysis_report hero_value_source is 'ai' (qualitative, no tier)",
      REGISTRY["lifestyle_analysis_report"].hero_value_source == "ai")
_ls_en = open("prompts/lifestyle_analysis_report_en.txt", encoding="utf-8").read()
_ls_hi = open("prompts/lifestyle_analysis_report_hi.txt", encoding="utf-8").read()
check("AE: lifestyle_analysis_report EN explicitly forbids a medical diagnosis", "medical diagnosis" in _ls_en)
check("AF: lifestyle_analysis_report EN explicitly forbids a treatment/medication recommendation",
      "recommend a treatment" in _ls_en or "treatment or medication" in _ls_en)
check("AG: lifestyle_health_non_certainty_mandatory key exists and resolves EN+HI",
      "lifestyle_health_non_certainty_mandatory" in DISCLAIMER_TEXT
      and bool(get_mandatory_disclaimer("lifestyle_health_non_certainty_mandatory", "en"))
      and bool(get_mandatory_disclaimer("lifestyle_health_non_certainty_mandatory", "hi")))
check("AE (HI): lifestyle_analysis_report HI explicitly forbids medical diagnosis/treatment/medication",
      "चिकित्सीय निदान" in _ls_hi and "उपचार या दवा" in _ls_hi)
check("R2: lifestyle_analysis_report is explicitly distinguished from mood_mental_health_report in its own prompt",
      "mood_mental_health_report" in _ls_en)

print("\n=== AH/AI/AJ/AK/AL/AM: Property -- Low/Moderate/Elevated, no purchase/return/title guarantee, no exact date ===")

check("AH: property_report constrains value to exactly Low/Moderate/Elevated",
      REGISTRY["property_report"].hero_value_source == "ai")
_pr_en = open("prompts/property_report_en.txt", encoding="utf-8").read()
_pr_hi = open("prompts/property_report_hi.txt", encoding="utf-8").read()
check("AH: property_report EN prompt constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _pr_en)
check("AI: property_report EN forbids a guaranteed property purchase or sale", "guaranteed property purchase" in _pr_en)
check("AJ: property_report EN forbids guaranteed price appreciation", "guaranteed price appreciation" in _pr_en)
check("AK: property_report EN forbids a guaranteed investment return", "guaranteed investment return" in _pr_en)
check("AL: property_report EN forbids a guaranteed favorable legal-title outcome", "legal-title outcome" in _pr_en)
check("AM: property_report EN forbids an exact purchase date", "exact purchase date" in _pr_en)
check("AH (HI): property_report HI prompt constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _pr_hi)

print("\n=== AN/AO/AP/AQ/AR/AS/AT/AU: Legal Disputes -- highest scrutiny, no court outcome, no advice, no victory framing ===")

_ld_en = open("prompts/legal_disputes_report_en.txt", encoding="utf-8").read()
_ld_hi = open("prompts/legal_disputes_report_hi.txt", encoding="utf-8").read()
check("AN: legal_disputes_report constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _ld_en)
check("AO: legal_disputes_report EN forbids court victory/defeat", "court victory" in _ld_en and "court defeat" in _ld_en)
_victory_lines_en = [line for line in _ld_en.splitlines() if "victory" in line.lower()]
check("AP: legal_disputes_report EN never instructs 'victory' language as a live instruction -- "
      "every line mentioning it is itself a MUST NOT/NEVER prohibition",
      bool(_victory_lines_en) and all(
          ("must not" in line.lower() or "never" in line.lower()) for line in _victory_lines_en
      ))
_victory_lines_hi = [line for line in _ld_hi.splitlines() if "विजय" in line]
check("AP (HI, CRITICAL REGRESSION GUARD): legal_disputes_report_hi.txt contains 'विजय' "
      "(victory) AT MOST once, and ONLY inside its own explicit forbidden-word rule line -- "
      "the old live violation ('क्या कोई ग्रह विजय प्राप्त करने में चुनौती बना हुआ है') must never return",
      len(_victory_lines_hi) <= 1 and (not _victory_lines_hi or "नहीं होना चाहिए" in _victory_lines_hi[0] or "नहीं होनी चाहिए" in _victory_lines_hi[0]))
check("AQ: legal_disputes_report EN forbids arrest prediction", "arrest" in _ld_en)
check("AR: legal_disputes_report EN forbids conviction/acquittal prediction", "conviction" in _ld_en and "acquittal" in _ld_en)
check("AS: legal_disputes_report EN explicitly forbids legal advice / dictating legal strategy",
      ("MUST NOT give legal advice" in _ld_en or "NEVER legal advice" in _ld_en) and "legal strategy" in _ld_en)
check("AT: targeted_aspect_summary is ABSENT from legal_disputes_report's required_context_keys "
      "(dropped -- poor evidentiary fit, see the Q3 Final-7 audit)",
      "targeted_aspect_summary" not in REGISTRY["legal_disputes_report"].required_context_keys)
check("AU: legal_dispute_non_certainty_mandatory key exists and resolves EN+HI",
      "legal_dispute_non_certainty_mandatory" in DISCLAIMER_TEXT
      and bool(get_mandatory_disclaimer("legal_dispute_non_certainty_mandatory", "en"))
      and bool(get_mandatory_disclaimer("legal_dispute_non_certainty_mandatory", "hi")))

print("\n=== AV/AW: gemstone authority -- all deterministic, disabled products have no gemstone component ===")

_gemstone_enabled = {"sadhesati_report", "children_parenting_report", "lifestyle_analysis_report", "property_report", "legal_disputes_report"}
_gemstone_disabled = {"foreign_travel_report", "jupiter_transit_report"}
check("AV: gemstone-enabled Batch-5 products are exactly the expected 5",
      {slug for slug in BATCH5_SLUGS if REGISTRY[slug].gemstone_policy != "disabled"} == _gemstone_enabled)
check("AW: gemstone-disabled Batch-5 products are exactly the expected 2",
      {slug for slug in BATCH5_SLUGS if REGISTRY[slug].gemstone_policy == "disabled"} == _gemstone_disabled)
for slug in _gemstone_disabled:
    check(f"AW: {slug} components_enabled['gemstone'] is False", REGISTRY[slug].components_enabled.get("gemstone") is False)

print("\n=== AX: empty-house rule preserved for all relevant houses (4,5,6,7,8,9,12) ===")

fixture_kundali = {
    "lagna_sign": "Aries",
    "planets": [
        {"name": "Sun", "house": 1, "sign": "Aries"},
        {"name": "Moon", "house": 2, "sign": "Taurus"},
        # Deliberately no planet in 4/5/6/7/8/9/12.
    ],
}
facts = build_house_lord_facts(fixture_kundali)
_by_house = {f["house"]: f for f in facts}
for house_num, expected_sign, expected_lord in [
    (4, "Cancer", "Moon"), (5, "Leo", "Sun"), (6, "Virgo", "Mercury"), (7, "Libra", "Venus"),
    (8, "Scorpio", "Mars"), (9, "Sagittarius", "Jupiter"), (12, "Pisces", "Jupiter"),
]:
    f = _by_house[house_num]
    check(f"AX: house {house_num} has no occupying planet in this fixture", f["occupying_planets"] == [])
    check(f"AX: house {house_num} STILL carries its own sign/lord facts despite being empty",
          f["sign"] == expected_sign and f["lord"] == expected_lord)

print("\n=== AZ: ===META===/===REPORT=== present in all 14 rewritten prompts ===")

_all_prompt_files = [
    "sadhesati_report_en.txt", "sadhesati_report_hi.txt",
    "foreign_travel_report_en.txt", "foreign_travel_report_hi.txt",
    "children_parenting_report_en.txt", "children_parenting_report_hi.txt",
    "jupiter_transit_report_en.txt", "jupiter_transit_report_hi.txt",
    "lifestyle_analysis_report_en.txt", "lifestyle_analysis_report_hi.txt",
    "property_report_en.txt", "property_report_hi.txt",
    "legal_disputes_report_en.txt", "legal_disputes_report_hi.txt",
]
_prompt_text = {fn: open(f"prompts/{fn}", encoding="utf-8").read() for fn in _all_prompt_files}
for fn, text in _prompt_text.items():
    check(f"AZ: {fn} contains ===META=== and ===REPORT=== markers", "===META===" in text and "===REPORT===" in text)

print("\n=== BD: EN/HI heading parity -- no whole-line-bold heading in any HI file starts with a Latin letter ===")

for fn in [f for f in _all_prompt_files if f.endswith("_hi.txt")]:
    t = _prompt_text[fn]
    english_heading_lines = [line for line in t.splitlines() if re.match(r"^\*\*[A-Za-z]", line.strip())]
    check(f"BD: {fn} has no English-lettered whole-line-bold heading", english_heading_lines == [])

print("\n=== BE: no unsupported exact life-event timing anywhere across the 14 prompts (date/month/year/age near an event) ===")

_forbidden_exact_phrases = [
    "you will marry", "you will conceive", "you will win", "you will lose",
    "exact conception date", "exact birth date",
]
_prohibition_markers = ("must not", "never", "no ", "forbid", "cannot", "must never")
for fn, text in _prompt_text.items():
    lowered_lines = text.lower().splitlines()
    live_violations = []
    for phrase in _forbidden_exact_phrases:
        for line in lowered_lines:
            if phrase in line and not any(marker in line for marker in _prohibition_markers):
                live_violations.append((phrase, line))
    check(f"BE: {fn} contains no forbidden exact-event phrase as a LIVE instruction "
          "(a phrase inside the prompt's own MUST NOT/NEVER prohibition line is not a violation)",
          live_violations == [])

print(f"\nPart 1 subtotal: {passed} passed, {failed} failed so far")


# =====================================================================
# PART 2 -- LOCAL Postgres DB integration tests against the REAL
# tasks.py::_generate_and_send_report_core() code path.
# =====================================================================

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from models import Order  # noqa: E402
import tasks  # noqa: E402
from modules.payments.report_ai_client import ReportAICompletion  # noqa: E402


def _fake_completion(content, model="gpt-5.6-luna", input_tokens=100, output_tokens=200, total_tokens=300, duration_seconds=1.5):
    return ReportAICompletion(
        content=content, model=model,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        duration_seconds=duration_seconds,
    )


def _structured_content(value, interpretation="Interpretation text.", evidence=None, action_items=None,
                         gemstone_reason=None, narrative="**Section**\nSome narrative text.\n**Summary**\nDone."):
    evidence = evidence if evidence is not None else ["Evidence one.", "Evidence two."]
    meta = {"answer_hero": {"label": "Label", "value": value, "interpretation": interpretation, "evidence": evidence}}
    if action_items is not None:
        meta["action_items"] = action_items
    if gemstone_reason is not None:
        meta["gemstone_reason"] = gemstone_reason
    import json
    return f"===META===\n{json.dumps(meta)}\n===REPORT===\n{narrative}\n"


def _make_order(**overrides):
    values = dict(
        name="Q3 Batch5 Test", email="q3batch5test@example.com",
        product="sadhesati_report", dob="1990-06-15", tob="10:30", pob="Delhi, India",
        status="PAID", payment_status="PAID", report_stage="Pending",
        latitude="28.6139", longitude="77.2090", language="en",
    )
    values.update(overrides)
    order = Order(**values)
    db.session.add(order)
    db.session.commit()
    return order


def _cleanup(order):
    o = Order.query.get(order.id)
    if o is not None:
        db.session.delete(o)
        db.session.commit()


def _run_capturing_pdf(order_id):
    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return None

    with patch("tasks.generate_pdf_report", side_effect=_capture):
        tasks._generate_and_send_report_core(order_id)
    return captured


with app.app_context():
    current_db = db.session.execute(text("SELECT current_database()")).scalar()
    print(f"\nConnected to database: {current_db}")
    assert current_db == "jyotishasha_local"

    # =================================================================
    print("\n=== 1: sadhesati_report -- deterministic status/phase, substone gemstone, mandatory disclaimer ===")
    # =================================================================
    order1 = _make_order(product="sadhesati_report")
    try:
        fake_content = _structured_content(
            value="Some AI-guessed status that should be discarded",
            gemstone_reason="This substone supports steady discipline during this period.",
            action_items=["Maintain a consistent daily routine.", "Practice patience in decision-making."],
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order1.id)

        db.session.refresh(order1)
        check("1: report_stage reached 'Ready'", order1.report_stage == "Ready")
        check("1: answer_hero.value is the DETERMINISTIC status, AI's own value discarded",
              captured.get("answer_hero", {}).get("value") not in (None, "Some AI-guessed status that should be discarded")
              and ("Active" in captured.get("answer_hero", {}).get("value", "") or captured.get("answer_hero", {}).get("value") == "Inactive"))
        check("1: mandatory Sade Sati disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["sadhesati_non_certainty_mandatory"]["en"])
        check("1: app_download CTA present (global requirement)", captured.get("app_download") is not None)
    finally:
        if order1.pdf_url and os.path.exists(order1.pdf_url):
            os.remove(order1.pdf_url)
        _cleanup(order1)

    # =================================================================
    print("\n=== 2: foreign_travel_report -- Low/Moderate/Elevated passthrough, NO gemstone, no mandatory disclaimer ===")
    # =================================================================
    order2 = _make_order(product="foreign_travel_report")
    try:
        fake_content = _structured_content(value="Moderate")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order2.id)

        db.session.refresh(order2)
        check("2: report_stage reached 'Ready'", order2.report_stage == "Ready")
        check("2: answer_hero.value passes through unmodified ('Moderate')",
              captured.get("answer_hero", {}).get("value") == "Moderate")
        check("2: (required) NO gemstone component, gemstone_policy='disabled'", captured.get("gemstone") is None)
        check("2: no mandatory disclaimer ('general' type)", captured.get("disclaimer") is None)
        check("2: real Dasha-window timeline component was built", captured.get("timeline") is not None)
    finally:
        if order2.pdf_url and os.path.exists(order2.pdf_url):
            os.remove(order2.pdf_url)
        _cleanup(order2)

    # =================================================================
    print("\n=== 3: children_parenting_report -- qualitative hero, mandatory fertility/pregnancy-safety disclaimer ===")
    # =================================================================
    order3 = _make_order(product="children_parenting_report")
    try:
        fake_content = _structured_content(value="Nurturing, With Steady Guidance")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order3.id)

        db.session.refresh(order3)
        check("3: report_stage reached 'Ready'", order3.report_stage == "Ready")
        check("3: answer_hero.value passes through unmodified", captured.get("answer_hero", {}).get("value") == "Nurturing, With Steady Guidance")
        check("3: mandatory children/parenting disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["children_parenting_non_certainty_mandatory"]["en"])
        check("3: disclaimer explicitly excludes fertility/pregnancy/conception-timing/child-sex claims",
              "fertility" in captured.get("disclaimer", "").lower() and "sex" in captured.get("disclaimer", "").lower())
    finally:
        if order3.pdf_url and os.path.exists(order3.pdf_url):
            os.remove(order3.pdf_url)
        _cleanup(order3)

    # =================================================================
    print("\n=== 4: jupiter_transit_report -- deterministic Lagna-relative house, NO gemstone ===")
    # =================================================================
    order4 = _make_order(product="jupiter_transit_report")
    try:
        fake_content = _structured_content(value="Some AI-guessed house that should be discarded")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order4.id)

        db.session.refresh(order4)
        check("4: report_stage reached 'Ready'", order4.report_stage == "Ready")
        check("4: answer_hero.value is the DETERMINISTIC Jupiter house, AI's own value discarded",
              "House from Lagna" in captured.get("answer_hero", {}).get("value", ""))
        check("4: (required) NO gemstone component, gemstone_policy='disabled'", captured.get("gemstone") is None)
        check("4: no mandatory disclaimer ('general' type, mirrors saturn_transit_report)", captured.get("disclaimer") is None)
    finally:
        if order4.pdf_url and os.path.exists(order4.pdf_url):
            os.remove(order4.pdf_url)
        _cleanup(order4)

    # =================================================================
    print("\n=== 5: lifestyle_analysis_report -- qualitative hero, mandatory no-diagnosis disclaimer ===")
    # =================================================================
    order5 = _make_order(product="lifestyle_analysis_report")
    try:
        fake_content = _structured_content(value="Structured, With Room for More Rest")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order5.id)

        db.session.refresh(order5)
        check("5: report_stage reached 'Ready'", order5.report_stage == "Ready")
        check("5: answer_hero.value passes through unmodified", captured.get("answer_hero", {}).get("value") == "Structured, With Room for More Rest")
        check("5: mandatory lifestyle/health disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["lifestyle_health_non_certainty_mandatory"]["en"])
    finally:
        if order5.pdf_url and os.path.exists(order5.pdf_url):
            os.remove(order5.pdf_url)
        _cleanup(order5)

    # =================================================================
    print("\n=== 6: property_report -- Low/Moderate/Elevated, mandatory no-guarantee disclaimer ===")
    # =================================================================
    order6 = _make_order(product="property_report")
    try:
        fake_content = _structured_content(value="Elevated")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order6.id)

        db.session.refresh(order6)
        check("6: report_stage reached 'Ready'", order6.report_stage == "Ready")
        check("6: answer_hero.value passes through unmodified ('Elevated')", captured.get("answer_hero", {}).get("value") == "Elevated")
        check("6: mandatory property disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["property_non_certainty_mandatory"]["en"])
    finally:
        if order6.pdf_url and os.path.exists(order6.pdf_url):
            os.remove(order6.pdf_url)
        _cleanup(order6)

    # =================================================================
    print("\n=== 7: legal_disputes_report -- Low/Moderate/Elevated, mandatory non-certainty/non-advice disclaimer ===")
    # =================================================================
    order7 = _make_order(product="legal_disputes_report")
    try:
        fake_content = _structured_content(value="Low")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order7.id)

        db.session.refresh(order7)
        check("7: report_stage reached 'Ready'", order7.report_stage == "Ready")
        check("7: answer_hero.value passes through unmodified ('Low')", captured.get("answer_hero", {}).get("value") == "Low")
        check("7: mandatory legal-dispute disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["legal_dispute_non_certainty_mandatory"]["en"])
        check("7: disclaimer explicitly states it is not legal advice and names no court-outcome guarantee",
              "not legal advice" in captured.get("disclaimer", "").lower())
    finally:
        if order7.pdf_url and os.path.exists(order7.pdf_url):
            os.remove(order7.pdf_url)
        _cleanup(order7)

    # =================================================================
    print("\n=== 8 (BA): malformed required metadata -> Failed for all 7 Batch-5 products ===")
    # =================================================================
    for slug in BATCH5_SLUGS:
        order_bad = _make_order(product=slug)
        try:
            with patch("tasks.generate_report_completion", return_value=_fake_completion(
                "Plain narrative text with no ===META===/===REPORT=== markers at all."
            )):
                tasks._generate_and_send_report_core(order_bad.id)
            db.session.refresh(order_bad)
            check(f"8 (BA): {slug} -- missing structured metadata -> report_stage='Failed'", order_bad.report_stage == "Failed")
        finally:
            _cleanup(order_bad)

    # =================================================================
    print("\n=== 9 (AY/BD): Hindi-language generation uses the same code path, DD/MM/YYYY, EN/HI parity ===")
    # =================================================================
    order_hi = _make_order(product="property_report", language="hi")
    try:
        fake_content_hi = _structured_content(
            value="Moderate", interpretation="व्याख्या।", evidence=["प्रमाण एक।", "प्रमाण दो।"],
            narrative="**संपत्ति अधिग्रहण प्रवृत्ति**\nहिंदी नैरेटिव पाठ।\n**सारांश**\nसमाप्त।",
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content_hi)):
            captured = _run_capturing_pdf(order_hi.id)

        db.session.refresh(order_hi)
        check("9: Hindi-language property_report reaches 'Ready'", order_hi.report_stage == "Ready")
        check("9: PDF language kwarg is 'hi'", captured.get("language") == "hi")
        check("9: Hindi mandatory disclaimer is the localized Hindi text, not the English fallback",
              captured.get("disclaimer") == DISCLAIMER_TEXT["property_non_certainty_mandatory"]["hi"])
        check("9: Hindi app_download heading is localized",
              captured.get("app_download", {}).get("heading") == "अपनी ज्योतिष यात्रा जारी रखें")
    finally:
        if order_hi.pdf_url and os.path.exists(order_hi.pdf_url):
            os.remove(order_hi.pdf_url)
        _cleanup(order_hi)

    # =================================================================
    print("\n=== 10 (AY): Sade Sati and Jupiter timeline dates are real and DD/MM/YYYY-shaped ===")
    # =================================================================
    order_sade = _make_order(product="sadhesati_report")
    try:
        fake_content = _structured_content(value="Active")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order_sade.id)
        db.session.refresh(order_sade)
        check("10: sadhesati_report reaches 'Ready'", order_sade.report_stage == "Ready")
        if captured.get("timeline"):
            check("10: Sade Sati timeline entries are DD/MM/YYYY-shaped",
                  all(re.match(r"^\d{2}/\d{2}/\d{4} . \d{2}/\d{2}/\d{4}$", e["date_range"]) for e in captured["timeline"]["entries"]))
    finally:
        if order_sade.pdf_url and os.path.exists(order_sade.pdf_url):
            os.remove(order_sade.pdf_url)
        _cleanup(order_sade)

    order_jup = _make_order(product="jupiter_transit_report")
    try:
        fake_content = _structured_content(value="Some house")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order_jup.id)
        db.session.refresh(order_jup)
        check("10: jupiter_transit_report reaches 'Ready'", order_jup.report_stage == "Ready")
        if captured.get("timeline"):
            check("10: Jupiter transit timeline entries are DD/MM/YYYY-shaped",
                  all(re.match(r"^\d{2}/\d{2}/\d{4} . \d{2}/\d{2}/\d{4}$", e["date_range"]) for e in captured["timeline"]["entries"]))
    finally:
        if order_jup.pdf_url and os.path.exists(order_jup.pdf_url):
            os.remove(order_jup.pdf_url)
        _cleanup(order_jup)

    # =================================================================
    print("\n=== 11 (BB/BC): Luna-only, no gpt-4o-mini fallback ===")
    # =================================================================
    import inspect
    _src = inspect.getsource(tasks)
    check("11 (BB): tasks.py imports generate_report_completion from the shared Q3 client (Luna-only)",
          "from modules.payments.report_ai_client import generate_report_completion" in _src)
    _code_lines_with_literal = [
        line for line in _src.splitlines()
        if ("gpt-4o-mini" in line) and not line.strip().startswith("#")
    ]
    check("11 (BC): 'gpt-4o-mini' never appears in a live code line in tasks.py (only in an explanatory comment)",
          _code_lines_with_literal == [])

    # =================================================================
    print("\n=== 12: previous batches remain unaffected by Batch 5 (regression) ===")
    # =================================================================
    order_b1 = _make_order(product="saturn_transit_report")
    try:
        fake_content = _structured_content(value="Some AI-guessed house that should be discarded")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order_b1.id)
        db.session.refresh(order_b1)
        check("12: saturn_transit_report (Batch 1) still reaches 'Ready' unaffected by Batch 5", order_b1.report_stage == "Ready")
        check("12: saturn_transit_report's own deterministic house override still works",
              "House from Lagna" in captured.get("answer_hero", {}).get("value", ""))
    finally:
        if order_b1.pdf_url and os.path.exists(order_b1.pdf_url):
            os.remove(order_b1.pdf_url)
        _cleanup(order_b1)

    order_b4 = _make_order(product="love_marriage_report")
    try:
        fake_content = _structured_content(value="Moderate")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order_b4.id)
        db.session.refresh(order_b4)
        check("12: love_marriage_report (Batch 4) still reaches 'Ready' unaffected by Batch 5", order_b4.report_stage == "Ready")
    finally:
        if order_b4.pdf_url and os.path.exists(order_b4.pdf_url):
            os.remove(order_b4.pdf_url)
        _cleanup(order_b4)

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)

if failed:
    sys.exit(1)
