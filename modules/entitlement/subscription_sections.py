# modules/entitlement/subscription_sections.py

"""
Subscription section identity -- separate, deliberately, from AI report
generation identity.

======================================================================
WHY THIS FILE EXISTS (the coupling this decouples)
======================================================================
modules/models_ai_reports.py::AI_REPORT_SEGMENTS (LOVE/CAREER/FINANCE/
HEALTH/FAMILY) was, before this file existed, used for TWO genuinely
different concerns at once:

1. "What segment values can the AI Report Engine actually generate
   content for" -- AIReport.segment's value domain, consulted by
   modules/premium_report/premium_report_service.py and
   modules/ai_report_engine/generator_registry.py before ever calling
   OpenAI.
2. "What segment values can a subscription profile be entitled to /
   select" -- consulted by modules/entitlement/plan_access_policy.py,
   entitlement_service.py, entitlement_write_service.py, and
   routes/routes_google_purchase_confirm.py.

Adding "Alerts & Opportunities" as the 6th subscription section by
appending "ALERTS" to AI_REPORT_SEGMENTS directly would have made
concern (2)'s change silently affect concern (1) too: it would let a
request reach modules/premium_report/premium_report_service.py's
segment validation with segment="ALERTS" and only fail later, deeper in
the AI generation pipeline (generator_registry.py has no generator
registered for it -- see its own docstring, which explicitly excludes
Alerts) -- an avoidable failure mode instead of a clean, early rejection
that already exists today.

SUBSCRIPTION_SECTIONS below is concern (2)'s own, now-independent value
domain: every AI_REPORT_SEGMENTS value, plus "ALERTS". AI_REPORT_SEGMENTS
itself is completely untouched -- still exactly 5 values, still the only
domain modules/premium_report/premium_report_service.py and
modules/ai_report_engine/generator_registry.py ever consult. Alerts
content itself continues to come exclusively from the existing,
unmodified Alerts Engine (modules/alerts/), never from the AI Report
Engine.
"""

from __future__ import annotations

from modules.models_ai_reports import AI_REPORT_SEGMENTS

ALERTS_SECTION = "ALERTS"

# The six canonical, machine-identical section identifiers used
# everywhere a PROFILE'S SUBSCRIPTION ENTITLEMENT/SELECTION is decided --
# never used to decide what the AI Report Engine can generate (that
# stays AI_REPORT_SEGMENTS, unmodified, imported directly where needed).
SUBSCRIPTION_SECTIONS = AI_REPORT_SEGMENTS + (ALERTS_SECTION,)
