# services/attention_policy.py

"""
N4 -- Global User Attention Policy.

Sits ABOVE the existing per-type eligibility/content pipelines
(services/notification_builder.py's Event/Transit/Dasha/Panchang/Panchak
sections, and modules/alerts/user_alert_selection_service.py's own Alerts
selection) -- narrows an already-eligible candidate pool down to what
actually reaches the user as a PUSH today, and decides which of the rest
(if any) still deserve a Bell-only row. Detection, per-type eligibility,
astrology calculation, and Alerts' own conflict/severity/cooldown engine
are NOT touched or reimplemented here -- this module only ever narrows an
already-eligible pool, exactly like modules/alerts/user_alert_selection.py
narrows Alerts' own pool, one layer up.

==================================================
WHY A SHARED, PERSISTED COUNTER (not shared process memory)
==================================================
services/event_scheduler.py::run_daily_event_job() (6 AM / 5 PM / 6 PM
IST, via .github/workflows/notifications.yml) and
modules/alerts/alerts_scheduler.py::run_daily_alerts_job() (8 AM IST, via
.github/workflows/alerts.yml) are two COMPLETELY SEPARATE GitHub Actions
workflows -- separate processes, separate checkouts, no shared memory,
running at different times, each with its own advisory-lock/rerun-safety
story. A literal "compare every candidate from both systems in one
function call before either sends" selector is not possible without
merging these into one process/run -- an explicit rewrite, out of scope
per this task's own "Architecture before implementation" instruction.

The smallest safe integration is what's implemented below: BOTH
schedulers, independently, query the SAME already-persisted signal --
today's UserNotification rows for this user -- immediately before they
decide to send. UserNotification is the ONE table both pipelines already
write to on every successful push (services/event_scheduler.py's own
STEP 5B; modules/alerts/persistence_repository.py::finalize_delivery()),
so no new table and no new cross-process communication mechanism was
needed. The real, chronological execution order (6 AM -> 8 AM -> 6 PM in
practice) becomes the de facto negotiation: whichever process sends
first spends the shared budget, and every later process/rerun sees the
up-to-date count, because the count is re-read from the database on
every call, never cached in memory -- this is what makes a rerun, a
delayed run, or a second execution window structurally unable to bypass
the cap (see this module's own tests).

Accepted, documented limitation: a genuinely SIMULTANEOUS cross-process
race (two workflows executing for the same user in the same instant) is
not guarded against here -- no distributed lock spans the two GitHub
Actions workflows. Given the real schedule never overlaps (6 AM, 8 AM,
5 PM dismiss-only, 6 PM) and each workflow already serializes itself
(Alerts' own advisory lock; the notification cron's own slot-scoped
GitHub Actions concurrency), this is a low-probability edge case, not a
routine one -- closing it fully would require the larger rewrite this
task explicitly asks NOT to force.

==================================================
PRIORITY MODEL (validated against actual candidate signals, not assumed)
==================================================
Tier 1 (Highest) -- Dasha/Dasha-pre, N3 Personalized Transit, and
  HIGH/CRITICAL-severity Alerts (Alerts' own config-driven
  severity_cooldown_registry.py value, never re-derived here).
Tier 2 (Contextual) -- Event (festival/vrat), Panchak, and
  LOW/MEDIUM-severity Alerts.
Tier 3 (Routine) -- Panchang.

No "major vs minor Dasha" sub-distinction was invented: every Dasha
change today already goes through one unified code path with no severity
signal, and a real Vimshottari Dasha transition is inherently rare
(at most a handful across a user's lifetime), so treating every Dasha
change as Tier 1 uniformly is grounded, not fabricated -- see
services/personalization_engine.py::get_users_for_dasha_change() and
services/dasha_db_filler.py, neither of which distinguishes Mahadasha-
level from Antardasha-only transitions. Likewise, no "significant vs
routine Event" split was invented: no existing per-vrat/festival
importance signal exists in AstroEvent beyond the type itself, and the
existing STEP 5A topic-broadcast PRIORITY dict in event_scheduler.py
serves an unrelated purpose (global topic ordering, not personalized
push selection) and is not reused here. Transit is uniformly Tier 1
because the existing house-eligibility filter ([1,4,7,8,10,12] in
services/personalization_engine.py::get_users_for_transit(), unmodified)
already gates "important" before a candidate ever reaches this module.
Panchak is uniformly Tier 2 because notification_builder.py's own
first-day-only gating (unmodified) already means every Panchak candidate
that reaches this module is "genuinely relevant" (a fresh window
starting, not a stale continuation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_

from extensions import db
from notifications.notification_models import UserNotification

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
TIER_HIGHEST = 1
TIER_CONTEXTUAL = 2
TIER_ROUTINE = 3

_EVENT_SCHEDULER_TYPE_TIER: Dict[str, int] = {
    "dasha": TIER_HIGHEST,
    "dasha_pre": TIER_HIGHEST,
    "transit": TIER_HIGHEST,
    "event": TIER_CONTEXTUAL,
    "panchak": TIER_CONTEXTUAL,
    "panchang": TIER_ROUTINE,
}

_ALERT_HIGH_SEVERITIES = {"HIGH", "CRITICAL"}

# Which tiers still deserve a Bell-only row when suppressed purely by the
# global daily push cap. Panchang is deliberately excluded -- see PUSH VS
# BELL section below.
BELL_ONLY_ELIGIBLE_TIERS = {TIER_HIGHEST, TIER_CONTEXTUAL}

# Product cap: normal target is 2 astrology pushes/user/day. No 3rd-push
# "exceptional, time-critical" exception is implemented -- none of the
# current candidate types carries a genuinely exceptional signal to hang
# one on: even Alerts' own CRITICAL severity level, the single highest
# level the vocabulary supports, is never actually assigned by the live
# catalog today (see severity_cooldown_registry.py's own comment: "CRITICAL
# is supported here even though the current catalog never assigns it").
# Inventing a 3rd-push carve-out with no real trigger behind it would be
# exactly the "silently create exceptions" this task explicitly forbids.
DAILY_PUSH_CAP = 2


def tier_for_event_scheduler_type(ntype: str) -> int:
    """
    Tier for a services/notification_builder.py candidate type (event,
    transit, dasha, dasha_pre, panchak, panchang). An unrecognized future
    type defaults to Tier 2 (Contextual) -- a safe middle ground: never
    silently Tier-1-privileged, never silently dropped as Tier-3-routine.
    """
    return _EVENT_SCHEDULER_TYPE_TIER.get(ntype, TIER_CONTEXTUAL)


def tier_for_alert_severity(severity: Optional[str]) -> int:
    """Tier for an Alerts candidate, from its own config-driven severity
    (modules/alerts/severity_cooldown_registry.py) -- never re-derived
    from confidence/priority, matching that package's own architecture
    decision that severity/confidence/priority/cooldown stay independent
    concepts."""
    return TIER_HIGHEST if (severity or "").upper() in _ALERT_HIGH_SEVERITIES else TIER_CONTEXTUAL


# ---------------------------------------------------------------------------
# Shared daily push counter
# ---------------------------------------------------------------------------
def start_of_today_ist(now: datetime) -> datetime:
    """IST midnight of `now`'s own IST calendar day, as a naive UTC
    datetime -- the exact convention services/notification_lifecycle.py's
    own _ist_midnight_utc() already established, recomputed locally here
    rather than importing that module's private helper."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    ist_now = now.astimezone(IST)
    ist_midnight = datetime.combine(ist_now.date(), time(0), tzinfo=IST)
    return ist_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def count_pushes_sent_today(user_id: int, now: Optional[datetime] = None) -> int:
    """
    The shared cross-process signal: how many astrology pushes has this
    user already received today (IST calendar day), across BOTH
    services/event_scheduler.py's pipeline and Alerts -- both write
    UserNotification on every successful send, and only on a successful
    send (see this module's own docstring). A Bell-only row (this
    module's own `data["delivery_channel"] == "bell_only"` marker, never
    written before N4) is explicitly excluded -- it was never pushed, so
    it must never consume push budget. Rows with no delivery_channel key
    at all (every row ever written before N4, and every ordinary pushed
    row since) are counted, by design -- no backfill/migration needed.
    """
    now = now or datetime.utcnow()
    since = start_of_today_ist(now)
    return (
        UserNotification.query.filter(
            UserNotification.user_id == user_id,
            UserNotification.created_at >= since,
            or_(
                UserNotification.data["delivery_channel"].astext.is_(None),
                UserNotification.data["delivery_channel"].astext != "bell_only",
            ),
        ).count()
    )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AttentionCandidate:
    """Plain-values input to select_for_push() -- deliberately not
    coupled to any ORM row or the notification_builder.py dict shape
    directly, mirroring modules/alerts/user_alert_selection.py's own
    AttentionCandidate-equivalent (AlertCandidate) pattern. `key` is
    caller-defined and only used to let the caller map a result back to
    its own original candidate object; this module never inspects it."""

    key: Any
    tier: int
    label: str = ""  # non-sensitive, for observability only (e.g. "transit", "dasha")


