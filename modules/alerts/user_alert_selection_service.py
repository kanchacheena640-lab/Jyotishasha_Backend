# modules/alerts/user_alert_selection_service.py

"""
User Alert Selection -- orchestration layer.

Wires the pure algorithm in user_alert_selection.py to real persisted
data for one profile: fetches this profile's active alerts (Phase 1,
unmodified), filters to those currently eligible
(delivery_eligibility_policy.py, Phase 4, unmodified), resolves how
many have already been selected/delivered within the current alert day
(Phase 3's sunrise boundary, unmodified, via
persistence_repository.py::count_delivered_since()), and returns the
final user-facing AlertMicroEvent rows.

THE single source of truth for "what should this profile see today":
- modules/alerts/alerts_scheduler.py calls this for push delivery.
- A future Alerts app API endpoint (not built in this change -- none
  was requested) MUST call this same function rather than
  repository.fetch_active_for_profile() directly, so the app's Alerts
  section can never show a persisted-but-not-selected detection that
  push delivery itself would never have sent.

No astrology, persistence-writing, entitlement, or sunrise logic lives
here -- purely reads existing data and calls existing, unmodified
functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from modules.models_user import AppUser

from modules.alerts.delivery_eligibility_policy import evaluate_delivery_eligibility
from modules.alerts.persistence_models import AlertMicroEvent
from modules.alerts.persistence_repository import AlertPersistenceRepository
from modules.alerts.sunrise_boundary import SunriseResolutionError, resolve_current_alert_day_start
from modules.alerts.user_alert_selection import (
    MAX_USER_FACING_ALERTS,
    alert_candidate_from_row,
    select_user_facing_alerts,
)

_IST = ZoneInfo("Asia/Kolkata")
_UTC = ZoneInfo("UTC")


def resolve_daily_cap_window_start(lat: Optional[float], lon: Optional[float], now: datetime) -> datetime:
    """
    Start of the window used to count "alerts already selected/
    delivered today" for the max-2-per-alert-day cap. Prefers the SAME
    sunrise-to-sunrise alert day boundary Phase 3 already established
    (resolve_current_alert_day_start(), unmodified) using the caller's
    own lat/lon. Falls back to plain IST midnight only if sunrise
    resolution itself is unavailable (missing/invalid coordinates) --
    defensive only; see alerts_scheduler.py's own use of this function
    for why real production never actually reaches the fallback branch.

    ALWAYS returns a NAIVE datetime whose digits are the correct UTC
    instant -- i.e. directly comparable to AlertMicroEvent.last_delivered_at
    (a naive "timestamp without time zone" column, always written via
    datetime.utcnow()-equivalent naive-UTC values throughout this
    package). This conversion is deliberate and was verified necessary,
    not stylistic: resolve_current_alert_day_start() returns a
    TZ-AWARE, IST-labeled datetime, and this local Postgres instance's
    session timezone is Asia/Calcutta -- comparing a tz-aware value
    directly against a naive column in SQL does NOT raise an error and
    does NOT silently do a correct UTC-instant comparison either; it
    makes Postgres reinterpret the naive column's digits AS IST
    wall-clock time (the session timezone) before comparing, silently
    shifting the effective window boundary by the IST offset (+05:30).
    Verified directly against the real local DB before landing this
    fix (a naive/aware comparison that should have been unambiguous
    returned the wrong boolean). Stripping to naive-UTC here, once,
    keeps every OTHER comparison in this package (which are all
    pure-Python, naive-vs-naive, and already correct) undisturbed.
    """
    try:
        alert_day_start = resolve_current_alert_day_start(lat, lon, now=now)
    except SunriseResolutionError:
        now_ist = now.astimezone(_IST) if now.tzinfo else now.replace(tzinfo=_IST)
        alert_day_start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    return alert_day_start.astimezone(_UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class UserFacingAlertsResult:
    """`selected` is the final user-facing set (normally 1, at most
    MAX_USER_FACING_ALERTS). `eligible_count` is how many alerts passed
    the EXISTING Phase 4 confidence/cooldown gate before this layer's
    own narrowing -- exposed so a caller (the scheduler) can report
    accurate, distinct operational counters for "failed the pre-
    existing eligibility gate" vs "eligible but not selected by this
    product-layer narrowing", without recomputing eligibility itself."""

    selected: List[AlertMicroEvent]
    eligible_count: int


def get_user_facing_alerts_for_profile(
    profile_id: int,
    *,
    now: Optional[datetime] = None,
    repository: Optional[AlertPersistenceRepository] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> UserFacingAlertsResult:
    """
    Returns the final, user-facing AlertMicroEvent rows for this
    profile's current alert day -- normally 1, at most
    MAX_USER_FACING_ALERTS. `lat`/`lon` default to this profile's own
    AppUser.lat/lng when not supplied (the same source
    ProfileDetectionService and every other Alerts caller already
    uses); pass them explicitly to avoid a second AppUser lookup when
    the caller already has one in hand (e.g. the scheduler).
    """
    now = now or datetime.utcnow()
    repository = repository or AlertPersistenceRepository()

    if lat is None or lon is None:
        user = AppUser.query.get(profile_id)
        lat = lat if lat is not None else (user.lat if user else None)
        lon = lon if lon is not None else (user.lng if user else None)

    active_alerts = repository.fetch_active_for_profile(profile_id=profile_id)

    eligible_rows = [
        row for row in active_alerts
        if evaluate_delivery_eligibility(
            event_id=row.event_id, state=row.state, confidence=row.confidence,
            last_delivered_at=row.last_delivered_at, now=now,
        ).eligible
    ]

    already_selected_today = repository.count_delivered_since(
        profile_id=profile_id,
        since=resolve_daily_cap_window_start(lat, lon, now),
    )

    selected_candidates = select_user_facing_alerts(
        (alert_candidate_from_row(r) for r in eligible_rows),
        already_selected_today=already_selected_today,
        max_alerts=MAX_USER_FACING_ALERTS,
    )
    selected_ids = {c.event_id for c in selected_candidates}
    selected_rows = [r for r in eligible_rows if r.event_id in selected_ids]
    return UserFacingAlertsResult(selected=selected_rows, eligible_count=len(eligible_rows))
