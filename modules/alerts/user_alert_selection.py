# modules/alerts/user_alert_selection.py

"""
User Alert Selection Layer (Alerts Product Hardening).

Sits BETWEEN detection/persistence (Phases 1-4, untouched) and user
exposure/delivery (Phase 5/5.1's deliver_alert(), also untouched). Its
ONLY job: given the full set of currently delivery-ELIGIBLE alerts for
one profile's current alert day, pick the small, non-contradictory,
non-redundant subset that should actually reach the user -- normally
1, at most 2.

Does NOT touch astrology detection, persistence writes, entitlement,
sunrise-boundary resolution, or the Rule/Confidence/Planning Window
Engine. Does NOT decide per-event eligibility (confidence threshold,
cooldown) -- that remains exclusively
delivery_eligibility_policy.py::evaluate_delivery_eligibility()
(Phase 4, unmodified). This layer only narrows an ALREADY-eligible
candidate pool down to the user-facing set.

==================================================
WHY THIS EXISTS
==================================================
A real production run (Phase 7B) showed that a profile with many
simultaneously-eligible micro-events (e.g. 11 in one case) produces a
noisy, sometimes self-contradictory push/Bell experience if every
eligible detection is exposed -- including, concretely, "Mood Low" and
"Mood Positive" both being eligible for the same profile on the same
day (opposite readings of the same underlying Moon placement). Nothing
about detection was wrong; exposing every technically-true detection
as a separate user-facing alert is the wrong PRODUCT behavior. This
layer fixes that without touching the engine that produced the
(correct) detections.

==================================================
CATALOG INSPECTION (grounding for CONFLICT_GROUPS below)
==================================================
Before writing CONFLICT_GROUPS, every one of the 23 real event
definitions in config/micro_events.json was inspected rule-by-rule
(planet + condition + value), not just by event name/title. Two kinds
of real, evidenced overlap were found:

TIER 1 -- direct opposite pairs on the SAME astrological axis (same
category, structurally inverse trigger conditions):
  - mood_positive vs mood_low: Moon in houses {1,3,5,9,11} (benefic)
    vs {6,8,12} (dusthana); benefic (Moon/Jupiter/Venus) vs malefic
    (Saturn/Rahu/Ketu) dasha lords. The exact case the real production
    run surfaced.
  - energy_high vs energy_low: Mars direct/strong vs Mars retrograde/
    in {8,12}; same dasha-lord inversion pattern.
  - good_time_to_start_something_new vs delay_possible: Jupiter-benefic
    houses/yoga vs Mercury retrograde + Saturn affliction -- opposite
    answers to "is this a good time".
  - relationship_harmony vs relationship_tension: Venus benefic-in-7th
    vs Saturn/Mars afflicting-the-7th -- opposite reading of the same
    house.
  - financial_gain_opportunity vs financial_caution: Jupiter/Venus
    benefic-in-2nd/11th vs Saturn afflicting-2nd/11th -- opposite
    reading of the same wealth houses.
  - health_slightly_weak vs recovery_phase: BOTH keyed to the identical
    6th/8th/12th houses (verified: health_slightly_weak's
    "saturn_house" rule and recovery_phase's "jupiter_house" rule use
    the exact same house list, (6,8,12)) -- malefic vs benefic
    occupant of the SAME houses, i.e. contradictory narration ("weak"
    vs "recovering") of the same placement.

TIER 2 -- cross-category substantial overlap, evidenced by an
IDENTICAL (planet, condition, value) rule shared between events in
DIFFERENT categories (so category-diversity alone would not catch
them):
  - mood_low <-> health_slightly_weak: both include a Moon-in-{6,8,12}
    rule (this is mood_low's own highest-weight rule, 0.22).
  - energy_low <-> minor_injury_caution: both include a
    Mars-conjunction-Saturn rule (weight 0.18 in both).
  - unexpected_expense <-> minor_injury_caution: both include a
    Mars-conjunction-Rahu rule.
  - mental_clarity <-> travel_opportunity <-> learning_focus: all
    three include the identical Mercury-conjunction-Jupiter rule.
  - financial_gain_opportunity <-> opportunity_window: both include the
    identical Jupiter-conjunction-Venus rule.

Not included: nothing else in the catalog shares a structural
(house/conjunction/sign/motion) rule across events -- overlaps that
exist only via the generic per-event "mahadasha_support"/
"antardasha_support" dasha-lord rules were deliberately excluded, since
those are broad, low-specificity rules present on nearly every event
and sharing one is not meaningful evidence of redundant meaning.
`stable_phase` (the fallback event) is never included in any group --
verified directly from planning_window_engine.py::plan(): the fallback
catalog is only ever consulted when the NORMAL catalog produces zero
planned events for the whole window, so stable_phase can never appear
in the same candidate pool as a real event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, List, Optional, Set

MAX_USER_FACING_ALERTS = 2

# A second alert is only ever added if it clears this PRIORITY tier
# (confidence_engine.derive_priority(), gated by the EXISTING
# priority_thresholds["high"] in config/micro_events.json -- no new
# threshold invented). Reusing "priority" here, not "severity": severity
# is a static, config-driven label per event TYPE (Phase 4), while
# whether today's detection is strong enough to justify a second
# simultaneous alert is a question about today's CONFIDENCE, which is
# exactly what "priority" already measures.
_STRONG_ENOUGH_FOR_SECOND_SLOT = "high"

_SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
_PRIORITY_RANK = {"high": 2, "medium": 1, "low": 0}

# See "CATALOG INSPECTION" above for the evidence behind every group.
# Each group: at most ONE member may ever appear in the user-facing set
# for the same alert day -- the strongest (per _rank_key) survives.
CONFLICT_GROUPS: List[FrozenSet[str]] = [
    # Tier 1 -- direct opposite pairs.
    frozenset({"mood_positive", "mood_low"}),
    frozenset({"energy_high", "energy_low"}),
    frozenset({"good_time_to_start_something_new", "delay_possible"}),
    frozenset({"relationship_harmony", "relationship_tension"}),
    frozenset({"financial_gain_opportunity", "financial_caution"}),
    frozenset({"health_slightly_weak", "recovery_phase"}),
    # Tier 2 -- cross-category rule-level overlap.
    frozenset({"mood_low", "health_slightly_weak"}),
    frozenset({"energy_low", "minor_injury_caution"}),
    frozenset({"unexpected_expense", "minor_injury_caution"}),
    frozenset({"mental_clarity", "travel_opportunity", "learning_focus"}),
    frozenset({"financial_gain_opportunity", "opportunity_window"}),
]


def _groups_for(event_id: str) -> Set[int]:
    """Indices into CONFLICT_GROUPS that contain this event_id."""
    return {i for i, g in enumerate(CONFLICT_GROUPS) if event_id in g}


@dataclass(frozen=True)
class AlertCandidate:
    """Plain-values input to select_user_facing_alerts() -- deliberately
    NOT an AlertMicroEvent ORM row, so this module (like every other
    Alerts layer) has zero DB/ORM import dependency and stays trivially
    unit-testable. Build one via `alert_candidate_from_row()` below."""

    event_id: str
    category: str
    severity: Optional[str]
    priority: Optional[str]
    confidence: float


def alert_candidate_from_row(row) -> AlertCandidate:
    """Thin adapter from a persisted AlertMicroEvent row (or anything
    duck-typed the same way) to AlertCandidate. The only place this
    module reaches toward the persistence layer's shape -- kept to one
    tiny function so it's obvious and easy to keep in sync."""
    return AlertCandidate(
        event_id=row.event_id,
        category=row.category,
        severity=row.severity,
        priority=row.priority,
        confidence=row.confidence,
    )