@dataclass(frozen=True)
class PushSelectionResult:
    approved: List[Any] = field(default_factory=list)
    bell_only: List[Any] = field(default_factory=list)
    dropped: List[Any] = field(default_factory=list)


def select_for_push(
    candidates: List[AttentionCandidate],
    *,
    already_sent_today: int,
    cap: int = DAILY_PUSH_CAP,
) -> PushSelectionResult:
    """
    Pure, deterministic, side-effect-free -- exactly like
    modules/alerts/user_alert_selection.py::select_user_facing_alerts().
    `candidates` must already be per-type-eligible (this function does
    not re-check any type's own eligibility, only narrows for global
    attention). Ranks by tier (stable: original relative order preserved
    within a tier -- no invented tie-break beyond input order, since
    within-run candidate order for one user is already deterministic
    from services/notification_builder.py::get_user_notifications()'s own
    section order), then keeps up to the remaining daily quota.

    Everything not kept is split into `bell_only` (tier is in
    BELL_ONLY_ELIGIBLE_TIERS -- genuinely useful information the user
    lost only because their attention budget was spent elsewhere) and
    `dropped` (Tier 3 / routine -- would be pure Bell clutter with little
    retroactive value; see PUSH VS BELL policy in this module's own
    docstring).
    """
    remaining = max(0, cap - already_sent_today)
    ranked = sorted(enumerate(candidates), key=lambda pair: (pair[1].tier, pair[0]))

    approved: List[Any] = []
    rest: List[AttentionCandidate] = []
    for _, c in ranked:
        if len(approved) < remaining:
            approved.append(c.key)
        else:
            rest.append(c)

    bell_only = [c.key for c in rest if c.tier in BELL_ONLY_ELIGIBLE_TIERS]
    dropped = [c.key for c in rest if c.tier not in BELL_ONLY_ELIGIBLE_TIERS]
    return PushSelectionResult(approved=approved, bell_only=bell_only, dropped=dropped)
