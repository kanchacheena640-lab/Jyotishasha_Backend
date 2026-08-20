# modules/alerts/alert_ai_content_service.py

"""
AI-Written Personalized Alert Content.

==================================================
ARCHITECTURAL GATE FIX (post-implementation review)
==================================================
The original version of this file called OpenAI from inside
ProfileDetectionService.evaluate_profile()'s per-DETECTED-event loop --
BEFORE selection/suppression/ranking/cooldown/daily-cap narrowed the
detected set down to the small (normally 1, at most
MAX_USER_FACING_ALERTS) set actually shown to the user. For a profile
with 5 detected events where selection ultimately chose only 1, that
version could make up to 5 OpenAI calls for one delivered alert --
violating the locked requirement:

    Detection -> suppression/ranking/cooldown/daily-cap
        -> FINAL selected alert(s) -> OpenAI generation

This version splits the work into two halves, at the same boundary the
data itself crosses:

  1. describe_triggered_facts() -- PURE, no OpenAI, no cost. Called
     from ProfileDetectionService for EVERY detected event (cheap
     string formatting only), producing a small list of plain-English
     facts persisted on AlertMicroEvent.triggered_facts. This is safe
     to do for every detected event regardless of whether it is later
     selected -- it costs nothing and is what makes generation possible
     LATER without having to re-run detection/kundali calculation for
     an event selected hours or days after it was first detected (the
     live EvaluationContext/PlannedMicroEvent only exist in-memory
     during one evaluate_profile() call).

  2. ensure_ai_content_for_selected_rows() -- the ONLY place OpenAI is
     ever called from. Takes the FINAL, already-selected AlertMicroEvent
     rows (modules/alerts/user_alert_selection_service.py::
     get_user_facing_alerts_for_profile()'s own `selected` list -- THE
     single selection authority both modules/alerts/alerts_scheduler.py
     and routes/routes_alerts_dashboard.py already share) and generates
     content ONLY for those, reading each row's own already-persisted
     `triggered_facts` -- no live detection objects needed. Idempotent
     per row (skips a row that already has ai_insight, or one with no
     triggered_facts to ground a prompt in) -- generated once, reused by
     every downstream surface, safe to call from multiple selection
     call sites or a scheduler retry without ever double-generating for
     the same occurrence.

No new OpenAI client/model construction -- reuses
services/ai_prediction_lab/openai_client.generate() directly, the same
call modules/ai_report_engine/openai_executor.py::OpenAIExecutor
already wraps for Premium Reports (that heavier class -- expiry/
versioning/GeneratedReport -- is the wrong shape for a two-field,
~40-word addition, so it is not reused here; only the actual OpenAI
call is).

Never raises to its caller. Any failure -- OpenAI error/timeout,
unparseable output, a row with no triggered_facts -- leaves ai_insight/
ai_action NULL; notification_content_adapter.py falls back to the
existing deterministic per-category template -- this file can never
break alert delivery.
"""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import Iterable, List, Optional

from extensions import db

from modules.alerts.event_models import EvaluationContext, TriggeredRule
from modules.alerts.event_registry import get_default_registry
from modules.alerts.persistence_models import AlertMicroEvent
from modules.alerts.planning_models import PlannedMicroEvent
from services.ai_prediction_lab import openai_client


@dataclass(frozen=True)
class AlertAIContent:
    insight: str
    action: str


def _describe_rule(rule: TriggeredRule, context: EvaluationContext) -> Optional[str]:
    """
    Translates one TriggeredRule into a plain-English astrological fact,
    preferring the ACTUAL current chart data on `context` (e.g. the
    planet's real current house/sign) over merely restating the rule's
    own configured condition list -- more specific and more accurate.
    Returns None for a rule this function cannot describe (never
    raises) -- the caller simply omits it.
    """
    snapshot = context.planet_snapshots.get(rule.planet)

    if rule.condition in ("house_in", "house_not_in"):
        if snapshot and snapshot.house is not None:
            return f"{rule.planet} is currently transiting house {snapshot.house}"
        return None

    if rule.condition == "sign_in":
        if snapshot and snapshot.sign:
            return f"{rule.planet} is currently in {snapshot.sign}"
        return None

    if rule.condition == "nakshatra_in":
        if snapshot and snapshot.nakshatra:
            return f"{rule.planet} is currently in {snapshot.nakshatra} nakshatra"
        return None

    if rule.condition == "motion_equals":
        if snapshot and snapshot.motion:
            return f"{rule.planet} is currently {snapshot.motion}"
        return None

    if rule.condition == "conjunction_with":
        other = str(rule.value)
        return f"{rule.planet} is currently in conjunction with {other}"

    if rule.condition == "mahadasha_lord_in":
        if context.mahadasha_lord:
            return f"the current Mahadasha lord is {context.mahadasha_lord}"
        return None

    if rule.condition == "antardasha_lord_in":
        if context.antardasha_lord:
            return f"the current Antardasha lord is {context.antardasha_lord}"
        return None

    if rule.condition == "yoga_active":
        yoga_name = str(rule.value).replace("_", " ")
        return f"the {yoga_name} is currently active in the chart"

    if rule.condition == "natal_lord_house_in":
        value = rule.value if isinstance(rule.value, dict) else {}
        natal_house = value.get("natal_house")
        house_text = f"house {natal_house}" if natal_house else "a key house"
        current_house = snapshot.house if snapshot and snapshot.house is not None else None
        if current_house is not None:
            return (
                f"{rule.planet}, the natal lord of {house_text}, is currently "
                f"transiting into house {current_house}"
            )
        return f"{rule.planet}, the natal lord of {house_text}, is favorably placed"

    if rule.condition == "natal_lord_aspected_by":
        value = rule.value if isinstance(rule.value, dict) else {}
        natal_house = value.get("natal_house")
        house_text = f"house {natal_house}" if natal_house else "a key house"
        return f"the natal lord of {house_text} is receiving a supportive aspect"

    return None


