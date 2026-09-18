"""
test_report_generation_q3_batch0_integration.py
-------------------------------------------------
Q3 Batch 0 -- direct integration verification against the REAL
tasks.py::_generate_and_send_report_core() code path (not just the
isolated unit modules). LOCAL Postgres DB ONLY (jyotishasha_local),
refuses to run against anything else -- same established convention as
every other test_report_platform_*.py file this session.

No real OpenAI/Luna call -- tasks.generate_report_completion is
monkeypatched throughout.

Covers:
  G. A Q3-enabled product (simulated by monkeypatching tasks.
     get_product_intelligence for this test only -- no real product is
     q3_enabled=True yet) whose AI response has malformed/incomplete
     structured metadata: generation FAILS through the existing
     report_stage="Failed" path. It does NOT silently fall back to
     narrative-only (Q3 Batch 0 correction #1, locked).
  H. A non-Q3-enabled product (the real, current state of all 25
     registry entries) with a normal narrative-only AI response:
     generation completes exactly as before Batch 0 (report_stage=
     "Ready", pdf_url set) -- confirms staged migration is safe.
  M. No PII (name/email/DOB/TOB/POB), no prompt text, and no AI
     response text ever reaches the properties dict passed to
     record_event() for the report_generation_completed event -- only
     model/token-count/duration/report_type/structured_metadata_valid.
  N. Real (UNMOCKED) activity_events.sanitize_properties() pipeline:
     none of the 6 new Q3 Batch 0 properties are silently dropped.
     This is a deliberate, dedicated regression guard for a real bug
     found while writing this exact test file -- "input_tokens"/
     "output_tokens"/"total_tokens" collided with activity_events' own
     _FORBIDDEN_KEY_SUBSTRINGS denylist ("token" is forbidden there,
     correctly, to block real auth/session tokens) and were silently
     dropped even though they were in the schema's own allowlist. Test
     M alone would NOT have caught this, because it mocks record_event
     directly and never exercises the real sanitize_properties() call
     -- this section exists specifically because that gap was found.
"""

import os
import sys
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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
from modules.payments.report_product_intelligence import ProductIntelligence  # noqa: E402
from modules.activity_events.event_schemas import sanitize_properties  # noqa: E402

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


def _fake_completion(content, model="gpt-5.6-luna", input_tokens=100, output_tokens=200, total_tokens=300, duration_seconds=1.5):
    return ReportAICompletion(
        content=content, model=model,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        duration_seconds=duration_seconds,
    )


def _make_order(**overrides):
    values = dict(
        name="Q3 Batch0 Test", email="q3batch0test@example.com",
        product="property_report", dob="1990-06-15", tob="10:30", pob="Delhi, India",
        status="PAID", payment_status="PAID", report_stage="Pending",
        latitude="28.6139", longitude="77.2090", language="en",
    )
    values.update(overrides)
    order = Order(**values)
    db.session.add(order)
    db.session.commit()
    return order


def _cleanup(order_id):
    o = Order.query.get(order_id)
    if o is not None:
        db.session.delete(o)
        db.session.commit()


