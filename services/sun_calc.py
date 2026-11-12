# services/sun_calc.py

from datetime import date, datetime, timedelta, timezone
from astral import Observer
from astral.sun import (
    SUN_APPARENT_RADIUS,
    refraction_at_zenith,
    sunrise,
    sunset,
    zenith,
)
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Astral's own sunrise/sunset criterion: the sun's upper limb on the horizon with
# standard refraction, expressed as a geometric (unrefracted) zenith angle. This is
# exactly what astral.sun.time_of_transit uses for sunrise()/sunset() at sea level.
_HORIZON_ZENITH = 90.0 + SUN_APPARENT_RADIUS
_GEOMETRIC_EVENT_ZENITH = _HORIZON_ZENITH + refraction_at_zenith(_HORIZON_ZENITH)


def _solve_event_with_astral_model(observer, local_date, rising):
    """
    Instant on `local_date` (IST) at which the sun reaches astral's sunrise/sunset
    zenith, found by bisection on astral's own solar-position model
    (astral.sun.zenith). Sunrise is searched 00:00-12:00 IST, sunset 12:00-24:00 IST.
    Raises ValueError when the sun does not cross that zenith in the window.
    """
    start = datetime(
        local_date.year, local_date.month, local_date.day,
        0 if rising else 12, 0, tzinfo=IST
    )
    lo, hi = start, start + timedelta(hours=12)

    def above_event_zenith(t):
        return zenith(
            observer, t.astimezone(timezone.utc), with_refraction=False
        ) - _GEOMETRIC_EVENT_ZENITH

    f_lo, f_hi = above_event_zenith(lo), above_event_zenith(hi)
    if (f_lo > 0) == (f_hi > 0):
        raise ValueError("Sun does not cross the horizon in the search window")

    for _ in range(40):  # 12 h / 2**40 -> far below one microsecond
        mid = lo + (hi - lo) / 2
        f_mid = above_event_zenith(mid)
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid

    return (lo + (hi - lo) / 2).astimezone(IST)


def _event_on_local_date(event_fn, observer, local_date, rising):
    """
    Astral sunrise/sunset for the given India (IST) calendar date.

    Fast path: the exact call used before (tzinfo=IST), so every date that already
    worked returns the identical value.

    Fallback (only when astral raises): astral 3.2 anchors each calculation to a UTC
    date. When the event falls within moments of UTC midnight (sunrise near 05:30 IST,
    e.g. Lucknow on 2027-04-30) no UTC date returns it and astral raises "Unable to
    find a sunrise time on the date specified", although the sun does rise. The event
    is then solved from astral's own solar model with astral's own horizon criterion;
    on ordinary days this agrees with astral's sunrise()/sunset() to about a second.
    No value is estimated or invented: if the sun really does not cross the horizon,
    the original error is raised.
    """
    try:
        return event_fn(observer, date=local_date, tzinfo=IST).astimezone(IST)
    except ValueError as err:
        first_error = err

    try:
        return _solve_event_with_astral_model(observer, local_date, rising)
    except ValueError:
        raise first_error


def calculate_sunrise_sunset(
    target_date,
    latitude,
    longitude
):
    """
    Calculate sunrise and sunset using Astral.
    Returns IST datetime objects.
    """

    try:

        # Normalize date
        if isinstance(target_date, str):
            y, m, d = map(
                int,
                target_date.split("-")
            )

            target_date = datetime(y, m, d)

        elif isinstance(target_date, date):
            target_date = datetime(
                target_date.year,
                target_date.month,
                target_date.day
            )

        elif not isinstance(
            target_date,
            datetime
        ):
            raise ValueError(
                "Invalid date type"
            )

        observer = Observer(
            latitude=latitude,
            longitude=longitude
        )

        sunrise_ist = _event_on_local_date(
            sunrise,
            observer,
            target_date.date(),
            rising=True
        )

        sunset_ist = _event_on_local_date(
            sunset,
            observer,
            target_date.date(),
            rising=False
        )

        return (
            sunrise_ist,
            sunset_ist
        )

    except Exception as e:
        print(
            "[ERROR] Sunrise/sunset calculation failed:",
            e
        )

        return None, None