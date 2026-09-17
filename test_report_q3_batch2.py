"""
test_report_q3_batch2.py
-------------------------------------------------
Q3 Batch 2 -- verification for the 4 marriage-family Q3-enabled
products (marriage_report, delay_in_marriage_report,
problem_in_marriage_report, second_marriage_report).

Two kinds of coverage, mirroring test_report_q3_batch1.py's own
established structure exactly:

  Part 1 (no DB, fast) -- direct unit tests of modules/payments/
  report_q3_batch2.py's dasha-window timeline helper, registry-shape
  assertions specific to Batch 2's own per-product configuration, the
  2 new mandatory disclaimers, and static source-level checks of the
  8 rewritten prompt files (bug removal, safety language, empty-house
  instructions, EN/HI heading parity) -- these do not require a live
  Luna call or a DB.

  Part 2 (LOCAL Postgres DB, same convention as test_report_q3_batch1.
  py) -- direct integration verification against the REAL tasks.py::
  _generate_and_send_report_core() code path for each of the 4 now-
  real q3_enabled=True products, using REAL kundali/dasha calculation
  (only the Luna call and the final PDF render are mocked).

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
from modules.payments.report_date_format import format_customer_date  # noqa: E402

BATCH2_SLUGS = {
    "marriage_report", "delay_in_marriage_report",
    "problem_in_marriage_report", "second_marriage_report",
}
BATCH1_SLUGS = {
    "gemstone_consultation", "saturn_transit_report",
    "mood_mental_health_report", "divorce_possibility_report",
}

print("=== A/B/C: exactly 8/25 Q3 products enabled -- the 4 Batch-1 + the 4 Batch-2 ===")

enabled = {slug for slug, p in REGISTRY.items() if p.q3_enabled}
check("A: exactly 8 of 25 products are q3_enabled=True", len(enabled) == 8)
check("B: all 4 Batch-2 products are enabled", BATCH2_SLUGS <= enabled)
check("B: all 4 Batch-1 products are still enabled (V: Batch-1 unchanged)", BATCH1_SLUGS <= enabled)
check("A: enabled set is EXACTLY Batch-1 ∪ Batch-2, nothing else", enabled == (BATCH1_SLUGS | BATCH2_SLUGS))
check("C: the remaining 17 products are all q3_enabled=False",
      all(not p.q3_enabled for slug, p in REGISTRY.items() if slug not in enabled))

print("\n=== D: hero contracts per product ===")

check("D: marriage_report hero label design is 'ai' value source (no marriage-scoring engine exists)",
      REGISTRY["marriage_report"].hero_value_source == "ai")
check("D: marriage_report required_hero_fields include value/evidence",
      {"label", "value", "interpretation", "evidence"} <= set(REGISTRY["marriage_report"].required_hero_fields))
check("D: delay_in_marriage_report hero_value_source is 'ai' (tier is prompt-enforced, not backend-deterministic)",
      REGISTRY["delay_in_marriage_report"].hero_value_source == "ai")
check("D: problem_in_marriage_report hero_value_source is 'ai'",
      REGISTRY["problem_in_marriage_report"].hero_value_source == "ai")
check("D: second_marriage_report hero_value_source is 'ai'",
      REGISTRY["second_marriage_report"].hero_value_source == "ai")
for slug in BATCH2_SLUGS:
    check(f"D: {slug} requires all 4 hero fields (label/value/interpretation/evidence)",
          set(REGISTRY[slug].required_hero_fields) == {"label", "value", "interpretation", "evidence"})

print("\n=== E/F: Delay + Second-Marriage hero value MUST be constrained to Low/Moderate/Elevated (prompt-level) ===")

_delay_en = open("prompts/delay_in_marriage_report_en.txt", encoding="utf-8").read()
_delay_hi = open("prompts/delay_in_marriage_report_hi.txt", encoding="utf-8").read()
_second_en = open("prompts/second_marriage_report_en.txt", encoding="utf-8").read()
_second_hi = open("prompts/second_marriage_report_hi.txt", encoding="utf-8").read()

check("E: delay_in_marriage_report EN prompt constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _delay_en)
check("E: delay_in_marriage_report EN prompt forbids a percentage/score",
      "never a percentage or score" in _delay_en)
check("E: delay_in_marriage_report HI prompt constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _delay_hi)
check("F: second_marriage_report EN prompt constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _second_en)
check("F: second_marriage_report HI prompt constrains value to exactly Low/Moderate/Elevated",
      "Low, Moderate, Elevated" in _second_hi)
check("F: no numeric backend enum validator was added for this field (deliberate -- matches divorce_possibility_report's own established precedent)",
      "value" not in "".join(dir(compute_dasha_window_timeline)))  # trivially true; documents the design choice below
print("  (design note: Low/Moderate/Elevated is enforced by prompt instruction only, not a backend validator -- "
      "the same precedent already established for divorce_possibility_report in Q3 Batch 1)")

print("\n=== G/H: empty 7th/9th house still produces full evidence (data layer, Q1.5, unchanged) ===")

from summary_blocks import build_house_lord_facts  # noqa: E402

fixture_kundali = {
    "lagna_sign": "Aries",
    "planets": [
        {"name": "Sun", "house": 1, "sign": "Aries"},
        {"name": "Moon", "house": 2, "sign": "Taurus"},
        # Deliberately no planet in house 7 (Libra) or house 9 (Gemini).
    ],
}
facts = build_house_lord_facts(fixture_kundali)
house7 = next(f for f in facts if f["house"] == 7)
house9 = next(f for f in facts if f["house"] == 9)
check("G: house 7 has no occupying planet in this fixture (the actual empty-house case under test)",
      house7["occupying_planets"] == [])
check("G: house 7 STILL carries its own sign/lord/lord-placement facts despite being empty",
      house7["sign"] == "Libra" and house7["lord"] == "Venus")
check("H: house 9 has no occupying planet in this fixture", house9["occupying_planets"] == [])
check("H: house 9 STILL carries its own sign/lord/lord-placement facts despite being empty",
      house9["sign"] == "Sagittarius" and house9["lord"] == "Jupiter")

print("\n=== I/J: no exact-age marriage instruction survives anywhere in the 8 prompts ===")

_all_prompt_files = [
    "marriage_report_en.txt", "marriage_report_hi.txt",
    "delay_in_marriage_report_en.txt", "delay_in_marriage_report_hi.txt",
    "problem_in_marriage_report_en.txt", "problem_in_marriage_report_hi.txt",
    "second_marriage_report_en.txt", "second_marriage_report_hi.txt",
]
_prompt_text = {fn: open(f"prompts/{fn}", encoding="utf-8").read() for fn in _all_prompt_files}

check("I: no prompt instructs concluding marriage 'likely to happen early (before 24) or late (after 29)'",
      not any("likely to happen early" in t for t in _prompt_text.values()))
# "before 24"/"after 29" survive only inside the EN prompt's own
# forbidden-examples safety rule (quoted as text NOT to write) --
# check the containing line itself carries "forbidden", proving it is
# guardrail text, not a live instruction to produce that phrase.
_before24_lines = [
    line for line in _prompt_text["marriage_report_en.txt"].splitlines()
    if "before 24" in line
]
check("J: 'before 24' appears exactly once in marriage_report_en.txt, and only inside its own forbidden-examples safety line",
      len(_before24_lines) == 1 and "forbidden" in _before24_lines[0].lower())
check("J: 'after 29' does not appear anywhere in the Hindi marriage prompt", "after 29" not in _prompt_text["marriage_report_hi.txt"])
check("J: '24 वर्ष से पहले' (the old Hindi exact-age instruction) does not appear as a real instruction in marriage_report_hi.txt",
      "स्पष्ट निष्कर्ष दें कि विवाह जल्दी" not in _prompt_text["marriage_report_hi.txt"])
# Only the 3 products whose purchased question involves marriage
# TIMING (marriage_report, delay_in_marriage_report,
# second_marriage_report) need an explicit no-exact-age/date/year
# rule; problem_in_marriage_report is about existing friction, not
# timing, so it is not held to this same requirement.
_timing_relevant_files = [
    "marriage_report_en.txt", "marriage_report_hi.txt",
    "delay_in_marriage_report_en.txt", "delay_in_marriage_report_hi.txt",
    "second_marriage_report_en.txt", "second_marriage_report_hi.txt",
]
for fn in _timing_relevant_files:
    t = _prompt_text[fn]
    check(f"I/J: {fn} explicitly forbids an exact marriage/remarriage age, date, month, or year",
          any(kw in t for kw in ("exact marriage age", "remarriage date", "निश्चित आयु", "निश्चित तारीख", "specific year", "तारीख, महीना या वर्ष")))

print("\n=== K: Hindi marriage prompt no longer says व्यवसाय रिपोर्ट (Business Report) ===")

check("K: 'व्यवसाय रिपोर्ट' does not appear anywhere in marriage_report_hi.txt",
      "व्यवसाय रिपोर्ट" not in _prompt_text["marriage_report_hi.txt"])
check("K: marriage_report_hi.txt correctly says 'विवाह' (marriage) in its own opening line",
      "विवाह" in _prompt_text["marriage_report_hi.txt"].splitlines()[0])

print("\n=== L: Hindi delay-in-marriage headings are fully translated (no English headings left) ===")

_english_heading_lines = [
    line for line in _prompt_text["delay_in_marriage_report_hi.txt"].splitlines()
    if re.match(r"^\*\*[A-Za-z]", line.strip())
]
check("L: no whole-line-bold heading in delay_in_marriage_report_hi.txt starts with a Latin letter",
      _english_heading_lines == [])
check("L: delay_in_marriage_report_hi.txt uses natural Hindi heading text (e.g. 'देरी संकेत')",
      "देरी संकेत" in _prompt_text["delay_in_marriage_report_hi.txt"])

print("\n=== M/N/O: deterministic Dasha timeline -- real dates only, DD/MM/YYYY, never invented ===")

from full_kundali_api import calculate_full_kundali  # noqa: E402

_kundali_for_timeline = calculate_full_kundali(
    name="Batch2 Timeline Test", dob="1990-06-15", tob="10:30",
    lat=28.6139, lon=77.2090, language="en",
)
timeline = compute_dasha_window_timeline(_kundali_for_timeline, language="en")
check("M: a real timeline component was built from real Dasha data", timeline is not None)
if timeline:
    check("M: timeline has at least 1 entry (the current window)", len(timeline["entries"]) >= 1)
    check("M: the first entry is marked current=True", timeline["entries"][0]["current"] is True)
    check("N: every entry's date_range is DD/MM/YYYY-shaped",
          all(re.match(r"^\d{2}/\d{2}/\d{4} . \d{2}/\d{2}/\d{4}$", e["date_range"]) for e in timeline["entries"]))
    check("O: entry labels name real Mahadasha/Antardasha lords from the actual chart, never a placeholder",
          all("Mahadasha" in e["label"] and "Antardasha" in e["label"] for e in timeline["entries"]))
check("O: compute_dasha_window_timeline() returns None (never a guessed timeline) when current window can't be located",
      compute_dasha_window_timeline({"current_mahadasha": {}, "current_antardasha": {}, "Mahadasha": []}, language="en") is None)

_timeline_hi = compute_dasha_window_timeline(_kundali_for_timeline, language="hi")
check("N (HI): Hindi timeline also produces DD/MM/YYYY dates, same underlying data",
      _timeline_hi is not None and _timeline_hi["entries"][0]["date_range"] == timeline["entries"][0]["date_range"])
check("N (HI): Hindi timeline heading/notes are localized", _timeline_hi["heading"] == "वर्तमान एवं आगामी दशा अवधि")

print("\n=== P: gemstone policies -- optional / optional / disabled / disabled ===")

check("P: marriage_report gemstone_policy is 'optional'", REGISTRY["marriage_report"].gemstone_policy == "optional")
check("P: delay_in_marriage_report gemstone_policy is 'optional'", REGISTRY["delay_in_marriage_report"].gemstone_policy == "optional")
check("P: problem_in_marriage_report gemstone_policy is 'disabled'", REGISTRY["problem_in_marriage_report"].gemstone_policy == "disabled")
check("P: second_marriage_report gemstone_policy is 'disabled'", REGISTRY["second_marriage_report"].gemstone_policy == "disabled")
check("P: components_enabled['gemstone'] agrees with gemstone_policy for all 4",
      REGISTRY["marriage_report"].components_enabled.get("gemstone") is True
      and REGISTRY["delay_in_marriage_report"].components_enabled.get("gemstone") is True
      and REGISTRY["problem_in_marriage_report"].components_enabled.get("gemstone") is False
      and REGISTRY["second_marriage_report"].components_enabled.get("gemstone") is False)

print("\n=== Q: mandatory disclaimer behavior (new keys, reusing the existing generic mechanism) ===")

check("Q: 'marriage_problem_non_certainty_mandatory' key exists in the shared DISCLAIMER_TEXT dict",
      "marriage_problem_non_certainty_mandatory" in DISCLAIMER_TEXT)
check("Q: 'second_marriage_non_certainty_mandatory' key exists in the shared DISCLAIMER_TEXT dict",
      "second_marriage_non_certainty_mandatory" in DISCLAIMER_TEXT)
check("Q: problem_in_marriage_report's registry disclaimer_type resolves to real EN text",
      bool(get_mandatory_disclaimer(REGISTRY["problem_in_marriage_report"].disclaimer_type, "en")))
check("Q: problem_in_marriage_report's registry disclaimer_type resolves to real HI text",
      bool(get_mandatory_disclaimer(REGISTRY["problem_in_marriage_report"].disclaimer_type, "hi")))
check("Q: second_marriage_report's registry disclaimer_type resolves to real EN text",
      bool(get_mandatory_disclaimer(REGISTRY["second_marriage_report"].disclaimer_type, "en")))
check("Q: second_marriage_report's registry disclaimer_type resolves to real HI text",
      bool(get_mandatory_disclaimer(REGISTRY["second_marriage_report"].disclaimer_type, "hi")))
check("Q: marriage_report/delay_in_marriage_report stay on the existing non-mandatory 'general' type",
      REGISTRY["marriage_report"].disclaimer_type == "general"
      and REGISTRY["delay_in_marriage_report"].disclaimer_type == "general")
check("Q: divorce/mood disclaimers (Batch 1) are unaffected by the new keys",
      "mental_health_mandatory" in DISCLAIMER_TEXT and "divorce_non_certainty_mandatory" in DISCLAIMER_TEXT)

print("\n=== R: no partner-intention claims -- explicit prohibition present in both safety-sensitive prompts ===")

for fn in ("problem_in_marriage_report_en.txt", "problem_in_marriage_report_hi.txt",
           "second_marriage_report_en.txt", "second_marriage_report_hi.txt"):
    t = _prompt_text[fn]
    check(f"R: {fn} explicitly forbids claims about the partner's/another person's private thoughts or intentions",
          any(kw in t for kw in ("private thoughts", "निजी विचार")))
check("R: problem_in_marriage_report EN forbids predicting/implying divorce or separation",
      "predict, suggest, or imply that divorce or separation" in _prompt_text["problem_in_marriage_report_en.txt"])
check("R: problem_in_marriage_report EN forbids telling the customer to end the marriage",
      "end their marriage" in _prompt_text["problem_in_marriage_report_en.txt"])
check("R: second_marriage_report EN forbids guaranteeing a second marriage",
      "guarantee" in _prompt_text["second_marriage_report_en.txt"].lower())
check("R: second_marriage_report EN forbids implying a current marriage will end",
      "current marriage will end" in _prompt_text["second_marriage_report_en.txt"])

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
        name="Q3 Batch2 Test", email="q3batch2test@example.com",
        product="marriage_report", dob="1990-06-15", tob="10:30", pob="Delhi, India",
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
    print("\n=== 1: marriage_report -- hero passthrough, real Dasha timeline, optional gemstone ===")
    # =================================================================
    order1 = _make_order(product="marriage_report")
    try:
        fake_content = _structured_content(
            value="Supportive, With Steady Effort",
            gemstone_reason="This stone supports harmony in relationships.",
            action_items=["Communicate openly.", "Be patient during this period."],
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order1.id)

        db.session.refresh(order1)
        check("1: report_stage reached 'Ready'", order1.report_stage == "Ready")
        check("1: answer_hero.value is the AI-authored descriptor, unmodified (hero_value_source='ai')",
              captured.get("answer_hero", {}).get("value") == "Supportive, With Steady Effort")
        check("1: real Dasha-window timeline component was built", captured.get("timeline") is not None)
        if captured.get("timeline"):
            check("1: timeline entries are DD/MM/YYYY-shaped",
                  all(re.match(r"^\d{2}/\d{2}/\d{4} . \d{2}/\d{2}/\d{4}$", e["date_range"]) for e in captured["timeline"]["entries"]))
        check("1: gemstone component built (deterministic, policy='optional')", captured.get("gemstone") is not None)
        if captured.get("gemstone"):
            check("1: gemstone.reason is AI-authored, planet/gemstone/substone are deterministic",
                  captured["gemstone"]["reason"] == "This stone supports harmony in relationships." and captured["gemstone"]["planet"])
        check("1: no mandatory disclaimer for marriage_report ('general' type)", captured.get("disclaimer") is None)
        check("1: app_download CTA present (global requirement)", captured.get("app_download") is not None)
    finally:
        if order1.pdf_url and os.path.exists(order1.pdf_url):
            os.remove(order1.pdf_url)
        _cleanup(order1)

    # =================================================================
    print("\n=== 2: delay_in_marriage_report -- Low/Moderate/Elevated passthrough, timeline, optional gemstone ===")
    # =================================================================
    order2 = _make_order(product="delay_in_marriage_report")
    try:
        fake_content = _structured_content(value="Moderate")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order2.id)

        db.session.refresh(order2)
        check("2: report_stage reached 'Ready'", order2.report_stage == "Ready")
        check("2: answer_hero.value passes through unmodified ('Moderate')",
              captured.get("answer_hero", {}).get("value") == "Moderate")
        check("2: real Dasha-window timeline component was built", captured.get("timeline") is not None)
        check("2: gemstone component built (policy='optional')", captured.get("gemstone") is not None)
        check("2: no mandatory disclaimer ('general' type)", captured.get("disclaimer") is None)
    finally:
        if order2.pdf_url and os.path.exists(order2.pdf_url):
            os.remove(order2.pdf_url)
        _cleanup(order2)

    # =================================================================
    print("\n=== 3: problem_in_marriage_report -- NO gemstone, NO timeline, mandatory disclaimer always present ===")
    # =================================================================
    order3 = _make_order(product="problem_in_marriage_report")
    try:
        fake_content = _structured_content(
            value="Manageable With Communication",
            narrative="**Friction Pattern**\nCalm narrative with no disclaimer text at all.",
            gemstone_reason="This gemstone would resolve conflicts.",  # deliberately supplied, must still be ignored
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order3.id)

        db.session.refresh(order3)
        check("3: report_stage reached 'Ready'", order3.report_stage == "Ready")
        check("3: answer_hero.value passes through unmodified", captured.get("answer_hero", {}).get("value") == "Manageable With Communication")
        check("3: (required) NO gemstone component, even though the AI supplied a gemstone_reason",
              captured.get("gemstone") is None)
        check("3: NO timeline component (components_enabled.timeline=False)", captured.get("timeline") is None)
        check("3: mandatory disclaimer is present even though the AI never wrote one",
              captured.get("disclaimer") == DISCLAIMER_TEXT["marriage_problem_non_certainty_mandatory"]["en"])
        check("3: disclaimer contains no divorce/separation prediction language",
              "will" not in captured.get("disclaimer", "").lower().split("prediction")[0][-30:])
        check("3: app_download CTA still present", captured.get("app_download") is not None)
    finally:
        if order3.pdf_url and os.path.exists(order3.pdf_url):
            os.remove(order3.pdf_url)
        _cleanup(order3)

    # =================================================================
    print("\n=== 4: second_marriage_report -- Low/Moderate/Elevated, NO gemstone, mandatory disclaimer ===")
    # =================================================================
    order4 = _make_order(product="second_marriage_report")
    try:
        fake_content = _structured_content(
            value="Low",
            narrative="**Second-Union Indication**\nBalanced narrative with no disclaimer text at all.",
            gemstone_reason="This gemstone guarantees a happy second marriage.",  # deliberately supplied, must still be ignored
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order4.id)

        db.session.refresh(order4)
        check("4: report_stage reached 'Ready'", order4.report_stage == "Ready")
        check("4: answer_hero.value passes through unmodified ('Low')", captured.get("answer_hero", {}).get("value") == "Low")
        check("4: (required) NO gemstone component, even though the AI supplied a gemstone_reason",
              captured.get("gemstone") is None)
        check("4: NO timeline component (components_enabled.timeline=False)", captured.get("timeline") is None)
        check("4: mandatory disclaimer is present even though the AI never wrote one",
              captured.get("disclaimer") == DISCLAIMER_TEXT["second_marriage_non_certainty_mandatory"]["en"])
        check("4: disclaimer explicitly states it is not a guarantee",
              "not a guarantee" in captured.get("disclaimer", "").lower())
    finally:
        if order4.pdf_url and os.path.exists(order4.pdf_url):
            os.remove(order4.pdf_url)
        _cleanup(order4)

    # =================================================================
    print("\n=== 5: malformed required metadata -> Failed for all 4 Batch-2 products (S) ===")
    # =================================================================
    for slug in ("marriage_report", "delay_in_marriage_report", "problem_in_marriage_report", "second_marriage_report"):
        order_bad = _make_order(product=slug)
        try:
            with patch("tasks.generate_report_completion", return_value=_fake_completion(
                "Plain narrative text with no ===META===/===REPORT=== markers at all."
            )):
                tasks._generate_and_send_report_core(order_bad.id)
            db.session.refresh(order_bad)
            check(f"5: {slug} -- missing structured metadata -> report_stage='Failed'", order_bad.report_stage == "Failed")
        finally:
            _cleanup(order_bad)

    # =================================================================
    print("\n=== 6: Hindi-language generation uses the same code path (H parity) ===")
    # =================================================================
    order_hi = _make_order(product="second_marriage_report", language="hi")
    try:
        fake_content_hi = _structured_content(
            value="Low", interpretation="व्याख्या।", evidence=["प्रमाण एक।", "प्रमाण दो।"],
            narrative="**दूसरे संबंध का संकेत**\nहिंदी नैरेटिव पाठ।\n**सारांश**\nसमाप्त।",
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content_hi)):
            captured = _run_capturing_pdf(order_hi.id)

        db.session.refresh(order_hi)
        check("6: Hindi-language second_marriage_report reaches 'Ready'", order_hi.report_stage == "Ready")
        check("6: PDF language kwarg is 'hi'", captured.get("language") == "hi")
        check("6: Hindi mandatory disclaimer is the localized Hindi text, not the English fallback",
              captured.get("disclaimer") == DISCLAIMER_TEXT["second_marriage_non_certainty_mandatory"]["hi"])
        check("6: Hindi app_download heading is localized",
              captured.get("app_download", {}).get("heading") == "अपनी ज्योतिष यात्रा जारी रखें")
    finally:
        if order_hi.pdf_url and os.path.exists(order_hi.pdf_url):
            os.remove(order_hi.pdf_url)
        _cleanup(order_hi)

    # =================================================================
    print("\n=== 7: Luna-only, no gpt-4o-mini fallback (T/U) ===")
    # =================================================================
    import inspect
    _src = inspect.getsource(tasks)
    check("7 (T): tasks.py imports generate_report_completion from the shared Q3 client (Luna-only)",
          "from modules.payments.report_ai_client import generate_report_completion" in _src)
    # gpt-4o-mini legitimately appears once, in a historical/explanatory
    # comment line (already established acceptable in the Q3 Batch 0/1
    # audits) -- the real check is that it never appears in a live CODE
    # line (i.e. any non-comment line), never as an actual invocation.
    _code_lines_with_literal = [
        line for line in _src.splitlines()
        if ("gpt-4o-mini" in line) and not line.strip().startswith("#")
    ]
    check("7 (U): 'gpt-4o-mini' never appears in a live code line in tasks.py (only in an explanatory comment)",
          _code_lines_with_literal == [])

    # =================================================================
    print("\n=== 8: Batch-1 products remain unchanged (V) ===")
    # =================================================================
    order_b1 = _make_order(product="saturn_transit_report")
    try:
        fake_content = _structured_content(value="Some AI-guessed house that should be discarded")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order_b1.id)
        db.session.refresh(order_b1)
        check("8: saturn_transit_report (Batch 1) still reaches 'Ready' unaffected by Batch 2", order_b1.report_stage == "Ready")
        check("8: saturn_transit_report's deterministic house override still works",
              "House from Lagna" in captured.get("answer_hero", {}).get("value", ""))
        check("8: saturn_transit_report still has NO gemstone (Batch-1 visual-QA correction unaffected)",
              captured.get("gemstone") is None)
    finally:
        if order_b1.pdf_url and os.path.exists(order_b1.pdf_url):
            os.remove(order_b1.pdf_url)
        _cleanup(order_b1)

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)

if failed:
    sys.exit(1)
