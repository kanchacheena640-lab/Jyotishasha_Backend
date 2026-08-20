"""
test_alert_notification_content_ai.py
----------------------------------
Focused tests for the AI-content preference added to
modules/alerts/notification_content_adapter.py::
build_alert_notification_content() -- proves:
  - ai_insight present -> used as body, exact string, not reworded.
  - ai_insight absent -> falls back to the ORIGINAL Phase 5
    deterministic per-category template, byte-for-byte unchanged
    (regression guard -- this is the "opportunity_window" bug the
    original audit found).
  - ai_action present -> included as a top-level "action" key AND
    inside data["action"].
  - ai_action absent -> "action" key entirely absent from both the
    top-level result and data (never an empty string).
  - title is NEVER affected by ai_insight/ai_action -- always the
    fixed catalog string.

No database, no OpenAI call -- this module is pure functions over its
own catalog registry.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.alerts.notification_content_adapter import build_alert_notification_content  # noqa: E402

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


def main():
    # ==========================================================
    print("=== A: no AI content supplied -> original Phase 5 fallback, unchanged ===")
    # ==========================================================
    result_a = build_alert_notification_content(
        event_id="opportunity_window", category="timing", severity="MEDIUM",
    )
    check("A: title is the fixed catalog string", result_a["title"] == "Opportunity Window")
    check(
        "A: body is the EXACT original generic category sentence (regression guard for the reported bug)",
        result_a["body"] == "A timing-related signal is active for you today.",
    )
    check("A: no 'action' key when ai_action absent", "action" not in result_a)
    check("A: no 'action' key in data either", "action" not in result_a["data"])

    # ==========================================================
    print("\n=== B: ai_insight supplied -> used verbatim as body instead of the fallback ===")
    # ==========================================================
    result_b = build_alert_notification_content(
        event_id="opportunity_window", category="timing", severity="MEDIUM",
        ai_insight="A supportive window is opening for career recognition.",
    )
    check("B: title still the fixed catalog string", result_b["title"] == "Opportunity Window")
    check("B: body is the AI insight verbatim, not the category fallback", result_b["body"] == "A supportive window is opening for career recognition.")
    check("B: no 'action' key when ai_action still absent", "action" not in result_b)

    # ==========================================================
    print("\n=== C: both ai_insight and ai_action supplied ===")
    # ==========================================================
    result_c = build_alert_notification_content(
        event_id="opportunity_window", category="timing", severity="MEDIUM",
        ai_insight="Insight text.", ai_action="Send that proposal today.",
    )
    check("C: body is the insight", result_c["body"] == "Insight text.")
    check("C: top-level action present", result_c.get("action") == "Send that proposal today.")
    check("C: action also present inside data (travels with push/Bell payload)", result_c["data"].get("action") == "Send that proposal today.")
    check("C: data still carries type/event_id/category/severity unchanged", result_c["data"]["type"] == "alert" and result_c["data"]["event_id"] == "opportunity_window")

    # ==========================================================
    print("\n=== D: ai_insight is an empty string -> treated as absent, falls back ===")
    # ==========================================================
    result_d = build_alert_notification_content(
        event_id="opportunity_window", category="timing", severity="MEDIUM", ai_insight="",
    )
    check("D: empty-string ai_insight falls back to category template, not an empty body", result_d["body"] == "A timing-related signal is active for you today.")

    # ==========================================================
    print("\n=== E: works identically across a different category/event (not opportunity_window-specific) ===")
    # ==========================================================
    result_e = build_alert_notification_content(
        event_id="relationship_harmony", category="relationship", severity="LOW",
        ai_insight="Your bond with someone close may feel warmer than usual.",
        ai_action="Make time for a real conversation with them today.",
    )
    check("E: title correct for a different event", result_e["title"] == "Relationship Harmony")
    check("E: AI body used for this event too", result_e["body"] == "Your bond with someone close may feel warmer than usual.")
    check("E: action present for this event too", result_e.get("action") == "Make time for a real conversation with them today.")

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
