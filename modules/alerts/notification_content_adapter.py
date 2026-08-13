# modules/alerts/notification_content_adapter.py

"""
Alerts Notification Content Adapter (Phase 5).

Deterministic, config/catalog-driven notification content for a
detected micro-event -- NO OpenAI call, NO AI-generated text anywhere.
Reuses the Rule Engine's own event catalog
(modules/alerts/event_registry.py, unmodified) for the event's fixed
`title` (the exact same string every DetectedMicroEvent/
PlannedMicroEvent already carries -- see event_models.py's own
docstring: "title is always the fixed catalog string, never generated
text"). Body text comes from a small, hardcoded, per-category template
map -- the only new "content" this file introduces; every string is
fixed at code-review time, same discipline config/micro_events.json's
own `title` field already follows.

Deliberately does NOT include `confidence` anywhere in the returned
content or payload -- per this phase's instruction not to expose
internal confidence percentages absent an explicit product
requirement.

Does not modify or duplicate any EXISTING generic notification content
function -- services/notification_builder.py's build_event_content()/
build_panchang_content() are untouched and unrelated (those are for
AstroEvent-based festival/vrat/Panchang notifications, a completely
different event shape).
"""

from __future__ import annotations

from typing import Any, Dict

from modules.alerts.event_registry import get_default_registry
from modules.alerts.exceptions import AlertsEngineError

# One short, deterministic sentence per category. Fixed strings only --
# nothing here is generated at runtime.
_CATEGORY_BODY_TEMPLATES: Dict[str, str] = {
    "emotional": "Your emotional outlook may be shifting today.",
    "vitality": "Your energy and vitality may be shifting today.",
    "financial": "A financial signal is active for you today.",
    "timing": "A timing-related signal is active for you today.",
    "health": "A wellbeing signal is active for you today.",
    "relationship": "A relationship signal is active for you today.",
    "travel": "A travel-related signal is active for you today.",
    "learning": "A learning-related signal is active for you today.",
    "general": "Your current phase is stable today.",
}
_DEFAULT_BODY_TEMPLATE = "A personalized astrological signal is active for you today."


class AlertContentError(AlertsEngineError):
    """Raised when notification content cannot be deterministically
    built for a given event_id -- e.g. it is not a real catalog event.
    Fails loudly rather than sending a blank/garbled notification."""


def build_alert_notification_content(
    *,
    event_id: str,
    category: str,
    severity: str,
) -> Dict[str, Any]:
    """
    Returns {"title": str, "body": str, "data": dict} -- deterministic,
    catalog/config-driven, confidence never exposed.

    `data` follows the SAME "type" + "event_id" deep-link convention
    every existing AstroEvent-based notification already uses (see
    services/notification_builder.py's build_event_content()/
    build_panchang_content(), which use
    {"type": "event"/"transit"/"dasha"/"dasha_pre"/"panchak"/"panchang",
    "event_id": ...}) -- "type": "alert" is a new, distinct, clearly-
    namespaced value the Flutter app can switch on alongside those
    existing cases, without any of them changing.
    """
    catalog_event = get_default_registry().get(event_id)
    if catalog_event is None:
        raise AlertContentError(f"Unknown event_id for notification content: {event_id!r}")

    title = catalog_event.title
    body = _CATEGORY_BODY_TEMPLATES.get(category, _DEFAULT_BODY_TEMPLATE)

    return {
        "title": title,
        "body": body,
        "data": {
            "type": "alert",
            "event_id": event_id,
            "category": category,
            "severity": severity,
        },
    }