def _rank_key(c: AlertCandidate):
    """Deterministic strength ordering: severity, then priority, then
    confidence, then event_id as a stable tie-breaker -- exactly the
    order specified. Ascending sort on this key = strongest first.
    Unknown/None severity or priority rank BELOW every known value
    (defensive; every row written since Phase 4 always has both, but
    this must not crash or silently mis-rank an older/partial row)."""
    return (
        -_SEVERITY_RANK.get((c.severity or "").upper(), -1),
        -_PRIORITY_RANK.get((c.priority or "").lower(), -1),
        -c.confidence,
        c.event_id,
    )


def select_user_facing_alerts(
    candidates: Iterable[AlertCandidate],
    *,
    already_selected_today: int = 0,
    max_alerts: int = MAX_USER_FACING_ALERTS,
) -> List[AlertCandidate]:
    """
    Pure, deterministic, side-effect-free. `candidates` must already be
    confidence/cooldown-ELIGIBLE (see module docstring) -- this function
    does not re-check eligibility, only narrows for product exposure.

    `already_selected_today` is the count of alerts already shown/sent
    to this profile within the CURRENT alert day (see
    persistence_repository.py::count_delivered_since(), called by the
    orchestration layer, not here) -- this is what prevents a rerun
    from bypassing the daily cap via per-event cooldown mechanics: the
    cap is tracked independently of any single event's own cooldown
    clock.

    Algorithm:
      1. Rank all candidates deterministically (strongest first).
      2. Conflict/similarity suppression: walking strongest-to-weakest,
         drop any candidate that shares a CONFLICT_GROUPS entry with an
         already-kept (therefore stronger) candidate.
      3. Alert #1 = the strongest survivor, if any.
      4. Alert #2 (only if quota allows) = the next survivor that is
         BOTH from a meaningfully different category than #1 AND at
         least "high" priority. If no survivor clears both bars, only
         1 alert is returned -- a quota is never filled just to reach
         2.
    """
    remaining_quota = max(0, max_alerts - already_selected_today)
    pool = list(candidates)
    if remaining_quota <= 0 or not pool:
        return []

    ranked = sorted(pool, key=_rank_key)

    kept: List[AlertCandidate] = []
    used_groups: Set[int] = set()
    for c in ranked:
        my_groups = _groups_for(c.event_id)
        if my_groups & used_groups:
            continue  # a stronger conflicting/overlapping candidate already kept
        kept.append(c)
        used_groups |= my_groups

    if not kept:
        return []

    first = kept[0]
    selected = [first]
    if remaining_quota == 1:
        return selected

    for candidate in kept[1:]:
        if candidate.category == first.category:
            continue  # not "meaningfully different"
        if (candidate.priority or "").lower() != _STRONG_ENOUGH_FOR_SECOND_SLOT:
            continue  # not sufficiently strong on its own
        selected.append(candidate)
        break  # at most one more, ever

    return selected