def describe_triggered_facts(event: PlannedMicroEvent, context: EvaluationContext) -> List[str]:
    """
    PURE, no OpenAI call, no cost -- safe to call for EVERY detected
    event regardless of whether it is later selected. Called from
    modules/alerts/profile_detection_service.py at detection time,
    while the live EvaluationContext still exists; the result is
    persisted on AlertMicroEvent.triggered_facts so a LATER, separate
    generation step (after selection, possibly a different request
    entirely) has the real per-occurrence facts available without
    needing to recompute the kundali/re-run rule evaluation.
    """
    facts: List[str] = []
    for rule in event.triggered_rules:
        described = _describe_rule(rule, context)
        if described:
            facts.append(described)
    return facts


def _build_prompt(*, title: str, category: str, facts: List[str]) -> Optional[str]:
    if not facts:
        # Nothing concrete to ground the AI in -- never invent generic
        # filler in place of real chart facts; caller falls back to the
        # deterministic category template instead.
        return None

    facts_block = "\n".join(f"- {f}" for f in facts)

    return (
        f"Event: {title} (category: {category})\n"
        f"The following real, specific facts from this person's chart are active right now:\n"
        f"{facts_block}\n\n"
        "Write two short pieces of guidance for this person, in this exact order and format, "
        "each on its own line, with no extra commentary before or after:\n\n"
        "INSIGHT: <one or two sentences, in plain everyday language, explaining what this "
        "combination of chart facts may mean for their real life right now -- career, money, "
        "relationships, health, or timing, whichever the facts above actually support. "
        "Do not use astrological jargon like house numbers, planet names, or yoga names in this line -- "
        "translate them into ordinary meaning.>\n"
        "ACTION: <one concrete, practical suggestion for something they could actually do today or "
        "this week, in one sentence.>"
    )


def _parse_response(text: str) -> Optional[AlertAIContent]:
    insight = None
    action = None
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("insight:"):
            insight = stripped.split(":", 1)[1].strip()
        elif lower.startswith("action:"):
            action = stripped.split(":", 1)[1].strip()

    if not insight or not action:
        return None
    return AlertAIContent(insight=insight, action=action)


def build_alert_ai_content_from_facts(
    *, title: str, category: str, facts: List[str],
) -> Optional[AlertAIContent]:
    """
    THE only function in this file that calls OpenAI. Operates purely
    on already-persisted plain strings (title/category/facts) -- no
    live PlannedMicroEvent/EvaluationContext needed, so it can run at
    ANY later point (a separate request, a different process) from
    when those facts were originally computed. Returns None on ANY
    failure (OpenAI error/timeout, unparseable output, no facts to
    ground a prompt in) -- never raises.
    """
    try:
        prompt = _build_prompt(title=title, category=category, facts=facts)
        if prompt is None:
            return None

        # services.ai_prediction_lab.openai_client.generate() already
        # sets its own fixed system-role message ("You are a senior
        # Vedic astrologer") internally -- this file does not construct
        # a second system message or a new client, only the user-role
        # prompt content above.
        text = openai_client.generate(prompt)
        return _parse_response(text)
    except Exception:
        return None


def ensure_ai_content_for_selected_rows(
    selected_rows: Iterable[AlertMicroEvent],
) -> None:
    """
    THE post-selection generation gate. Call this ONLY with the FINAL,
    already-selected set (get_user_facing_alerts_for_profile()'s own
    `selected` -- the single selection authority both
    alerts_scheduler.py and routes_alerts_dashboard.py already share).
    Never call this with a raw/unselected detected-events list -- doing
    so would reintroduce the exact over-generation this function exists
    to close off.

    For each row: skipped entirely (no OpenAI call) if ai_insight is
    already set (generated once, per real occurrence -- calling this
    again for an already-enriched row, e.g. a scheduler retry or the
    dashboard being opened after a push already generated the content,
    costs nothing) or if the row has no triggered_facts to ground a
    prompt in (never invents generic filler). Otherwise calls OpenAI
    exactly once per row and persists the result immediately so every
    other caller (this function or notification_content_adapter.py)
    sees it without a second generation.

    Known, narrow, accepted residual race (disclosed, not engineered
    around): two callers invoking this for the SAME row at nearly the
    same instant (e.g. the scheduler and a dashboard fetch landing
    together) could both pass the "not yet generated" check before
    either commits, causing two OpenAI calls for that one row. Low
    probability, no data-safety consequence (the second commit simply
    overwrites with an equally-valid generation) -- not a schema/lock
    change this fix takes on.
    """
    registry = get_default_registry()

    for row in selected_rows:
        if row.ai_insight:
            continue
        if not row.triggered_facts:
            continue

        catalog_event = registry.get(row.event_id)
        title = catalog_event.title if catalog_event is not None else row.event_id

        content = build_alert_ai_content_from_facts(
            title=title, category=row.category, facts=row.triggered_facts,
        )
        if content is None:
            continue

        row.ai_insight = content.insight
        row.ai_action = content.action
        row.ai_generated_at = datetime.utcnow()
        db.session.commit()
