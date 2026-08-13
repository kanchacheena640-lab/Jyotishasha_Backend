# modules/alerts/sunrise_boundary.py

"""
Sunrise-to-Sunrise Alert Day Boundary Resolver (Phase 3).

Deliberately separate from the Rule Engine and Planning Window Engine
-- this module's ONLY job is "when does the current/next N astrological
alert day start". It reuses the EXISTING, UNMODIFIED production sunrise
calculation (services/sun_calc.py::calculate_sunrise_sunset()) for
every value it returns -- no new astronomy is computed here. It
performs no rule evaluation, no confidence scoring, and no persistence.

Jyotishasha astrology-standard definition (per this phase's spec):
- If current local time is on/after TODAY's local sunrise: the current
  alert day started at TODAY's sunrise.
- If current local time is BEFORE today's local sunrise: the current
  alert day started at YESTERDAY's sunrise (yesterday's alert day has
  not ended yet).
- Validity ends at the NEXT local sunrise, never at midnight.

"Local" means the sunrise computed for the CALLER's own verified
latitude/longitude -- never a hardcoded location. Coordinates are the
caller's responsibility to supply (see
modules/alerts/profile_detection_service.py, which reads them from the
same AppUser.lat/AppUser.lng every Premium Generator already reads).

Timezone note: services/sun_calc.py::calculate_sunrise_sunset() always
LABELS its returned instant as Asia/Kolkata (ZoneInfo), regardless of
the lat/lon supplied -- but the underlying astronomical MOMENT is
computed correctly for those coordinates via astral's own
Observer(latitude, longitude); only the display timezone is fixed.
Since every comparison this module makes is instant-vs-instant (not
label-vs-label), this is not a correctness problem -- it is the
existing infrastructure's known behavior, reused as-is per this
phase's "do not redesign" instruction. "Today"/"yesterday" (which
calendar date to compute sunrise FOR) is anchored to IST, consistent
with every other day-boundary decision already made elsewhere in this
package (planning_window_engine.py::_ist_midnight_today()) and in the
wider notification pipeline (services/event_scheduler.py's own IST
anchor) -- not a new convention introduced here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from services.sun_calc import calculate_sunrise_sunset

from modules.alerts.exceptions import AlertsEngineError

_IST = ZoneInfo("Asia/Kolkata")


class SunriseResolutionError(AlertsEngineError):
    """Raised when a trustworthy alert-day boundary cannot be
    determined -- invalid/missing coordinates, or
    calculate_sunrise_sunset() itself failing (it signals failure by
    returning (None, None), never by raising -- see its own docstring/
    except clause). Callers MUST treat this as "cannot safely evaluate
    this profile right now" and stop before touching persistence --
    never fall back to a silent default that could misclassify a
    still-valid alert as EXPIRED."""


def _valid_coordinate(lat: Optional[float], lon: Optional[float]) -> bool:
    return (
        isinstance(lat, (int, float)) and not isinstance(lat, bool)
        and isinstance(lon, (int, float)) and not isinstance(lon, bool)
        and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0
    )


def _sunrise_for(day: date, lat: float, lon: float) -> datetime:
    """Wraps calculate_sunrise_sunset() (existing, unmodified) and
    converts its (None, None)-on-failure signal into
    SunriseResolutionError, so every caller in this module has exactly
    ONE failure mode to handle."""
    sunrise_dt, _sunset_dt = calculate_sunrise_sunset(day, lat, lon)
    if sunrise_dt is None:
        raise SunriseResolutionError(
            f"calculate_sunrise_sunset() failed for date={day}, lat={lat}, lon={lon}"
        )
    return sunrise_dt


def resolve_current_alert_day_start(
    lat: float,
    lon: float,
    now: Optional[datetime] = None,
) -> datetime:
    """
    Returns the datetime the CURRENT astrological alert day started:
    today's local sunrise if `now` is on/after it, otherwise
    yesterday's local sunrise.

    `now` defaults to the current instant (IST-anchored, matching the
    rest of this package's day-boundary convention -- see module
    docstring) when not supplied; a naive `now` is treated as already
    being in that same reference. Raises SunriseResolutionError for
    invalid/missing coordinates or an underlying sunrise-calculation
    failure -- never guesses, never falls back to midnight silently.
    """
    if not _valid_coordinate(lat, lon):
        raise SunriseResolutionError(f"Invalid or missing coordinates: lat={lat!r}, lon={lon!r}")

    now = now or datetime.now(_IST)
    now = now.replace(tzinfo=_IST) if now.tzinfo is None else now.astimezone(_IST)

    today_sunrise = _sunrise_for(now.date(), lat, lon)
    if now >= today_sunrise:
        return today_sunrise

    return _sunrise_for(now.date() - timedelta(days=1), lat, lon)


def resolve_alert_day_sequence(
    lat: float,
    lon: float,
    count: int,
    now: Optional[datetime] = None,
) -> List[datetime]:
    """
    Returns `count` consecutive sunrise-anchored alert-day START
    moments, beginning with the CURRENT alert day
    (resolve_current_alert_day_start()). Each subsequent entry is that
    calendar day's ACTUAL, freshly-calculated local sunrise -- never a
    fixed +24h offset -- so the sequence correctly reflects real
    astronomical sunrise drift day to day, and correctly crosses
    month/year boundaries (it operates on real `date` arithmetic, which
    already handles calendar rollover).

    Raises SunriseResolutionError under the same conditions as
    resolve_current_alert_day_start() -- if ANY day in the sequence
    cannot be resolved, the WHOLE sequence is untrustworthy and this
    raises rather than returning a partial list.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    anchors = [resolve_current_alert_day_start(lat, lon, now=now)]
    for _ in range(count - 1):
        next_day = anchors[-1].date() + timedelta(days=1)
        anchors.append(_sunrise_for(next_day, lat, lon))

    return anchors
