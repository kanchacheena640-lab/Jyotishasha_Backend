# modules/entitlement/plan_access_policy.py

"""
Section-access rules for the finalized plans -- centralized here so
segment-access logic is never duplicated or hardcoded elsewhere in the
codebase (EntitlementService is the only caller).

    Prime Monthly       -> only the profile's selected section (six choices)
    Prime Yearly        -> only the profile's selected section (six choices)
    Prime Plus Monthly  -> all six sections
    Prime Plus Yearly   -> all six sections

    Silver (Monthly/Yearly)    -> only the profile's selected section
    Gold (Monthly/Yearly)      -> all six sections
    Platinum (Yearly)          -> all six sections

Silver/Gold/Platinum (Subscription Purchase System -- S11) are the
real, finalized Google Play Console product lineup -- a new 3-tier
ladder sold alongside the original Prime/Prime Plus system, not a
replacement for it. Added here as an explicit, user-authorized
exception rather than silently guessed: Silver keeps the
single-section restriction, Gold and Platinum grant every section.

"Sections" here means modules/entitlement/subscription_sections.py::
SUBSCRIPTION_SECTIONS (LOVE/CAREER/FINANCE/HEALTH/FAMILY/ALERTS) --
deliberately NOT modules/models_ai_reports.py::AI_REPORT_SEGMENTS (5
values only). This module decides subscription access, never what the
AI Report Engine can generate -- see subscription_sections.py's own
docstring for the full reasoning.

Adding a future plan requires exactly one change: one new entry in
PLAN_SEGMENT_ACCESS below.
"""

from __future__ import annotations

from typing import List, Optional

from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS

ACCESS_ALL = "ALL"
ACCESS_SELECTED = "SELECTED"

PLAN_SEGMENT_ACCESS = {
    "PRIME_MONTHLY": ACCESS_SELECTED,
    "PRIME_YEARLY": ACCESS_SELECTED,
    "PRIME_PLUS_MONTHLY": ACCESS_ALL,
    "PRIME_PLUS_YEARLY": ACCESS_ALL,
    "SILVER_MONTHLY": ACCESS_SELECTED,
    "SILVER_YEARLY": ACCESS_SELECTED,
    "GOLD_MONTHLY": ACCESS_ALL,
    "GOLD_YEARLY": ACCESS_ALL,
    "PLATINUM_YEARLY": ACCESS_ALL,
}


def resolve_accessible_segments(plan: Optional[str], selected_segment: Optional[str]) -> List[str]:
    """Given a plan (and, if relevant, the profile's selected segment),
    return the full list of segments that plan currently grants. Not
    time/status aware -- callers (EntitlementService) are responsible
    for only calling this when the subscription/trial is actually
    active."""
    if plan is None:
        return []

    mode = PLAN_SEGMENT_ACCESS.get(plan)

    if mode == ACCESS_ALL:
        return list(SUBSCRIPTION_SECTIONS)

    if mode == ACCESS_SELECTED:
        return [selected_segment] if selected_segment else []

    # Unknown plan -- grants nothing rather than guessing.
    return []


def plan_grants_segment(plan: Optional[str], selected_segment: Optional[str], segment: str) -> bool:
    return segment in resolve_accessible_segments(plan, selected_segment)
