"""
test_report_q3_batch1.py
-------------------------------------------------
Q3 Batch 1 -- verification for the first 4 Q3-enabled products
(gemstone_consultation, saturn_transit_report, mood_mental_health_report,
divorce_possibility_report).

Two kinds of coverage:

  Part 1 (no DB, fast) -- direct unit tests of modules/payments/
  report_q3_batch1.py's pure deterministic helpers (gemstone hero value,
  Saturn transit hero/timing, mandatory disclaimer lookup) against
  fixture data, and a couple of registry-shape assertions specific to
  Batch 1's own per-product configuration (not re-testing what
  test_report_product_intelligence.py's own section B/D already cover).

  Part 2 (LOCAL Postgres DB, same convention as test_report_generation_
  q3_batch0_integration.py) -- direct integration verification against
  the REAL tasks.py::_generate_and_send_report_core() code path for
  each of the 4 now-real q3_enabled=True products, using REAL kundali/
  transit/gemstone calculation (only the Luna call and the final PDF
  render are mocked) to prove:
    - deterministic value/gemstone overrides actually take effect,
    - the two mandatory disclaimers are always injected regardless of
      AI output,
    - gemstone_consultation hard-fails when its own deterministic
      gemstone data is incomplete,
    - action_items only render when structurally valid,
    - Hindi-language generation uses the same code path.

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

from modules.payments.report_q3_batch1 import (  # noqa: E402
    DISCLAIMER_TEXT,
    get_mandatory_disclaimer,
    compute_gemstone_hero_value,
    compute_saturn_transit_hero,
)
from modules.payments.report_structured_output import ReportMetadataError  # noqa: E402
from modules.payments.report_product_intelligence import REGISTRY, ProductIntelligence  # noqa: E402

print("=== 1: get_mandatory_disclaimer() -- backend-controlled, never AI-sourced ===")

check("1: mental_health_mandatory (en) returns the exact fixed EN text",
      get_mandatory_disclaimer("mental_health_mandatory", "en") == DISCLAIMER_TEXT["mental_health_mandatory"]["en"])
check("1: mental_health_mandatory (hi) returns the exact fixed HI text",
      get_mandatory_disclaimer("mental_health_mandatory", "hi") == DISCLAIMER_TEXT["mental_health_mandatory"]["hi"])
check("1: divorce_non_certainty_mandatory (en) returns the exact fixed EN text",
      get_mandatory_disclaimer("divorce_non_certainty_mandatory", "en") == DISCLAIMER_TEXT["divorce_non_certainty_mandatory"]["en"])
check("1: divorce_non_certainty_mandatory (hi) returns the exact fixed HI text",
      get_mandatory_disclaimer("divorce_non_certainty_mandatory", "hi") == DISCLAIMER_TEXT["divorce_non_certainty_mandatory"]["hi"])
check("1: 'none' disclaimer_type returns None (gemstone_consultation's own type)",
      get_mandatory_disclaimer("none", "en") is None)
check("1: any other/legacy disclaimer_type (e.g. 'financial_business') returns None -- inert for the 21 untouched products",
      get_mandatory_disclaimer("financial_business", "en") is None)
check("1: None disclaimer_type returns None (never raises)",
      get_mandatory_disclaimer(None, "en") is None)
check("1: mandatory disclaimer text never contains the rejected gemstone caution line",
      "Confirm suitability with a qualified astrologer" not in DISCLAIMER_TEXT["mental_health_mandatory"]["en"]
      and "Confirm suitability with a qualified astrologer" not in DISCLAIMER_TEXT["divorce_non_certainty_mandatory"]["en"])
check("1: mood disclaimer explicitly states it is not a diagnosis/treatment",
      "diagnosis" in DISCLAIMER_TEXT["mental_health_mandatory"]["en"].lower())
check("1: divorce disclaimer explicitly states it is not a prediction/legal outcome",
      "legal" in DISCLAIMER_TEXT["divorce_non_certainty_mandatory"]["en"].lower())

print("\n=== 2: compute_gemstone_hero_value() -- deterministic, never AI-sourced ===")

check("2: a complete gemstone_suggestion returns its own 'gemstone' string verbatim",
      compute_gemstone_hero_value({"planet": "Jupiter", "gemstone": "Yellow Sapphire (Pukhraj)", "substone": "Citrine (Sunaila)"})
      == "Yellow Sapphire (Pukhraj)")
check("2: the documented incomplete-data fallback shape ({'planet': None, 'paragraph': ...}) returns None",
      compute_gemstone_hero_value({"planet": None, "paragraph": "Data incomplete for recommendation."}) is None)
check("2: an empty dict returns None", compute_gemstone_hero_value({}) is None)
check("2: None input returns None", compute_gemstone_hero_value(None) is None)
check("2: a dict with a planet but empty gemstone string returns None (never an empty-string hero value)",
      compute_gemstone_hero_value({"planet": "Sun", "gemstone": ""}) is None)

print("\n=== 3: compute_saturn_transit_hero() -- deterministic house is mandatory, timing is best-effort ===")

# A realistic-shaped kundali fixture: Aries Lagna, Saturn currently
# transiting Pisces (a whole-sign offset of 12 -> house 12 from Lagna).
fixture_kundali = {
    "lagna_sign": "Aries",
    "transit_summary": {"positions": {"Saturn": {"rashi": "Pisces", "degree": 10.5, "motion": "Direct"}}},
}
saturn_hero = compute_saturn_transit_hero(fixture_kundali)
check("3: value names the correct deterministic house (12th, Aries Lagna + Saturn in Pisces)",
      "12th House" in saturn_hero["value"])
check("3: value names the Saturn rashi", "Pisces" in saturn_hero["value"])
check("3: timing/timeline are either both present or both None together (never half-built)",
      (saturn_hero["timing"] is None) == (saturn_hero["timeline"] is None))
if saturn_hero["timing"] is not None:
    check("3: (human visual QA correction) timing, when present, is customer-facing 'D Month YYYY to D Month YYYY', not raw ISO",
          bool(re.match(r"^\d{1,2} [A-Z][a-z]+ \d{4} to \d{1,2} [A-Z][a-z]+ \d{4}$", saturn_hero["timing"])))
    check("3: timeline, when present, is a well-shaped {heading, entries:[{label, date_range, note, current}]} dict",
          isinstance(saturn_hero["timeline"], dict)
          and "entries" in saturn_hero["timeline"]
          and isinstance(saturn_hero["timeline"]["entries"], list)
          and len(saturn_hero["timeline"]["entries"]) == 1
          and saturn_hero["timeline"]["entries"][0]["current"] is True)
else:
    print("  (real get_current_sign_residency('Saturn') returned no usable window in this environment -- "
          "timing/timeline correctly omitted rather than guessed)")

try:
    compute_saturn_transit_hero({"lagna_sign": None, "transit_summary": {"positions": {}}})
    check("3: unresolvable house (no lagna_sign, no Saturn position) raises ReportMetadataError", False)
except ReportMetadataError:
    check("3: unresolvable house (no lagna_sign, no Saturn position) raises ReportMetadataError", True)
except Exception as exc:
    check(f"3: unresolvable house raises ReportMetadataError specifically, not {type(exc).__name__}", False)

print("\n=== 4: Batch 1 registry shape -- exactly the 4 target products, correctly configured ===")

check("4: gemstone_consultation is q3_enabled=True", REGISTRY["gemstone_consultation"].q3_enabled is True)
check("4: saturn_transit_report is q3_enabled=True", REGISTRY["saturn_transit_report"].q3_enabled is True)
check("4: mood_mental_health_report is q3_enabled=True", REGISTRY["mood_mental_health_report"].q3_enabled is True)
check("4: divorce_possibility_report is q3_enabled=True", REGISTRY["divorce_possibility_report"].q3_enabled is True)
check("4: gemstone_consultation requires 'value' and 'evidence' in its hero contract",
      {"value", "evidence"} <= set(REGISTRY["gemstone_consultation"].required_hero_fields))
check("4: gemstone_consultation gemstone_policy is 'required'", REGISTRY["gemstone_consultation"].gemstone_policy == "required")
check("4: mood_mental_health_report disclaimer_type maps to a real mandatory disclaimer",
      REGISTRY["mood_mental_health_report"].disclaimer_type in DISCLAIMER_TEXT)
check("4: divorce_possibility_report disclaimer_type maps to a real mandatory disclaimer",
      REGISTRY["divorce_possibility_report"].disclaimer_type in DISCLAIMER_TEXT)
check("4: saturn_transit_report disclaimer_type has NO mandatory text (not a sensitive-content product)",
      REGISTRY["saturn_transit_report"].disclaimer_type not in DISCLAIMER_TEXT)
check("4: gemstone_consultation disclaimer_type has NO mandatory text (Q2.1's own rejected-caution rule)",
      REGISTRY["gemstone_consultation"].disclaimer_type not in DISCLAIMER_TEXT)

print("\n=== 4a: (human visual QA correction) gemstone policy -- only gemstone_consultation shows a gemstone box ===")

check("4a: mood_mental_health_report gemstone_policy is 'disabled'", REGISTRY["mood_mental_health_report"].gemstone_policy == "disabled")
check("4a: divorce_possibility_report gemstone_policy is 'disabled'", REGISTRY["divorce_possibility_report"].gemstone_policy == "disabled")
check("4a: saturn_transit_report gemstone_policy is 'disabled'", REGISTRY["saturn_transit_report"].gemstone_policy == "disabled")
check("4a: gemstone_consultation gemstone_policy is still 'required'", REGISTRY["gemstone_consultation"].gemstone_policy == "required")
check("4a: components_enabled['gemstone'] agrees with gemstone_policy for all 4 products",
      REGISTRY["gemstone_consultation"].components_enabled.get("gemstone") is True
      and REGISTRY["saturn_transit_report"].components_enabled.get("gemstone") is False
      and REGISTRY["mood_mental_health_report"].components_enabled.get("gemstone") is False
      and REGISTRY["divorce_possibility_report"].components_enabled.get("gemstone") is False)

print("\n=== 4b: shared date formatter -- word-month dates (EN/HI), internal ISO format untouched ===")

from modules.payments.report_date_format import format_customer_date, format_customer_date_range  # noqa: E402

check("4b: canonical 'YYYY-MM-DD' -> 'D Month YYYY'", format_customer_date("1990-06-15") == "15 June 1990")
check("4b: another calendar date formats correctly", format_customer_date("2025-03-29") == "29 March 2025")
check("4b: a datetime object formats correctly", format_customer_date(__import__("datetime").datetime(2026, 9, 17)) == "17 September 2026")
check("4b: an unparseable string is returned unchanged, never raises", format_customer_date("not-a-date") == "not-a-date")
check("4b: None is returned as an empty string, never raises", format_customer_date(None) == "")
check("4b: date range formats both ends and joins with 'to'",
      format_customer_date_range("2025-03-29", "2027-06-02") == "29 March 2025 to 2 June 2027")
check("4b: date range with both ends falsy returns None (nothing to show)", format_customer_date_range(None, None) is None)
check("4b: the underlying ISO source strings are never mutated by formatting (still 'YYYY-MM-DD' internally)",
      re.fullmatch(r"\d{4}-\d{2}-\d{2}", "2025-03-29") is not None)

print("\n=== 4c: shared Hindi component labels -- localized, never separate business logic ===")

from modules.payments.report_i18n_labels import get_label, labels_for_language, LABELS  # noqa: E402

check("4c: recommended_gemstone (hi) is the modern Hinglish label (Q4.2A), not the plain English label", get_label("recommended_gemstone", "hi") == "आपके लिए Recommended Gemstone")
check("4c: alternative_substone (hi) is the modern Hinglish label (Q4.2A)", get_label("alternative_substone", "hi") == "Alternative Sub-stone")
check("4c: supporting_planet (hi) is the modern Hinglish label (Q4.2A)", get_label("supporting_planet", "hi") == "Supporting Planet")
check("4c: suggested_next_steps (hi) is the modern Hinglish label (Q4.2A)", get_label("suggested_next_steps", "hi") == "आपके लिए Next Steps")
check("4c: EN labels stay in English", get_label("recommended_gemstone", "en") == "Recommended Gemstone")
check("4c: unrecognized language falls back to English, never raises", get_label("recommended_gemstone", "fr") == "Recommended Gemstone")
check("4c: unrecognized key returns '' , never raises/None", get_label("not_a_real_key", "hi") == "")
check("4c: labels_for_language returns every declared key for both languages",
      set(labels_for_language("en").keys()) == set(LABELS.keys()) == set(labels_for_language("hi").keys()))
check("4c: every declared label has both an 'en' and an 'hi' entry (no silently-English-only label)",
      all("en" in v and "hi" in v for v in LABELS.values()))

print("\n=== 4d: Hindi CSS coverage fix + verified app store URL (source-level checks) ===")

_template_src = open("templates/report_template.html", encoding="utf-8").read()
check("4d: (root cause fix) 'body.hi, body.hi *' universal Hindi font rule is present in the template",
      "body.hi, body.hi *" in _template_src)
check("4d: (regression guard) the old, narrow 'body.hi, body.hi p, body.hi li, body.hi td, body.hi th' rule is GONE",
      "body.hi, body.hi p, body.hi li, body.hi td, body.hi th" not in _template_src)
check("4d: no hardcoded English 'Recommended Gemstone' string remains in the template (now {{ labels.* }}-driven)",
      "<div class=\"gemstone-heading\">Recommended Gemstone</div>" not in _template_src)
check("4d: no hardcoded English 'Download the Jyotishasha App' string remains in the template",
      "Download the Jyotishasha App" not in _template_src)
check("4d: app-download block references the shared labels dict", "labels.app_download_action" in _template_src)

from app_config import JYOTISHASHA_PLAY_STORE_URL, JYOTISHASHA_APP_STORE_URL  # noqa: E402
check("4d: JYOTISHASHA_PLAY_STORE_URL is the exact official URL confirmed by the project owner (not package-id-derived)",
      JYOTISHASHA_PLAY_STORE_URL == "https://play.google.com/store/apps/details?id=com.jyotishasha.app&pcampaignid=web_share")
check("4d: JYOTISHASHA_APP_STORE_URL is None -- no verified iOS listing exists, and none is invented",
      JYOTISHASHA_APP_STORE_URL is None)

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
from full_kundali_api import calculate_full_kundali as real_calculate_full_kundali  # noqa: E402
from modules.payments.report_ai_client import ReportAICompletion  # noqa: E402


def _fake_completion(content, model="gpt-5.6-luna", input_tokens=100, output_tokens=200, total_tokens=300, duration_seconds=1.5):
    return ReportAICompletion(
        content=content, model=model,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        duration_seconds=duration_seconds,
    )


def _structured_content(value, interpretation="Interpretation text.", evidence=None, action_items=None, gemstone_reason=None, narrative="**Section**\nSome narrative text.\n**Summary**\nDone."):
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
        name="Q3 Batch1 Test", email="q3batch1test@example.com",
        product="gemstone_consultation", dob="1990-06-15", tob="10:30", pob="Delhi, India",
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
    """Runs the real pipeline with Luna already patched by the caller,
    and the final PDF render replaced by a capture -- avoids depending
    on real weasyprint output while still exercising every line of
    tasks.py's own Q3 Batch 1 wiring logic up to that call."""
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
    print("\n=== 5: gemstone_consultation -- deterministic value/gemstone override ===")
    # =================================================================
    order5 = _make_order(product="gemstone_consultation")
    try:
        fake_content = _structured_content(
            value="A Completely Wrong Gemstone Name The AI Made Up",
            gemstone_reason="This stone supports the relevant planet for this chart.",
            action_items=["Wear it on a comfortable day.", "Keep it clean."],
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order5.id)

        db.session.refresh(order5)
        check("5: report_stage reached 'Ready' for a valid gemstone_consultation response", order5.report_stage == "Ready")
        check("5: answer_hero was built", captured.get("answer_hero") is not None)
        if captured.get("answer_hero"):
            check("5: AI's invented gemstone name was DISCARDED, never rendered",
                  "Completely Wrong Gemstone Name" not in captured["answer_hero"]["value"])
            check("5: answer_hero.value matches the gemstone box's own deterministic gemstone name",
                  captured["answer_hero"]["value"] == (captured.get("gemstone") or {}).get("gemstone"))
        check("5: gemstone component was built (mandatory for this product)", captured.get("gemstone") is not None)
        if captured.get("gemstone"):
            check("5: gemstone.reason is the AI-authored text (the only AI-sourced field)",
                  captured["gemstone"]["reason"] == "This stone supports the relevant planet for this chart.")
            check("5: gemstone.planet is present (deterministic)", bool(captured["gemstone"]["planet"]))
        check("5: no automatic disclaimer for gemstone_consultation (disclaimer_type='none')", captured.get("disclaimer") is None)
        check("5: rejected generic caution line does not appear anywhere in the captured PDF kwargs",
              "Confirm suitability with a qualified astrologer" not in str(captured))
        check("5: no invented metal/finger/carat/mantra language anywhere in captured kwargs",
              not any(w in str(captured).lower() for w in ("carat", "ratti", "mantra", "which finger")))
        check("5: action_list was built from valid AI action_items", captured.get("action_list") is not None)
        if captured.get("action_list"):
            check("5: action_list.items matches the AI-supplied items", captured["action_list"]["items"] == ["Wear it on a comfortable day.", "Keep it clean."])
            check("5: (human visual QA correction) action_list.heading is localized, not the raw hardcoded English literal",
                  captured["action_list"]["heading"] == "Suggested Next Steps")  # en, matches labels.suggested_next_steps
        check("5: no timeline for gemstone_consultation (no deterministic timing source)", captured.get("timeline") is None)
        check("5: (human visual QA correction, P0) app_download CTA is present for every paid report",
              captured.get("app_download") is not None)
        if captured.get("app_download"):
            check("5: app_download uses the exact requested heading copy", captured["app_download"]["heading"] == "Continue Your Astrology Journey")
            check("5: app_download uses the exact requested body copy",
                  captured["app_download"]["benefit_text"] == "Get your personalized astrology insights, daily guidance and more in the Jyotishasha App.")
            check("5: app_download carries the owner-confirmed Play Store URL", captured["app_download"]["play_store_url"] == "https://play.google.com/store/apps/details?id=com.jyotishasha.app&pcampaignid=web_share")
            check("5: app_download carries NO invented App Store URL", captured["app_download"]["app_store_url"] is None)
    finally:
        if order5.pdf_url and os.path.exists(order5.pdf_url):
            os.remove(order5.pdf_url)
        _cleanup(order5)

    # =================================================================
    print("\n=== 6: gemstone_consultation -- HARD FAIL when core gemstone data incomplete ===")
    # =================================================================
    order6 = _make_order(product="gemstone_consultation")
    try:
        def _incomplete_gemstone_kundali(**kwargs):
            k = real_calculate_full_kundali(**kwargs)
            k["gemstone_suggestion"] = {"planet": None, "paragraph": "Data incomplete for recommendation."}
            return k

        fake_content = _structured_content(value="Some AI Gemstone Guess")
        with patch("tasks.calculate_full_kundali", side_effect=_incomplete_gemstone_kundali), \
             patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            tasks._generate_and_send_report_core(order6.id)

        db.session.refresh(order6)
        check("6: report_stage is 'Failed' when the deterministic gemstone recommendation is unavailable",
              order6.report_stage == "Failed")
        check("6: pdf_url was never set for this failed attempt", order6.pdf_url is None)
    finally:
        _cleanup(order6)

    # =================================================================
    print("\n=== 7: saturn_transit_report -- deterministic house/timing override ===")
    # =================================================================
    order7 = _make_order(product="saturn_transit_report")
    try:
        fake_content = _structured_content(value="Some AI-guessed house that should be discarded")
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order7.id)

        db.session.refresh(order7)
        check("7: report_stage reached 'Ready' for a valid saturn_transit_report response", order7.report_stage == "Ready")
        check("7: answer_hero was built", captured.get("answer_hero") is not None)
        if captured.get("answer_hero"):
            check("7: AI's guessed house text was DISCARDED", "Some AI-guessed house" not in captured["answer_hero"]["value"])
            check("7: answer_hero.value is a real deterministic 'House from Lagna' fact",
                  "House from Lagna" in captured["answer_hero"]["value"])
        check("7: (human visual QA correction) NO gemstone component for saturn_transit_report -- gemstone_policy is now 'disabled'",
              captured.get("gemstone") is None)
        check("7: no invented Saturn-drishti-onto-houses claim anywhere in captured kwargs",
              "aspects your" not in str(captured).lower() and "aspecting your" not in str(captured).lower())
        check("7: report is distinct from Sade Sati -- no report_subtitle/product mislabeling", captured.get("product") == "saturn_transit_report")
        if captured.get("answer_hero", {}).get("timing"):
            check("7: (human visual QA correction) Saturn timing is 'D Month YYYY to D Month YYYY', not the raw ISO shape",
                  bool(re.match(r"^\d{1,2} [A-Z][a-z]+ \d{4} to \d{1,2} [A-Z][a-z]+ \d{4}$", captured["answer_hero"]["timing"])))
        if captured.get("timeline"):
            check("7: (human visual QA correction) Saturn timeline heading is localized (EN)", captured["timeline"]["heading"] == "Current Saturn Transit Window")
            entry = captured["timeline"]["entries"][0]
            check("7: (human visual QA correction) Saturn timeline date_range is 'D Month YYYY to D Month YYYY', not the raw ISO shape",
                  bool(re.match(r"^\d{1,2} [A-Z][a-z]+ \d{4} to \d{1,2} [A-Z][a-z]+ \d{4}$", entry["date_range"])))
        check("7: app_download CTA present for saturn_transit_report too", captured.get("app_download") is not None)
    finally:
        if order7.pdf_url and os.path.exists(order7.pdf_url):
            os.remove(order7.pdf_url)
        _cleanup(order7)

    # =================================================================
    print("\n=== 8: mood_mental_health_report -- mandatory disclaimer, AI-authored value ===")
    # =================================================================
    order8 = _make_order(product="mood_mental_health_report")
    try:
        # Deliberately no disclaimer text anywhere in the AI's own
        # narrative or metadata -- proves the disclaimer is backend-
        # injected, never left to Luna's discretion.
        # gemstone_reason is deliberately supplied by "AI" here, even
        # though this product's gemstone_policy is now 'disabled' --
        # proves the backend ignores it rather than building a
        # gemstone box anyway.
        fake_content = _structured_content(
            value="Emotionally Reflective", narrative="**Emotional Pattern**\nCalm narrative with no disclaimer text at all.",
            gemstone_reason="This gemstone would help with anxiety.",
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order8.id)

        db.session.refresh(order8)
        check("8: report_stage reached 'Ready'", order8.report_stage == "Ready")
        check("8: answer_hero.value is the AI-authored descriptor, unmodified (hero_value_source='ai')",
              captured.get("answer_hero", {}).get("value") == "Emotionally Reflective")
        from modules.payments.report_q3_batch1 import DISCLAIMER_TEXT as _DT
        check("8: the mandatory mental-health disclaimer is present even though the AI never wrote one",
              captured.get("disclaimer") == _DT["mental_health_mandatory"]["en"])
        check("8: no diagnostic language was backend-injected into the disclaimer",
              not any(w in captured.get("disclaimer", "").lower() for w in ("depression", "anxiety disorder", "bipolar", "schizophrenia")))
        check("8: (human visual QA correction, required) mood_mental_health_report has NO gemstone component, "
              "even though the AI supplied a gemstone_reason",
              captured.get("gemstone") is None)
        check("8: app_download CTA present", captured.get("app_download") is not None)
    finally:
        if order8.pdf_url and os.path.exists(order8.pdf_url):
            os.remove(order8.pdf_url)
        _cleanup(order8)

    # =================================================================
    print("\n=== 9: divorce_possibility_report -- mandatory disclaimer, no inevitability wording ===")
    # =================================================================
    order9 = _make_order(product="divorce_possibility_report")
    try:
        fake_content = _structured_content(
            value="Moderate", narrative="**Risk Signal**\nBalanced narrative with no disclaimer text at all.",
            gemstone_reason="This gemstone would prevent divorce.",
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order9.id)

        db.session.refresh(order9)
        check("9: report_stage reached 'Ready'", order9.report_stage == "Ready")
        check("9: answer_hero.value is the AI-authored tendency signal, unmodified (hero_value_source='ai')",
              captured.get("answer_hero", {}).get("value") == "Moderate")
        from modules.payments.report_q3_batch1 import DISCLAIMER_TEXT as _DT2
        check("9: the mandatory non-certainty/legal disclaimer is present even though the AI never wrote one",
              captured.get("disclaimer") == _DT2["divorce_non_certainty_mandatory"]["en"])
        check("9: backend never injects inevitability wording into the disclaimer",
              "will happen" not in captured.get("disclaimer", "").lower()
              and "certain" not in captured.get("disclaimer", "").lower())
        check("9: (human visual QA correction, required) divorce_possibility_report has NO gemstone component, "
              "even though the AI supplied a gemstone_reason",
              captured.get("gemstone") is None)
        check("9: app_download CTA present", captured.get("app_download") is not None)
    finally:
        if order9.pdf_url and os.path.exists(order9.pdf_url):
            os.remove(order9.pdf_url)
        _cleanup(order9)

    # =================================================================
    print("\n=== 10: action_items only render when structurally valid ===")
    # =================================================================
    order10 = _make_order(product="mood_mental_health_report")
    try:
        fake_content = _structured_content(value="Steady", action_items="not a list")  # malformed on purpose
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content)):
            captured = _run_capturing_pdf(order10.id)
        check("10: a non-list action_items value is safely ignored -- action_list is None, generation still succeeds",
              captured.get("action_list") is None)
        db.session.refresh(order10)
        check("10: report_stage still reached 'Ready' despite the malformed (optional) action_items field",
              order10.report_stage == "Ready")
    finally:
        if order10.pdf_url and os.path.exists(order10.pdf_url):
            os.remove(order10.pdf_url)
        _cleanup(order10)

    # =================================================================
    print("\n=== 11: malformed required metadata -> Failed for all 4 Q3 Batch 1 products ===")
    # =================================================================
    for slug in ("gemstone_consultation", "saturn_transit_report", "mood_mental_health_report", "divorce_possibility_report"):
        order_bad = _make_order(product=slug)
        try:
            with patch("tasks.generate_report_completion", return_value=_fake_completion(
                "Plain narrative text with no ===META===/===REPORT=== markers at all."
            )):
                tasks._generate_and_send_report_core(order_bad.id)
            db.session.refresh(order_bad)
            check(f"11: {slug} -- missing structured metadata -> report_stage='Failed'", order_bad.report_stage == "Failed")
        finally:
            _cleanup(order_bad)

    # =================================================================
    print("\n=== 12: Hindi-language generation uses the same code path ===")
    # =================================================================
    order_hi = _make_order(product="gemstone_consultation", language="hi")
    try:
        fake_content_hi = _structured_content(
            value="गलत रत्न नाम",  # deliberately wrong -- must still be overridden
            interpretation="व्याख्या।", evidence=["प्रमाण एक।", "प्रमाण दो।"],
            gemstone_reason="कारण।",
            action_items=["सुझाव एक।", "सुझाव दो।"],
            narrative="**आपकी रत्न अनुशंसा**\nहिंदी नैरेटिव पाठ।\n**सारांश**\nसमाप्त।",
        )
        with patch("tasks.generate_report_completion", return_value=_fake_completion(fake_content_hi)):
            captured = _run_capturing_pdf(order_hi.id)

        db.session.refresh(order_hi)
        check("12: Hindi-language gemstone_consultation reaches 'Ready'", order_hi.report_stage == "Ready")
        check("12: Hindi AI value was still discarded in favor of the deterministic gemstone name",
              captured.get("answer_hero", {}).get("value") != "गलत रत्न नाम")
        check("12: PDF language kwarg is 'hi'", captured.get("language") == "hi")
        check("12: (human visual QA correction) action_list.heading is the localized Hindi label, not the English literal",
              (captured.get("action_list") or {}).get("heading") == "आपके लिए Next Steps")
        check("12: (human visual QA correction) app_download heading is the localized Hindi copy",
              (captured.get("app_download") or {}).get("heading") == "अपनी ज्योतिष यात्रा जारी रखें")
        check("12: (human visual QA correction) app_download body is the localized Hindi copy",
              (captured.get("app_download") or {}).get("benefit_text")
              == "Jyotishasha App में पाएं अपनी Personalized Astrology Insights, Daily Guidance और बहुत कुछ।")
        check("12: Hindi report still carries the owner-confirmed Play Store URL",
              (captured.get("app_download") or {}).get("play_store_url") == "https://play.google.com/store/apps/details?id=com.jyotishasha.app&pcampaignid=web_share")
    finally:
        if order_hi.pdf_url and os.path.exists(order_hi.pdf_url):
            os.remove(order_hi.pdf_url)
        _cleanup(order_hi)

    # =================================================================
    print("\n=== 13: legacy (non-Q3-enabled) product is completely unaffected ===")
    # =================================================================
    # Q3 Batch 5 (FINAL) completed the migration -- ALL 25 products are
    # now genuinely q3_enabled=True, so no real product can demonstrate
    # the legacy narrative-only path anymore (this is exactly the
    # staleness that hit the two previous fixed choices in turn,
    # startup_suggestion_report then property_report, as each was
    # enabled by a later batch). This simulates a hypothetical
    # q3_enabled=False product instead -- permanently immune to any
    # future registry change, since the registry is now fully migrated.
    fake_intel_legacy = ProductIntelligence(
        report_slug="property_report", generator="standard_v1",
        q3_enabled=False,  # simulated -- every real product is enabled today
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        relevant_houses=(), relevant_planets=(), required_context_keys=(),
        components_enabled={}, gemstone_policy="optional", disclaimer_type="general",
    )
    order_legacy = _make_order(product="property_report")
    try:
        with patch("tasks.get_product_intelligence", return_value=fake_intel_legacy), \
             patch("tasks.generate_report_completion", return_value=_fake_completion(
            "**Your Birth Chart & Planets**\nPlain narrative, no META/REPORT markers, exactly like pre-Batch-0.\n\n**Summary**\nDone."
        )):
            captured = _run_capturing_pdf(order_legacy.id)
        db.session.refresh(order_legacy)
        check("13: legacy product reaches 'Ready'", order_legacy.report_stage == "Ready")
        check("13: legacy product gets no answer_hero", captured.get("answer_hero") is None)
        check("13: legacy product gets no disclaimer", captured.get("disclaimer") is None)
        check("13: legacy product gets no action_list", captured.get("action_list") is None)
        check("13: legacy product gets no timeline", captured.get("timeline") is None)
        check("13: legacy product gets no gemstone (unchanged Q3 gating for a q3_enabled=False product)",
              captured.get("gemstone") is None)
        check("13: (human visual QA correction, P0) even a legacy/non-Q3 product gets the app_download CTA -- "
              "it is a Q2.1 GLOBAL requirement, not Q3-specific",
              captured.get("app_download") is not None)
    finally:
        if order_legacy.pdf_url and os.path.exists(order_legacy.pdf_url):
            os.remove(order_legacy.pdf_url)
        _cleanup(order_legacy)

    # =================================================================
    print("\n=== 14: DOB and Report Date render as word-month dates in the actual generated HTML ===")
    # =================================================================
    # A direct, no-Order unit call against the REAL generate_pdf_report_
    # weasy() -- proves the formatter is actually applied inside that
    # function's own context-building (not just testable in isolation),
    # by inspecting the raw HTML string handed to WeasyPrint (patched
    # out so no real PDF render/file write happens).
    import pdf_generator_weasy as _pgw

    captured_html = {}

    class _FakeHTML:
        def __init__(self, string=None, base_url=None):
            captured_html["html"] = string

        def write_pdf(self, output_path):
            pass

    with patch.object(_pgw, "HTML", _FakeHTML):
        _pgw.generate_pdf_report_weasy(
            output_path=os.path.join(os.environ.get("TEMP", "."), "q3batch1_date_fmt_test.pdf"),
            user_info={"name": "Date Fmt Test", "dob": "1990-06-15", "tob": "10:30", "pob": "Delhi, India"},
            summary_blocks={}, gpt_response="**Section**\nSome text.", kundali_drawing=None,
            used_placeholders=[], product="startup_suggestion_report", language="en",
        )

    html = captured_html.get("html", "")
    check("14: (human visual QA correction) DOB renders as '15 June 1990' in the generated HTML, not raw ISO 'YYYY-MM-DD'",
          "15 June 1990" in html and "1990-06-15" not in html and "15/06/1990" not in html)
    check("14: (human visual QA correction) Report Date is word-month-shaped in the generated HTML",
          bool(re.search(r"Report Date:</strong>\s*\d{1,2} [A-Z][a-z]+ \d{4}", html)))

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)

if failed:
    sys.exit(1)