with app.app_context():
    current_db = db.session.execute(text("SELECT current_database()")).scalar()
    print(f"Connected to database: {current_db}")
    assert current_db == "jyotishasha_local"

    # =============================================================
    print("\n=== G: Q3-enabled product with malformed metadata -> Failed, never a silent degrade ===")
    # =============================================================
    order_g = _make_order(product="startup_suggestion_report")
    try:
        fake_intel_missing_meta = ProductIntelligence(
            report_slug="startup_suggestion_report", generator="standard_v1",
            q3_enabled=True,  # simulated -- no real product is enabled yet
            hero_value_source="ai",
            required_hero_fields=("label", "value", "interpretation", "evidence"),
            relevant_houses=(), relevant_planets=(), required_context_keys=(),
            components_enabled={}, gemstone_policy="optional", disclaimer_type="general",
        )
        with patch("tasks.get_product_intelligence", return_value=fake_intel_missing_meta), \
             patch("tasks.generate_report_completion", return_value=_fake_completion(
                 "Just plain narrative text with no ===META===/===REPORT=== markers at all."
             )):
            tasks._generate_and_send_report_core(order_g.id)

        db.session.refresh(order_g)
        check("G: report_stage is 'Failed' (never 'Ready') when required structured metadata is missing",
              order_g.report_stage == "Failed")
        check("G: pdf_url was never set for a Q3-enabled product's failed generation",
              order_g.pdf_url is None)
    finally:
        _cleanup(order_g.id)

    order_g2 = _make_order(product="startup_suggestion_report")
    try:
        fake_intel_incomplete_hero = ProductIntelligence(
            report_slug="startup_suggestion_report", generator="standard_v1",
            q3_enabled=True,
            hero_value_source="ai",
            required_hero_fields=("label", "value", "interpretation", "evidence"),
            relevant_houses=(), relevant_planets=(), required_context_keys=(),
            components_enabled={}, gemstone_policy="optional", disclaimer_type="general",
        )
        malformed_content = (
            '===META===\n'
            '{"answer_hero": {"label": "Startup Outlook"}}\n'  # missing value/interpretation/evidence
            '===REPORT===\n'
            '**Business Orientation**\nSome narrative text.\n'
        )
        with patch("tasks.get_product_intelligence", return_value=fake_intel_incomplete_hero), \
             patch("tasks.generate_report_completion", return_value=_fake_completion(malformed_content)):
            tasks._generate_and_send_report_core(order_g2.id)

        db.session.refresh(order_g2)
        check("G: report_stage is 'Failed' when structured metadata is present but missing required hero fields",
              order_g2.report_stage == "Failed")
    finally:
        _cleanup(order_g2.id)

    # =============================================================
    print("\n=== H: non-Q3-enabled product continues narrative-only behavior, unchanged ===")
    # =============================================================
    order_h = _make_order(product="property_report")
    try:
        # Q3 Batch 5 (FINAL) completed the migration -- ALL 25 products
        # are now genuinely q3_enabled=True, so no real product can
        # demonstrate the legacy narrative-only path anymore. This
        # simulates a hypothetical q3_enabled=False product the same
        # way tests G/G2 above already simulate a hypothetical
        # q3_enabled=True one -- proving the legacy code path itself
        # still exists and still works, permanently immune to any
        # future batch enabling more products (this is exactly the
        # staleness that hit the previous two choices, startup_
        # suggestion_report then property_report, as each was enabled
        # by a later batch).
        fake_intel_legacy = ProductIntelligence(
            report_slug="property_report", generator="standard_v1",
            q3_enabled=False,  # simulated -- every real product is enabled today
            hero_value_source="ai",
            required_hero_fields=("label", "value", "interpretation", "evidence"),
            relevant_houses=(), relevant_planets=(), required_context_keys=(),
            components_enabled={}, gemstone_policy="optional", disclaimer_type="general",
        )
        with patch("tasks.get_product_intelligence", return_value=fake_intel_legacy), \
             patch("tasks.generate_report_completion", return_value=_fake_completion(
            "**Business Orientation**\nA full narrative report with no structured metadata at all, "
            "exactly like every real report generated before Q3 Batch 0.\n\n**Summary**\nConclusion text."
        )):
            tasks._generate_and_send_report_core(order_h.id)

        db.session.refresh(order_h)
        check("H: report_stage is 'Ready' for a non-Q3-enabled product (unchanged legacy behavior)",
              order_h.report_stage == "Ready")
        check("H: pdf_url was set", bool(order_h.pdf_url))
        check("H: email_status reached a real terminal SMTP-attempt state (SENT or FAILED, never NOT_ATTEMPTED)",
              order_h.email_status in ("SENT", "FAILED"))
    finally:
        if order_h.pdf_url and os.path.exists(order_h.pdf_url):
            os.remove(order_h.pdf_url)
        _cleanup(order_h.id)

    # =============================================================
    print("\n=== M: no PII/prompt/response content in observability properties ===")
    # =============================================================
    order_m = _make_order(
        product="property_report",
        name="Sensitive Name M", email="sensitive.pii.m@example.com",
        dob="1985-01-01", tob="09:15", pob="Sensitive City, India",
    )
    captured_events = []
    try:
        def _capture_record_event(**kwargs):
            captured_events.append(kwargs)
            return None

        secret_prompt_text = "SECRET_PROMPT_MARKER_Sensitive Name M was born on 1985-01-01"
        secret_response_text = "**Business Orientation**\nSECRET_RESPONSE_MARKER narrative for Sensitive Name M."

        # Same simulated-legacy-product pattern as test H above (Q3
        # Batch 5 completed the migration -- no real product is
        # q3_enabled=False anymore) -- this response has no ===META===/
        # ===REPORT=== markers at all, matching the legacy narrative-
        # only contract this test is actually about.
        fake_intel_legacy_m = ProductIntelligence(
            report_slug="property_report", generator="standard_v1",
            q3_enabled=False,
            hero_value_source="ai",
            required_hero_fields=("label", "value", "interpretation", "evidence"),
            relevant_houses=(), relevant_planets=(), required_context_keys=(),
            components_enabled={}, gemstone_policy="optional", disclaimer_type="general",
        )
        with patch("tasks.get_product_intelligence", return_value=fake_intel_legacy_m), \
             patch("tasks.generate_report_completion", return_value=_fake_completion(secret_response_text)), \
             patch("tasks.record_event", side_effect=_capture_record_event):
            tasks._generate_and_send_report_core(order_m.id)

        completed_events = [e for e in captured_events if e.get("event_name") == "report_generation_completed"]
        check("M: a report_generation_completed event was actually emitted", len(completed_events) == 1)

        if completed_events:
            props = completed_events[0].get("properties", {})
            check("M: properties contains a model field", "model" in props)
            check("M: properties contains token counts under their renamed, non-'token'-substring keys (ai_input_units/ai_output_units/ai_total_units)",
                  "ai_input_units" in props and "ai_output_units" in props and "ai_total_units" in props)
            check("M: (regression guard) the old '*_tokens' key names are NOT used -- they collide with activity_events' own forbidden-substring denylist and would be silently dropped",
                  "input_tokens" not in props and "output_tokens" not in props and "total_tokens" not in props)
            check("M: properties contains duration_seconds", "duration_seconds" in props)
            check("M: NO customer name anywhere in the emitted properties", "Sensitive Name M" not in str(props))
            check("M: NO customer email anywhere in the emitted properties", "sensitive.pii.m@example.com" not in str(props))
            check("M: NO DOB/TOB/POB anywhere in the emitted properties", "1985-01-01" not in str(props) and "Sensitive City" not in str(props))
            check("M: NO prompt content anywhere in the emitted properties", "SECRET_PROMPT_MARKER" not in str(props))
            check("M: NO AI response content anywhere in the emitted properties", "SECRET_RESPONSE_MARKER" not in str(props))
            check("M: the entire event kwargs (not just properties) also carry no PII -- only order_id as entity_id",
                  "Sensitive Name M" not in str(completed_events[0]) and "sensitive.pii.m@example.com" not in str(completed_events[0]))
    finally:
        db.session.refresh(order_m)
        if order_m.pdf_url and os.path.exists(order_m.pdf_url):
            os.remove(order_m.pdf_url)
        _cleanup(order_m.id)

    # =============================================================
    print("\n=== N: real (UNMOCKED) sanitize_properties() preserves all 6 new properties ===")
    # =============================================================
    real_input = {
        "report_type": "startup_suggestion_report",
        "model": "gpt-5.6-luna",
        "ai_input_units": 100,
        "ai_output_units": 200,
        "ai_total_units": 300,
        "duration_seconds": 1.5,
        "structured_metadata_valid": True,
    }
    clean, dropped = sanitize_properties("report_generation_completed", 1, real_input)
    check("N: nothing was dropped by the real schema/denylist pipeline", dropped == [])
    check("N: model preserved", clean.get("model") == "gpt-5.6-luna")
    check("N: ai_input_units preserved (renamed from the colliding 'input_tokens')", clean.get("ai_input_units") == 100)
    check("N: ai_output_units preserved", clean.get("ai_output_units") == 200)
    check("N: ai_total_units preserved", clean.get("ai_total_units") == 300)
    check("N: duration_seconds preserved", clean.get("duration_seconds") == 1.5)
    check("N: structured_metadata_valid preserved", clean.get("structured_metadata_valid") is True)

    # Explicit proof of the bug this section guards against: the OLD
    # key names really do get silently dropped by the real pipeline,
    # confirming the rename above was necessary, not cosmetic.
    old_names_input = {"report_type": "x", "input_tokens": 1, "output_tokens": 2, "total_tokens": 3}
    _, old_dropped = sanitize_properties("report_generation_completed", 1, old_names_input)
    check("N: (proof) the OLD '*_tokens' key names ARE silently dropped by the real pipeline -- confirms the rename was required, not optional",
          set(old_dropped) == {"input_tokens", "output_tokens", "total_tokens"})

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)

if failed:
    sys.exit(1)
