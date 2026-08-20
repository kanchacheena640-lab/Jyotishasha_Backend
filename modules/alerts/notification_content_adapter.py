# modules/alerts/notification_content_adapter.py

"""
Alerts Notification Content Adapter (Phase 5; AI-Written Personalized
Alert Content addition on top).

Body text now PREFERS the AI-written `ai_insight`/`ai_action` a genuine
new/reactivated occurrence generated at detection time (see
modules/alerts/alert_ai_content_service.py, called from
modules/alerts/profile_detection_service.py, persisted on
AlertMicroEvent) -- passed in here by the caller, which already holds
the row. This file itself still makes NO OpenAI call and generates NO
text -- it only chooses between two ALREADY-COMPUTED sources: the
persisted AI content when present, or the original Phase 5
deterministic, config/catalog-driven fallback below when it is not
(never generated yet, or a past generation attempt failed) -- the
exact same category template every alert used before this addition,
byte-for-byte unchanged, so a missing/failed AI generation can never
degrade below Phase 5's own behavior.

Reuses the Rule Engine's own event catalog
(modules/alerts/event_registry.py, unmodified) for the event's fixed
`title` (the exact same string every DetectedMicroEvent/
PlannedMicroEvent already carries -- see event_models.py's own
docstring: "title is always the fixed catalog string, never generated
text" -- title is NEVER AI-written, only body/action are). The
per-category template map below is the only hardcoded "content" this
file introduces; every string is fixed at code-review time, same
discipline config/micro_events.json's own `title` field already
follows.

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

from typing import Any, Dict, Optional

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
    ai_insight: Optional[str] = None,
    ai_action: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns {"title": str, "body": str, "data": dict} -- title always
    the fixed catalog string; body is the persisted AI-written
    `ai_insight` when the caller supplies one (a genuine new/reactivated
    occurrence that generated successfully), else the original Phase 5
    deterministic per-category fallback, unchanged. `ai_insight`/
    `ai_action` are optional purely for backward compatibility -- every
    existing call site keeps working unmodified if it never passes
    them; they come from AlertMicroEvent.ai_insight/.ai_action, which
    this file does not read from the database itself (stays a plain-
    values consumer, matching persistence_repository.py's own
    discipline).

    A top-level `action` key is included in the return value ONLY when
    `ai_action` is supplied -- never an empty string, so a client can
    safely treat its absence as "no action for this alert" rather than
    parse-and-hide an empty value. It also travels inside `data`, so a
    push/Bell payload (title+body only, no 3rd field) still carries it
    for any consumer that reads the deep-link data instead of the
    notification's own body.

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
    body = ai_insight if ai_insight else _CATEGORY_BODY_TEMPLATES.get(category, _DEFAULT_BODY_TEMPLATE)

    data: Dict[str, Any] = {
        "type": "alert",
        "event_id": event_id,
        "category": category,
        "severity": severity,
    }

    result: Dict[str, Any] = {"title": title, "body": body, "data": data}

    if ai_action:
        result["action"] = ai_action
        data["action"] = ai_action

    return result
