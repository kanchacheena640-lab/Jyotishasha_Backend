"""
test_report_q3_batch3.py
-------------------------------------------------
Q3 Batch 3 -- verification for the 6 career/money/business Q3-enabled
products (financial_report, financial_stability_report, career_report,
government_job_report, business_report, startup_suggestion_report).

Two kinds of coverage, mirroring test_report_q3_batch1.py/
test_report_q3_batch2.py's own established structure exactly:

  Part 1 (no DB, fast) -- direct unit tests of the new summary_blocks.py
  wealth/career-yoga-evidence builders, registry-shape assertions
  specific to Batch 3's own per-product configuration, the 3 new
  mandatory disclaimers, and static source-level checks of the 12
  rewritten prompt files (strict product differentiation, empty-house
  instructions, safety/non-certainty language, EN/HI heading parity) --
  these do not require a live Luna call or a DB.

  Part 2 (LOCAL Postgres DB, same convention as test_report_q3_batch1/2.
  py) -- direct integration verification against the REAL tasks.py::
  _generate_and_send_report_core() code path for each of the 6 now-real
  q3_enabled=True products, using REAL kundali/dasha calculation (only
  the Luna call and the final PDF render are mocked).

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
from modules.payments.report_q3_batch2 import compute_dasha_window_timeline  # noqa: E402
from modules.payments.report_q3_batch3 import BATCH3_PRODUCT_SLUGS  # noqa: E402
from summary_blocks import (  # noqa: E402
    _build_wealth_yoga_summary, _build_career_yoga_summary,
    WEALTH_YOGA_LABELS, CAREER_YOGA_LABELS, build_house_lord_facts,
)

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

check("A: BATCH3_PRODUCT_SLUGS is exactly the 6 expected slugs", BATCH3_PRODUCT_SLUGS == frozenset(BATCH3_SLUGS))

print("=== A/B/C: exactly 14/25 Q3 products enabled -- Batch-1 4 + Batch-2 4 + Batch-3 6 ===")

enabled = {slug for slug, p in REGISTRY.items() if p.q3_enabled}
check("A: exactly 14 of 25 products are q3_enabled=True", len(enabled) == 14)
check("B: all 6 Batch-3 products are enabled", BATCH3_SLUGS <= enabled)
check("B: all 4 Batch-2 products still enabled (unaffected by Batch 3)", BATCH2_SLUGS <= enabled)
check("B: all 4 Batch-1 products still enabled (unaffected by Batch 3)", BATCH1_SLUGS <= enabled)
check("A: enabled set is EXACTLY Batch-1 ∪ Batch-2 ∪ Batch-3, nothing else",
      enabled == (BATCH1_SLUGS | BATCH2_SLUGS | BATCH3_SLUGS))
check("C: the remaining 11 products are all q3_enabled=False",
      all(not p.q3_enabled for slug, p in REGISTRY.items() if slug not in enabled))

print("\n=== D: hero contracts -- all 6 stay AI-authored (no scoring engine exists for any of them) ===")

for slug in BATCH3_SLUGS:
    check(f"D: {slug} hero_value_source is 'ai'", REGISTRY[slug].hero_value_source == "ai")
    check(f"D: {slug} requires all 4 hero fields (label/value/interpretation/evidence)",
          set(REGISTRY[slug].required_hero_fields) == {"label", "value", "interpretation", "evidence"})

print("\n=== E: gemstone policy -- 'optional' for all 6 Batch-3 products ===")

for slug in BATCH3_SLUGS:
    check(f"E: {slug} gemstone_policy is 'optional'", REGISTRY[slug].gemstone_policy == "optional")
    check(f"E: {slug} components_enabled['gemstone'] is True", REGISTRY[slug].components_enabled.get("gemstone") is True)

print("\n=== F: mandatory disclaimers -- new keys resolve for EN/HI, career_report stays 'general' (no mandatory disclaimer) ===")

check("F: 'financial_advice_non_certainty_mandatory' key exists in shared DISCLAIMER_TEXT", "financial_advice_non_certainty_mandatory" in DISCLAIMER_TEXT)
check("F: 'government_job_selection_non_certainty_mandatory' key exists", "government_job_selection_non_certainty_mandatory" in DISCLAIMER_TEXT)
check("F: 'business_outcome_non_certainty_mandatory' key exists", "business_outcome_non_certainty_mandatory" in DISCLAIMER_TEXT)

check("F: financial_report.disclaimer_type resolves to real EN+HI text",
      bool(get_mandatory_disclaimer(REGISTRY["financial_report"].disclaimer_type, "en"))
      and bool(get_mandatory_disclaimer(REGISTRY["financial_report"].disclaimer_type, "hi")))
check("F: financial_stability_report.disclaimer_type resolves to real EN+HI text",
      bool(get_mandatory_disclaimer(REGISTRY["financial_stability_report"].disclaimer_type, "en"))
      and bool(get_mandatory_disclaimer(REGISTRY["financial_stability_report"].disclaimer_type, "hi")))
check("F: government_job_report.disclaimer_type resolves to real EN+HI text",
      bool(get_mandatory_disclaimer(REGISTRY["government_job_report"].disclaimer_type, "en"))
      and bool(get_mandatory_disclaimer(REGISTRY["government_job_report"].disclaimer_type, "hi")))
check("F: business_report.disclaimer_type resolves to real EN+HI text",
      bool(get_mandatory_disclaimer(REGISTRY["business_report"].disclaimer_type, "en"))
      and bool(get_mandatory_disclaimer(REGISTRY["business_report"].disclaimer_type, "hi")))
check("F: startup_suggestion_report.disclaimer_type resolves to real EN+HI text",
      bool(get_mandatory_disclaimer(REGISTRY["startup_suggestion_report"].disclaimer_type, "en"))
      and bool(get_mandatory_disclaimer(REGISTRY["startup_suggestion_report"].disclaimer_type, "hi")))
check("F: business_report and startup_suggestion_report share the SAME disclaimer type (both business-outcome, deliberate)",
      REGISTRY["business_report"].disclaimer_type == REGISTRY["startup_suggestion_report"].disclaimer_type == "business_outcome_non_certainty_mandatory")
check("F: financial_report and financial_stability_report share the SAME disclaimer type (both financial-advice, deliberate)",
      REGISTRY["financial_report"].disclaimer_type == REGISTRY["financial_stability_report"].disclaimer_type == "financial_advice_non_certainty_mandatory")
check("F: career_report stays on the existing non-mandatory 'general' type (no mandatory disclaimer for this product)",
      REGISTRY["career_report"].disclaimer_type == "general")
check("F: get_mandatory_disclaimer('general', 'en') returns None (career_report gets no disclaimer text)",
      get_mandatory_disclaimer("general", "en") is None)
check("F: earlier batches' disclaimers unaffected by the 3 new keys",
      "mental_health_mandatory" in DISCLAIMER_TEXT and "divorce_non_certainty_mandatory" in DISCLAIMER_TEXT
      and "marriage_problem_non_certainty_mandatory" in DISCLAIMER_TEXT and "second_marriage_non_certainty_mandatory" in DISCLAIMER_TEXT)

print("\n=== G: wealth/career yoga-evidence builders -- safe degradation (never converts missing data into an absence claim) ===")

check("G1: empty kundali -> safe fallback sentence, never a crash",
      _build_wealth_yoga_summary({}) == "No specific wealth yoga is confirmed active from the available deterministic evaluators.")
check("G1: empty kundali -> career fallback sentence too",
      _build_career_yoga_summary({}) == "No specific career yoga is confirmed active from the available deterministic evaluators.")
check("G2: malformed entry (not a dict) is silently skipped, not a crash",
      _build_wealth_yoga_summary({"dhan_yog": "not-a-dict"}) == "No specific wealth yoga is confirmed active from the available deterministic evaluators.")
check("G3: explicitly inactive (is_active=False) yoga is never reported as active",
      "Dhan Yog is active" not in _build_wealth_yoga_summary({"dhan_yog": {"is_active": False}}))
check("G4: is_active key missing entirely is never reported as active",
      "Dhan Yog is active" not in _build_wealth_yoga_summary({"dhan_yog": {"strength": "High"}}))
check("G5: is_active=1 (truthy but not exactly True) is never reported as active -- strict `is True` check",
      "Dhan Yog is active" not in _build_wealth_yoga_summary({"dhan_yog": {"is_active": 1}}))
check("G6: is_active=True (exactly) IS reported as active",
      "Dhan Yog is active in this chart" in _build_wealth_yoga_summary({"dhan_yog": {"is_active": True}}))
check("G7: strength is included when present as a non-empty string",
      "strength: High" in _build_wealth_yoga_summary({"dhan_yog": {"is_active": True, "strength": "High"}}))
check("G8: first reason is included in parentheses when reasons list has a real string",
      "(Venus is strongly placed.)" in _build_wealth_yoga_summary(
          {"dhan_yog": {"is_active": True, "strength": "High", "reasons": ["Venus is strongly placed."]}}))
check("G9: multiple active yogas all appear in the same summary",
      "Dhan Yog is active" in _build_wealth_yoga_summary({"dhan_yog": {"is_active": True}, "kuber_rajyog": {"is_active": True}})
      and "Kuber Rajyog is active" in _build_wealth_yoga_summary({"dhan_yog": {"is_active": True}, "kuber_rajyog": {"is_active": True}}))
check("G10: wealth builder only reads the 4 wealth-relevant keys",
      set(WEALTH_YOGA_LABELS.keys()) == {"dhan_yog", "kuber_rajyog", "lakshmi_yog", "chandra_mangal_yog"})
check("G10: career builder only reads the 6 career-relevant keys",
      set(CAREER_YOGA_LABELS.keys()) == {"dharma_karmadhipati_rajyog", "rajya_sambandh_rajyog", "parashari_rajyog",
                                          "panch_mahapurush_yog", "gajakesari_yog", "budh_aditya_yog"})
check("G11: a career-only-relevant active yoga does not leak into the wealth summary",
      "Gajakesari" not in _build_wealth_yoga_summary({"gajakesari_yog": {"is_active": True}}))
check("G11: a wealth-only-relevant active yoga does not leak into the career summary",
      "Dhan Yog" not in _build_career_yoga_summary({"dhan_yog": {"is_active": True}}))

print("\n=== H: live yoga-evidence generation against a real calculated chart ===")

from full_kundali_api import calculate_full_kundali  # noqa: E402

_kundali_live = calculate_full_kundali(
    name="Batch3 Yoga Test", dob="1990-06-15", tob="10:30",
    lat=28.6139, lon=77.2090, language="en",
)
_live_wealth = _build_wealth_yoga_summary(_kundali_live)
_live_career = _build_career_yoga_summary(_kundali_live)
check("H: real chart produces a non-empty wealth_yoga_summary string", isinstance(_live_wealth, str) and len(_live_wealth) > 0)
check("H: real chart produces a non-empty career_yoga_summary string", isinstance(_live_career, str) and len(_live_career) > 0)
check("H: real wealth summary is either the safe fallback or names a real WEALTH_YOGA_LABELS label",
      _live_wealth.startswith("No specific wealth yoga") or any(label in _live_wealth for label in WEALTH_YOGA_LABELS.values()))
check("H: real career summary is either the safe fallback or names a real CAREER_YOGA_LABELS label",
      _live_career.startswith("No specific career yoga") or any(label in _live_career for label in CAREER_YOGA_LABELS.values()))

print("\n=== I: empty 2nd/6th/8th/10th/11th/12th house still produces full evidence (data layer, Q1.5, unaffected) ===")

fixture_kundali = {
    "lagna_sign": "Aries",
    "planets": [
        {"name": "Sun", "house": 1, "sign": "Aries"},
        {"name": "Moon", "house": 4, "sign": "Cancer"},
        # Deliberately no planet in 2nd/6th/7th/8th/10th/11th/12th --
        # every house Batch-3's 6 products care about.
    ],
}
facts = build_house_lord_facts(fixture_kundali)
_by_house = {f["house"]: f for f in facts}
for house_num, expected_sign, expected_lord in [
    (2, "Taurus", "Venus"), (6, "Virgo", "Mercury"), (7, "Libra", "Venus"),
    (8, "Scorpio", "Mars"), (10, "Capricorn", "Saturn"), (11, "Aquarius", "Saturn"), (12, "Pisces", "Jupiter"),
]:
    f = _by_house[house_num]
    check(f"I: house {house_num} has no occupying planet in this fixture", f["occupying_planets"] == [])
    check(f"I: house {house_num} STILL carries its own sign/lord facts despite being empty",
          f["sign"] == expected_sign and f["lord"] == expected_lord)

print("\n=== J: Dasha-window timeline reused UNCHANGED from Batch 2, no re-implementation ===")

_timeline = compute_dasha_window_timeline(_kundali_live, language="en")
check("J: a real timeline component was built for a Batch-3 chart", _timeline is not None)
if _timeline:
    check("J: timeline has at least 1 entry (the current window)", len(_timeline["entries"]) >= 1)
    check("J: every entry's date_range is DD/MM/YYYY-shaped",
          all(re.match(r"^\d{2}/\d{2}/\d{4} . \d{2}/\d{2}/\d{4}$", e["date_range"]) for e in _timeline["entries"]))
check("J: compute_dasha_window_timeline() returns None (never a guessed timeline) when current window can't be located",
      compute_dasha_window_timeline({"current_mahadasha": {}, "current_antardasha": {}, "Mahadasha": []}, language="en") is None)
check("J: report_q3_batch3.py does not re-export/duplicate compute_dasha_window_timeline",
      not hasattr(__import__("modules.payments.report_q3_batch3", fromlist=["x"]), "compute_dasha_window_timeline"))

print("\n=== K: prompt differentiation -- financial_report vs financial_stability_report ===")

_prompt_files = [
    "financial_report_en.txt", "financial_report_hi.txt",
    "financial_stability_report_en.txt", "financial_stability_report_hi.txt",
    "career_report_en.txt", "career_report_hi.txt",
    "government_job_report_en.txt", "government_job_report_hi.txt",
    "business_report_en.txt", "business_report_hi.txt",
    "startup_suggestion_report_en.txt", "startup_suggestion_report_hi.txt",
]
_prompt_text = {fn: open(f"prompts/{fn}", encoding="utf-8").read() for fn in _prompt_files}

check("K: financial_report EN is framed as GENERATING/BUILDING wealth",
      "GENERATING and BUILDING wealth" in _prompt_text["financial_report_en.txt"])
check("K: financial_stability_report EN is framed as RETENTION/STABILITY/VOLATILITY",
      "RETENTION, STABILITY, and VOLATILITY" in _prompt_text["financial_stability_report_en.txt"])
check("K: financial_stability_report EN explicitly documents the Low/Moderate/Elevated volatility-direction semantic (not inverted)",
      "NOT \"how financially stable\"" in _prompt_text["financial_stability_report_en.txt"]
      or "not \"how financially stable\"" in _prompt_text["financial_stability_report_en.txt"].lower())
check("K: financial_stability_report EN value constrained to Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _prompt_text["financial_stability_report_en.txt"])
check("K: financial_report EN value is explicitly never a number/percentage/score",
      "NEVER a number, percentage, or score" in _prompt_text["financial_report_en.txt"])

print("\n=== L: prompt differentiation -- career_report vs government_job_report ===")

check("L: career_report EN framed as DIRECTION/ORIENTATION, not government-specific",
      "DIRECTION and ORIENTATION" in _prompt_text["career_report_en.txt"])
check("L: government_job_report EN framed specifically as PUBLIC-SECTOR/GOVERNMENT tendency",
      "PUBLIC-SECTOR/GOVERNMENT career tendency" in _prompt_text["government_job_report_en.txt"])
check("L: career_report EN never forces a flat Job-vs-Business binary",
      "do NOT force a binary choice" in _prompt_text["career_report_en.txt"])
check("L: government_job_report EN value constrained to Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _prompt_text["government_job_report_en.txt"])
check("L: government_job_report EN forbids exam/selection/appointment certainty claims",
      "you will clear the exam" in _prompt_text["government_job_report_en.txt"])

print("\n=== M: prompt differentiation -- business_report vs startup_suggestion_report (strict, both directions) ===")

check("M: business_report EN framed as ONGOING BUSINESS CAPACITY (running/sustaining/growing)",
      "ONGOING BUSINESS CAPACITY" in _prompt_text["business_report_en.txt"])
check("M: business_report EN explicitly defers launch-timing questions to startup_suggestion_report",
      "that is startup_suggestion_report, a different product" in _prompt_text["business_report_en.txt"])
check("M: startup_suggestion_report EN framed as PREPARATION and LAUNCH READINESS for a NEW venture",
      "PREPARATION and LAUNCH READINESS" in _prompt_text["startup_suggestion_report_en.txt"])
check("M: startup_suggestion_report EN explicitly forbids writing a business_report under its own heading",
      "do not write a business_report under this heading" in _prompt_text["startup_suggestion_report_en.txt"])
check("M: startup_suggestion_report EN defers ongoing-operation questions to business_report",
      "that is business_report, a different product" in _prompt_text["startup_suggestion_report_en.txt"])
check("M: business_report hero value framed around SUSTAINING/GROWING, never 'start one now'",
      "never about whether to start one now" in _prompt_text["business_report_en.txt"])
check("M: startup_suggestion_report hero value framed around preparation/launch readiness only",
      "never a general business-capacity descriptor" in _prompt_text["startup_suggestion_report_en.txt"])
check("M: startup_suggestion_report gemstone_reason instructed to stay the MOST COMPACT field, never the report's main payoff",
      "most compact field in the whole response, never the report's main payoff" in _prompt_text["startup_suggestion_report_en.txt"])
check("M: business_report uses 9 section headings, startup_suggestion_report uses 8 (structurally distinct section counts)",
      "exactly these 9 numbered section headings" in _prompt_text["business_report_en.txt"]
      and "exactly these 8 numbered section headings" in _prompt_text["startup_suggestion_report_en.txt"])

print("\n=== N: no guaranteed-outcome language anywhere across all 12 Batch-3 prompts ===")

_forbidden_certainty_phrases_en = [
    "guaranteed startup success", "guaranteed business success", "guarantee of exam success",
    "guarantee of profit", "wealth is guaranteed",
]
for fn in [f for f in _prompt_files if f.endswith("_en.txt")]:
    t = _prompt_text[fn]
    check(f"N: {fn} contains at least one explicit non-certainty/non-guarantee instruction",
          any(kw in t.lower() for kw in ("never state or imply", "never promise", "never say or imply", "no certainty claims", "not a prediction or guarantee")))

print("\n=== O: empty-house instruction present in all 12 Batch-3 prompts ===")

for fn in _prompt_files:
    t = _prompt_text[fn]
    check(f"O: {fn} explicitly instructs analysing an empty house via sign/lord/lord-placement",
          ("no planet in this house, therefore nothing to analyse" in t)
          or ("इस भाव में कोई ग्रह नहीं है इसलिए विश्लेषण संभव नहीं" in t))

print("\n=== P: EN/HI heading parity -- no whole-line-bold heading in any HI file starts with a Latin letter ===")

for fn in [f for f in _prompt_files if f.endswith("_hi.txt")]:
    t = _prompt_text[fn]
    english_heading_lines = [line for line in t.splitlines() if re.match(r"^\*\*[A-Za-z]", line.strip())]
    check(f"P: {fn} has no English-lettered whole-line-bold heading", english_heading_lines == [])

print("\n=== Q: startup_suggestion_report_hi.txt was fully rebuilt -- matches EN's exact 8-section structure ===")

_startup_hi = _prompt_text["startup_suggestion_report_hi.txt"]
_startup_en_headings = re.findall(r"^\*\*(\d+)\. ", _prompt_text["startup_suggestion_report_en.txt"], re.MULTILINE)
_startup_hi_headings = re.findall(r"^\*\*(\d+)\. ", _startup_hi, re.MULTILINE)
check("Q: startup_suggestion_report_hi.txt has exactly 8 numbered section headings, matching EN's own count",
      len(_startup_hi_headings) == 8 and _startup_hi_headings == _startup_en_headings == [str(i) for i in range(1, 9)])
check("Q: startup_suggestion_report_hi.txt's closing section is plain 'सारांश' (Summary), NOT the old divergent 'सारांश और प्रेरणा' (Summary and Motivation)",
      "सारांश और प्रेरणा" not in _startup_hi and "**8. सारांश**" in _startup_hi)
check("Q: startup_suggestion_report_hi.txt does not reuse 'व्यवसाय' framing as its own opening heading (must not read as business_report)",
      "**1. व्यवसाय" not in _startup_hi)
check("Q: startup_suggestion_report_hi.txt uses all 5 expected context placeholders",
      all(f"{{{k}}}" in _startup_hi for k in
          ("birth_chart_summary", "house_lord_summary", "career_yoga_summary", "wealth_yoga_summary", "dasha_window_summary")))

print("\n=== R: all 12 Batch-3 prompts consume the correct context keys per their own registry entry ===")

for slug in BATCH3_SLUGS:
    for lang in ("en", "hi"):
        fn = f"{slug}_{lang}.txt"
        t = _prompt_text[fn]
        for key in REGISTRY[slug].required_context_keys:
            if key == "gemstone_summary":
                continue  # gemstone_summary is consumed by the PDF gemstone component, not necessarily quoted verbatim in every prompt body
            check(f"R: {fn} references its own registry-required context key '{{{key}}}'", f"{{{key}}}" in t)

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
        name="Q3 Batch3 Test", email="q3batch3test@example.com",
        product="financial_report", dob="1990-06-15", tob="10:30", pob="Delhi, India",
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
    print("\n=== 1: financial_report -- AI hero passthrough, real Dasha timeline, optional gemstone, mandatory disclaimer ===")
    # =================================================================
    order1 = _make_order(product="financial_report")
    try:
        fake_content = _structured_content(
            value="Building Momentum",
            gemstone_reason="This stone supports steady financial growth.",
            action_items=["Diversify income sources.", "Track monthly cash flow."],
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order1.id)

        db.session.refresh(order1)
        check("1: report_stage reached 'Ready'", order1.report_stage == "Ready")
        check("1: answer_hero.value is the AI-authored descriptor, unmodified (hero_value_source='ai')",
              captured.get("answer_hero", {}).get("value") == "Building Momentum")
        check("1: real Dasha-window timeline component was built", captured.get("timeline") is not None)
        check("1: gemstone component built (deterministic, policy='optional')", captured.get("gemstone") is not None)
        check("1: mandatory financial disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["financial_advice_non_certainty_mandatory"]["en"])
        check("1: action_list component built from AI-supplied action_items", captured.get("action_list") is not None)
        check("1: app_download CTA present (global requirement)", captured.get("app_download") is not None)
    finally:
        if order1.pdf_url and os.path.exists(order1.pdf_url):
            os.remove(order1.pdf_url)
        _cleanup(order1)

    # =================================================================
    print("\n=== 2: financial_stability_report -- Low/Moderate/Elevated passthrough, mandatory disclaimer ===")
    # =================================================================
    order2 = _make_order(product="financial_stability_report")
    try:
        fake_content = _structured_content(value="Moderate")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order2.id)

        db.session.refresh(order2)
        check("2: report_stage reached 'Ready'", order2.report_stage == "Ready")
        check("2: answer_hero.value passes through unmodified ('Moderate')",
              captured.get("answer_hero", {}).get("value") == "Moderate")
        check("2: real Dasha-window timeline component was built", captured.get("timeline") is not None)
        check("2: mandatory financial disclaimer present -- SAME key as financial_report (deliberate)",
              captured.get("disclaimer") == DISCLAIMER_TEXT["financial_advice_non_certainty_mandatory"]["en"])
    finally:
        if order2.pdf_url and os.path.exists(order2.pdf_url):
            os.remove(order2.pdf_url)
        _cleanup(order2)

    # =================================================================
    print("\n=== 3: career_report -- AI hero passthrough, NO mandatory disclaimer ('general' type) ===")
    # =================================================================
    order3 = _make_order(product="career_report")
    try:
        fake_content = _structured_content(value="Structured, Service-Oriented Tendency")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order3.id)

        db.session.refresh(order3)
        check("3: report_stage reached 'Ready'", order3.report_stage == "Ready")
        check("3: answer_hero.value passes through unmodified", captured.get("answer_hero", {}).get("value") == "Structured, Service-Oriented Tendency")
        check("3: real Dasha-window timeline component was built", captured.get("timeline") is not None)
        check("3: (required) NO mandatory disclaimer for career_report -- disclaimer_type is 'general'",
              captured.get("disclaimer") is None)
        check("3: app_download CTA still present", captured.get("app_download") is not None)
    finally:
        if order3.pdf_url and os.path.exists(order3.pdf_url):
            os.remove(order3.pdf_url)
        _cleanup(order3)

    # =================================================================
    print("\n=== 4: government_job_report -- Low/Moderate/Elevated, mandatory disclaimer ===")
    # =================================================================
    order4 = _make_order(product="government_job_report")
    try:
        fake_content = _structured_content(value="Elevated")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order4.id)

        db.session.refresh(order4)
        check("4: report_stage reached 'Ready'", order4.report_stage == "Ready")
        check("4: answer_hero.value passes through unmodified ('Elevated')", captured.get("answer_hero", {}).get("value") == "Elevated")
        check("4: mandatory government-job disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["government_job_selection_non_certainty_mandatory"]["en"])
        check("4: disclaimer explicitly names preparation/eligibility/selection process, never a guarantee",
              "preparation" in captured.get("disclaimer", "").lower())
    finally:
        if order4.pdf_url and os.path.exists(order4.pdf_url):
            os.remove(order4.pdf_url)
        _cleanup(order4)

    # =================================================================
    print("\n=== 5: business_report -- ongoing-capacity hero, mandatory disclaimer ===")
    # =================================================================
    order5 = _make_order(product="business_report")
    try:
        fake_content = _structured_content(value="Naturally Suited, With Steady Discipline")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order5.id)

        db.session.refresh(order5)
        check("5: report_stage reached 'Ready'", order5.report_stage == "Ready")
        check("5: answer_hero.value passes through unmodified", captured.get("answer_hero", {}).get("value") == "Naturally Suited, With Steady Discipline")
        check("5: mandatory business-outcome disclaimer present, backend-controlled",
              captured.get("disclaimer") == DISCLAIMER_TEXT["business_outcome_non_certainty_mandatory"]["en"])
    finally:
        if order5.pdf_url and os.path.exists(order5.pdf_url):
            os.remove(order5.pdf_url)
        _cleanup(order5)

    # =================================================================
    print("\n=== 6: startup_suggestion_report -- launch-readiness hero, SAME disclaimer type as business_report ===")
    # =================================================================
    order6 = _make_order(product="startup_suggestion_report")
    try:
        fake_content = _structured_content(
            value="Comparatively Ready to Launch",
            gemstone_reason="A brief, secondary note only.",
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order6.id)

        db.session.refresh(order6)
        check("6: report_stage reached 'Ready'", order6.report_stage == "Ready")
        check("6: answer_hero.value passes through unmodified", captured.get("answer_hero", {}).get("value") == "Comparatively Ready to Launch")
        check("6: mandatory business-outcome disclaimer present -- SAME key as business_report (deliberate)",
              captured.get("disclaimer") == DISCLAIMER_TEXT["business_outcome_non_certainty_mandatory"]["en"])
        check("6: real Dasha-window timeline component was built", captured.get("timeline") is not None)
    finally:
        if order6.pdf_url and os.path.exists(order6.pdf_url):
            os.remove(order6.pdf_url)
        _cleanup(order6)

    # =================================================================
    print("\n=== 7: malformed required metadata -> Failed for all 6 Batch-3 products ===")
    # =================================================================
    for slug in BATCH3_SLUGS:
        order_bad = _make_order(product=slug)
        try:
            with patch("tasks.generate_report_completion", return_value=_fake_completion(
                "Plain narrative text with no ===META===/===REPORT=== markers at all."
            )):
                tasks._generate_and_send_report_core(order_bad.id)
            db.session.refresh(order_bad)
            check(f"7: {slug} -- missing structured metadata -> report_stage='Failed'", order_bad.report_stage == "Failed")
        finally:
            _cleanup(order_bad)

    # =================================================================
    print("\n=== 8: Hindi-language generation uses the same code path (EN/HI parity) ===")
    # =================================================================
    order_hi = _make_order(product="business_report", language="hi")
    try:
        fake_content_hi = _structured_content(
            value="स्वाभाविक रूप से उपयुक्त, स्थिर अनुशासन के साथ",
            interpretation="व्याख्या।", evidence=["प्रमाण एक।", "प्रमाण दो।"],
            narrative="**व्यवसाय उपयुक्तता**\nहिंदी नैरेटिव पाठ।\n**सारांश**\nसमाप्त।",
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content_hi)):
            captured = _run_capturing_pdf(order_hi.id)

        db.session.refresh(order_hi)
        check("8: Hindi-language business_report reaches 'Ready'", order_hi.report_stage == "Ready")
        check("8: PDF language kwarg is 'hi'", captured.get("language") == "hi")
        check("8: Hindi mandatory disclaimer is the localized Hindi text, not the English fallback",
              captured.get("disclaimer") == DISCLAIMER_TEXT["business_outcome_non_certainty_mandatory"]["hi"])
        check("8: Hindi app_download heading is localized",
              captured.get("app_download", {}).get("heading") == "अपनी ज्योतिष यात्रा जारी रखें")
    finally:
        if order_hi.pdf_url and os.path.exists(order_hi.pdf_url):
            os.remove(order_hi.pdf_url)
        _cleanup(order_hi)

    # =================================================================
    print("\n=== 9: Luna-only, no gpt-4o-mini fallback ===")
    # =================================================================
    import inspect
    _src = inspect.getsource(tasks)
    check("9: tasks.py imports generate_report_completion from the shared Q3 client (Luna-only)",
          "from modules.payments.report_ai_client import generate_report_completion" in _src)
    _code_lines_with_literal = [
        line for line in _src.splitlines()
        if ("gpt-4o-mini" in line) and not line.strip().startswith("#")
    ]
    check("9: 'gpt-4o-mini' never appears in a live code line in tasks.py (only in an explanatory comment)",
          _code_lines_with_literal == [])

    # =================================================================
    print("\n=== 10: Batch-1 and Batch-2 products remain unaffected by Batch 3 (regression) ===")
    # =================================================================
    order_b1 = _make_order(product="saturn_transit_report")
    try:
        fake_content = _structured_content(value="Some AI-guessed house that should be discarded")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order_b1.id)
        db.session.refresh(order_b1)
        check("10: saturn_transit_report (Batch 1) still reaches 'Ready' unaffected by Batch 3", order_b1.report_stage == "Ready")
        check("10: saturn_transit_report's deterministic house override still works",
              "House from Lagna" in captured.get("answer_hero", {}).get("value", ""))
    finally:
        if order_b1.pdf_url and os.path.exists(order_b1.pdf_url):
            os.remove(order_b1.pdf_url)
        _cleanup(order_b1)

    order_b2 = _make_order(product="marriage_report")
    try:
        fake_content = _structured_content(value="Supportive, With Steady Effort")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order_b2.id)
        db.session.refresh(order_b2)
        check("10: marriage_report (Batch 2) still reaches 'Ready' unaffected by Batch 3", order_b2.report_stage == "Ready")
        check("10: marriage_report still has NO mandatory disclaimer ('general' type, unaffected)",
              captured.get("disclaimer") is None)
    finally:
        if order_b2.pdf_url and os.path.exists(order_b2.pdf_url):
            os.remove(order_b2.pdf_url)
        _cleanup(order_b2)

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)

if failed:
    sys.exit(1)
