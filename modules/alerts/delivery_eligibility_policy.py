# modules/alerts/delivery_eligibility_policy.py

"""
Delivery Eligibility Policy (Phase 4).

A pure, side-effect-free decision function: given an event's current
lifecycle state, confidence, severity/cooldown policy, and its
last-delivered timestamp (if any), decide whether it is CURRENTLY
eligible for notification/delivery. Performs NO database access, NO
FCM call, and sends NOTHING -- see this phase's own scope ("Do NOT
send notifications yet"). A future Phase 5 (notification content +
delivery adapter) is expected to call this function, then, only on a
CONFIRMED successful send, update AlertMicroEvent.last_delivered_at --
never this file's job.

==================================================
RULES (exactly as specified for this phase)
==================================================
- EXPIRED is NEVER delivery-eligible, regardless of cooldown/confidence.
- NEW and ACTIVE are treated identically otherwise: both are eligible
  once confidence clears the minimum threshold AND the per-event
  cooldown (measured from `last_delivered_at`, if any) has elapsed.
  This is what makes "ACTIVE must not automatically generate a
  notification every scheduler run" true -- an ACTIVE event that was
  JUST delivered stays ineligible until its cooldown elapses, exactly
  like a NEW one would after its own first delivery. A reactivated
  event (EXPIRED -> ACTIVE/NEW again, see
  persistence_repository.py::synchronize_profile_events()) is not
  treated specially here either -- it is governed by the same
  `last_delivered_at`-vs-cooldown check as any other NEW/ACTIVE event,
  which is exactly "respect the chosen cooldown policy" for
  reactivation, per this phase's own instruction.
- The minimum confidence gate reuses the EXISTING, already-configured
  `priority_thresholds["medium"]` value from
  config/micro_events.json (read via
  event_registry.EventRegistry.priority_thresholds, unmodified) --
  no new confidence number is invented. This is confidence
  INFLUENCING eligibility (a pass/fail gate), never confidence
  determining severity -- severity comes ONLY from
  SeverityCooldownRegistry, config-driven, per this phase's own
  architecture decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from modules.alerts.event_registry import get_default_registry
from modules.alerts.severity_cooldown_registry import (
    SeverityCooldownRegistry,
    get_default_severity_cooldown_registry,
)

_VALID_STATES = ("NEW", "ACTIVE", "EXPIRED")


@dataclass(frozen=True)
class DeliveryEligibility:
    eligible: bool
    reason: str
    severity: str
    next_eligible_at: Optional[datetime]


def evaluate_delivery_eligibility(
    *,
    event_id: str,
    state: str,
    confidence: float,
    last_delivered_at: Optional[datetime],
    now: Optional[datetime] = None,
    severity_registry: Optional[SeverityCooldownRegistry] = None,
    priority_thresholds: Optional[Dict[str, float]] = None,
) -> DeliveryEligibility:
    """
    Pure function -- no I/O, no persistence, no notification send.

    `state` must be one of "NEW" / "ACTIVE" / "EXPIRED" (the same
    values modules/alerts/persistence_models.py::ALERT_MICRO_EVENT_STATES
    uses; not imported directly, to avoid a dependency on that file,
    matching this phase's "keep DB, rule, and policy layers separate"
    discipline).

    Raises SeverityCooldownConfigError (via severity_registry.get())
    if `event_id` has no configured policy -- fails loudly, consistent
    with this phase's "fail validation... rather than silently
    guessing" requirement.
    """
    now = now or datetime.utcnow()
    severity_registry = severity_registry or get_default_severity_cooldown_registry()
    policy = severity_registry.get(event_id)  # raises SeverityCooldownConfigError if unknown

    if state not in _VALID_STATES:
        return DeliveryEligibility(
            eligible=False,
            reason=f"unrecognized lifecycle state {state!r}",
            severity=policy.severity,
            next_eligible_at=None,
        )

    if state == "EXPIRED":
        return DeliveryEligibility(
            eligible=False,
            reason="event is EXPIRED",
            severity=policy.severity,
            next_eligible_at=None,
        )

    thresholds = priority_thresholds if priority_thresholds is not None else get_default_registry().priority_thresholds
    min_confidence = thresholds.get("medium", 0.0)
    if confidence < min_confidence:
        return DeliveryEligibility(
            eligible=False,
            reason=(
                f"confidence {confidence:.3f} below minimum eligibility "
                f"threshold {min_confidence:.3f}"
            ),
            severity=policy.severity,
            next_eligible_at=None,
        )

    if last_delivered_at is not None:
        cooldown_ends_at = last_delivered_at + timedelta(hours=policy.cooldown_hours)
        if now < cooldown_ends_at:
            return DeliveryEligibility(
                eligible=False,
                reason=f"cooldown active until {cooldown_ends_at.isoformat()}",
                severity=policy.severity,
                next_eligible_at=cooldown_ends_at,
            )

    return DeliveryEligibility(
        eligible=True,
        reason="eligible",
        severity=policy.severity,
        next_eligible_at=now + timedelta(hours=policy.cooldown_hours),
    )
