# modules/alerts/entitlement_gate.py

"""
Alerts Entitlement Gate (Phase 5; revised for the "Alerts & Opportunities"
premium subscription section).

The ONLY question this module answers: does this profile currently
have legitimate access to the premium "Alerts & Opportunities"
feature? Reuses modules/entitlement/entitlement_service.py::EntitlementService
EXCLUSIVELY -- no subscription/plan/trial rule is duplicated or
reimplemented here. This file contains zero business logic of its
own beyond reading EntitlementService's own output.

======================================================================
REVISION -- Alerts is now a real, selectable subscription section
======================================================================
Previously, "Alerts & Opportunities" was not one of the selectable
premium segments, so this gate treated it as an all-or-nothing bonus
granted only alongside every other segment (an active trial, or an
ACCESS_ALL-type plan). That constraint has been explicitly lifted per a
locked product decision: Alerts & Opportunities is now the sixth
canonical subscription section (modules/entitlement/
subscription_sections.py::SUBSCRIPTION_SECTIONS = LOVE/CAREER/FINANCE/
HEALTH/FAMILY/ALERTS), selectable exactly like any of the other five --
a Prime/Silver profile that selected "ALERTS" as its `selected_segment`
is entitled; one that selected anything else is not.

This gate's own logic is now IDENTICAL in shape to how any other single
section's access is decided (`section in accessible_segments`) -- no
special-cased "all segments" rule remains. `accessible_segments` itself
is still entirely computed by EntitlementService (unmodified logic,
only its own SUBSCRIPTION_SECTIONS-vs-AI_REPORT_SEGMENTS source swapped
-- see entitlement_service.py and plan_access_policy.py), so this file
still introduces no new access rule of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from modules.entitlement.subscription_sections import ALERTS_SECTION
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

    if ALERTS_SECTION in snapshot.accessible_segments:
        return AlertsEntitlementResult(
            entitled=True,
            reason=(
                f"profile has access to the {ALERTS_SECTION} section "
                f"(membership_state={snapshot.membership_state})"
            ),
            membership_state=snapshot.membership_state,
        )

    if snapshot.subscription.is_active and snapshot.accessible_segments:
        return AlertsEntitlementResult(
            entitled=False,
            reason=(
                f"active subscription grants only section(s) "
                f"{snapshot.accessible_segments!r} -- Alerts & Opportunities "
                f"was not the selected section"
            ),
            membership_state=snapshot.membership_state,
        )

    return AlertsEntitlementResult(
        entitled=False,
        reason=f"no active trial or subscription (membership_state={snapshot.membership_state})",
        membership_state=snapshot.membership_state,
    )
