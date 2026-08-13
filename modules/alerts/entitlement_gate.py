# modules/alerts/entitlement_gate.py

"""
Alerts Entitlement Gate (Phase 5).

The ONLY question this module answers: does this profile currently
have legitimate access to the premium "Alerts & Opportunities"
feature? Reuses modules/entitlement/entitlement_service.py::EntitlementService
EXCLUSIVELY -- no subscription/plan/trial rule is duplicated or
reimplemented here. This file contains zero business logic of its
own beyond reading EntitlementService's own output.

======================================================================
WHY "access to ALL segments" IS THE GATE (verified from real code,
not invented -- confirmed with the user before implementation)
======================================================================
"Alerts & Opportunities" is NOT one of the 5 selectable premium
segments (modules/models_ai_reports.py::AI_REPORT_SEGMENTS =
LOVE/CAREER/FINANCE/HEALTH/FAMILY). Confirmed directly from code:
EntitlementService.has_access() itself raises ValueError for any
segment outside that list, and
modules/entitlement/entitlement_write_service.py's own write path
(line ~220) rejects any `selected_segment` outside AI_REPORT_SEGMENTS
at write time -- so a profile can NEVER have "ALERTS" as its
selected_segment today. Adding a 6th segment would be inventing/
modifying subscription business rules, explicitly forbidden for this
phase.

Given that hard constraint, this gate treats Alerts access as granted
exactly when the profile's CurrentEntitlement already grants access to
EVERY existing segment:
  - an active trial (EntitlementService.get_current_entitlement()
    already grants all 5 segments to any active trial, unconditionally
    -- see that method's own code), or
  - an ACCESS_ALL-type plan (PRIME_PLUS_*, GOLD_*, PLATINUM_YEARLY,
    per modules/entitlement/plan_access_policy.py -- unmodified).
A single-section (ACCESS_SELECTED) plan -- PRIME_*, SILVER_* -- never
grants Alerts, regardless of which one segment it selected, because
none of the 5 selectable segments IS Alerts.

This is derived ENTIRELY from EntitlementSnapshot.accessible_segments,
already computed by EntitlementService -- no new access rule, no new
plan table, no change to any entitlement file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from modules.models_ai_reports import AI_REPORT_SEGMENTS
from modules.entitlement.entitlement_service import EntitlementService


@dataclass(frozen=True)
class AlertsEntitlementResult:
    entitled: bool
    reason: str
    membership_state: str


def has_alerts_access(
    profile_id: int,
    entitlement_service: Optional[EntitlementService] = None,
) -> AlertsEntitlementResult:
    """
    Reuses EntitlementService.get_current_entitlement() -- the existing
    single source of truth -- unmodified. Always returns an explicit,
    human-readable `reason`, on both grant and rejection, per this
    phase's own requirement ("Return an explicit skip reason for
    entitlement rejection").
    """
    entitlement_service = entitlement_service or EntitlementService()
    snapshot = entitlement_service.get_current_entitlement(profile_id)

    all_segments_accessible = set(snapshot.accessible_segments) == set(AI_REPORT_SEGMENTS)

    if all_segments_accessible:
        return AlertsEntitlementResult(
            entitled=True,
            reason=f"profile has access to all segments (membership_state={snapshot.membership_state})",
            membership_state=snapshot.membership_state,
        )

    if snapshot.trial.is_active:
        # Should be structurally unreachable (an active trial already
        # grants all segments per EntitlementService.get_current_entitlement()
        # itself, so the branch above should always catch it first) --
        # kept as an explicit, defensive fallback rather than silently
        # falling through to "denied" if that invariant is ever changed
        # elsewhere in EntitlementService without this file's knowledge.
        return AlertsEntitlementResult(
            entitled=True,
            reason="profile has an active trial",
            membership_state=snapshot.membership_state,
        )

    if snapshot.subscription.is_active and snapshot.accessible_segments:
        return AlertsEntitlementResult(
            entitled=False,
            reason=(
                f"active subscription grants only segment(s) "
                f"{snapshot.accessible_segments!r} -- Alerts requires "
                f"an all-segments plan or an active trial"
            ),
            membership_state=snapshot.membership_state,
        )

    return AlertsEntitlementResult(
        entitled=False,
        reason=f"no active trial or subscription (membership_state={snapshot.membership_state})",
        membership_state=snapshot.membership_state,
    )
