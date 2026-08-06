# modules/alerts/__init__.py

"""
Alerts Engine -- Micro Event Engine. This is the permanent Alerts
implementation for this platform.

Detects small, recurring astrological micro-events from current planet
data (transits cross-referenced against the natal Lagna). This module
is deliberately independent from the Premium Generators
(modules/love/, modules/career/, modules/finance/, modules/health/,
modules/family/, and their shared modules/ai_report_engine/ /
services/ai_prediction_lab/ infrastructure) -- it imports nothing from
any of those, and nothing in those imports from here.

Not to be confused with anything named "Alerts" in the Premium AI
Report system: modules/models_ai_reports.py's AI_REPORT_SEGMENTS
(LOVE/CAREER/FINANCE/HEALTH/FAMILY) has no "ALERTS" entry, and never
will -- this engine is not a ReportGenerator, produces no cached AI
prose, and has its own registry (event_registry.py), entirely separate
from modules/ai_report_engine/generator_registry.py.

Architecture (frozen for this phase):

    Planet Data -> Rule Engine -> Detected Micro Events
        -> Confidence Score -> Output JSON

This phase implements ONLY detection: rule evaluation and confidence
scoring against a fixed, config-driven event catalog
(modules/alerts/config/micro_events.json). It never calls OpenAI, never
builds a prompt, and never produces natural-language output -- every
event's `title` is the exact, fixed string from the catalog, not
generated text. Language generation is an explicitly later phase.
"""
