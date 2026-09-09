# transit_engine.py
# Current + next 12 rashi transits with motion, IST based

import swisseph as swe
import datetime
from datetime import timedelta
import pytz

from lahiri_mode import ensure_lahiri_mode

# Swiss Ephemeris setup
swe.set_ephe_path('/usr/share/ephe')
swe.set_sid_mode(swe.SIDM_LAHIRI)
# U4C.2B -- the two lines above remain (ephemeris path + sidereal mode)
# but are no longer SUFFICIENT on their own: they only protect the
# thread that performs this import (U4C.2A proved swe.set_sid_mode() is
# THREAD-LOCAL). Every function below that actually calls swe.calc_ut()/
# swe.get_ayanamsa_ut() now calls ensure_lahiri_mode() itself,
# immediately before that call, so it is correct on ANY thread --
# never dependent on this import having already run on the same
# thread. Kept here anyway so a bare `import transit_engine` with no
# calculation at all still leaves the importing thread in the
# historically-expected state.

RASHIS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

PLANET_IDS = {
    0:'Sun', 1:'Moon', 2:'Mercury', 3:'Venus', 4:'Mars',
    5:'Jupiter', 6:'Saturn', swe.MEAN_NODE:'Rahu'
}
NAME_TO_ID = {v:k for k,v in PLANET_IDS.items()}

def _ist_now():
    return datetime.datetime.now(pytz.timezone("Asia/Kolkata"))

def _to_julday_utc(dt_any_tz: datetime.datetime) -> float:
    dt_utc = dt_any_tz.astimezone(pytz.UTC)
    hour = dt_utc.hour + dt_utc.minute/60.0 + dt_utc.second/3600.0
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)

def _rashi_from_sidereal_lon(sid_lon: float) -> str:
    return RASHIS[int(sid_lon // 30) % 12]

def get_current_positions():
    ensure_lahiri_mode()  # U4C.2B -- establish Lahiri on THIS thread, every call
    now_ist = _ist_now()
    jd = _to_julday_utc(now_ist)
    ay = swe.get_ayanamsa_ut(jd)

    out = {}
    for pid, name in PLANET_IDS.items():
        res, _ = swe.calc_ut(jd, pid)
        lon = res[0]
        speed = res[3] if len(res) > 3 else 0.0
        sid_lon = (lon - ay) % 360
        out[name] = {
            "rashi": _rashi_from_sidereal_lon(sid_lon),
            "degree": round(sid_lon % 30, 2),
            "motion": "Retrograde" if speed < 0 else "Direct"
        }

    rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
    ketu_sid = (rahu_sid + 180.0) % 360
    out["Ketu"] = {
        "rashi": _rashi_from_sidereal_lon(ketu_sid),
        "degree": round(ketu_sid % 30, 2),
        "motion": "Retrograde"
    }

    return {
        "timestamp_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "positions": out
    }

def _planet_rashi_on_day(planet_name: str, day_ist: datetime.datetime) -> str:
    # U4C.1 -- despite the name (kept unchanged for backward compatibility
    # with existing callers, e.g. services/festivals/holi_rashi_tips.py),
    # this accepts ANY aware instant, not just an IST midnight -- it is
    # the exact same Lahiri/Swiss-Ephemeris primitive get_current_
    # positions() itself uses, and is now also the sign oracle
    # _bisect_boundary() below calls at sub-day precision. No astrology
    # math lives anywhere else; a corrected ingress date is purely a
    # narrower search for WHEN this unchanged calculation flips sign.
    #
    # U4C.2B -- this is one of the two lowest-level primitives that
    # actually calls swe.calc_ut()/swe.get_ayanamsa_ut() in this file
    # (the other is get_current_positions() above); EVERY other
    # function in this module (_bisect_boundary, _find_sign_boundaries,
    # _get_rashi_transits, get_current_sign_residency,
    # _nearest_boundary_from, get_next_12_rashi_segments, ...) routes
    # through this one or _planet_motion_on_day() below, so guarding
    # these two protects the entire file's public surface without
    # scattering the guard across every caller.
    ensure_lahiri_mode()
    jd = _to_julday_utc(day_ist)
    ay = swe.get_ayanamsa_ut(jd)
    if planet_name == "Ketu":
        rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
        sid = (rahu_sid + 180.0) % 360
    else:
        pid = swe.MEAN_NODE if planet_name == "Rahu" else NAME_TO_ID[planet_name]
        sid = (swe.calc_ut(jd, pid)[0][0] - ay) % 360
    return _rashi_from_sidereal_lon(sid)

def _planet_motion_on_day(planet_name: str, day_ist: datetime.datetime) -> str:
    # U4C.2B -- retrograde speed itself is unaffected by ayanamsa (a
    # constant offset doesn't change a rate of change), so this call
    # was never actually vulnerable to the U4C.2A bug -- guarded anyway
    # for consistency with every other swe.calc_ut() entry point in
    # this file, and in case a future change ever makes this function
    # sidereal-position-dependent.
    ensure_lahiri_mode()
    jd = _to_julday_utc(day_ist)
    pid = swe.MEAN_NODE if planet_name in ("Rahu", "Ketu") else NAME_TO_ID[planet_name]
    speed = swe.calc_ut(jd, pid)[0][3]
    return "Retrograde" if speed < 0 else "Direct"

# ---------------------------------------------------------------
# U4C.1 -- CANONICAL INGRESS-BOUNDARY DETECTION
# ---------------------------------------------------------------
# U4C.0 root cause: the previous implementation of this file (and an
# independently duplicated copy in smart_transit_engine.py) sampled
# planetary sign only at IST midnight, one calendar day at a time, and
# labelled "entering_date" as the FIRST midnight sample that already
# showed the new sign. If the true ingress instant fell on day D (at
# any hour), the sample at day D's own midnight still showed the OLD
# sign (the ingress hadn't happened yet that day), so the new sign was
# only ever first VISIBLE at day D+1's midnight -- entering_date was
# therefore always exactly one calendar day (IST) LATER than the true
# ingress instant, for every planet, deterministically (proved via
# bisection against a real Moon ingress in U4C.0's audit).
#
# Fix: day-level scanning is still used ONLY to locate a <=24h bracket
# in which the sign changes (same cadence/cost as before -- this is not
# a performance regression, see U4C.1 report Sec.16). Once a bracket is
# found, _bisect_boundary() below binary-searches within it for the
# actual instant the sign flips, using the SAME _planet_rashi_on_day()
# primitive as the sign oracle. entering_date is then derived from that
# instant's own Asia/Kolkata calendar date -- never from which midnight
# sample happened to reveal it. No ephemeris call, ayanamsa, sidereal
# conversion, sign-classification, retrograde rule, or Jyotish rule is
# changed anywhere in this file; this is a date-boundary-detection
# correction only.
_BISECTION_ITERATIONS = 24  # narrows a <=24h bracket to ~24h / 2**24 =~ 5ms -- far exceeds the "minute-level or better" precision this product needs (see U4C.1 report Sec.5).

def _bisect_boundary(planet_name: str, earlier_dt: datetime.datetime, later_dt: datetime.datetime, earlier_rashi: str) -> datetime.datetime:
    """U4C.1 -- given two aware instants earlier_dt < later_dt where the
    planet's sidereal sign is `earlier_rashi` at earlier_dt and a
    DIFFERENT sign at later_dt, binary-search for the true boundary
    instant where the sign first changes.

    Assumes at most ONE sign-boundary crossing inside (earlier_dt,
    later_dt]. This holds for every one of the 9 tracked planets over
    any <=24h window used here: a planet only stations (near-zero
    angular speed) during a retrograde turn, so a there-and-back
    double-crossing of the SAME boundary within a single calendar day
    is not astronomically possible for Sun/Moon/Mercury/Venus/Mars/
    Jupiter/Saturn/Rahu/Ketu (see U4C.1 report Sec.9/11). This function
    does not decide WHETHER a boundary exists (the caller already
    confirmed that by sampling both ends) -- only WHEN, to sub-minute
    precision.
    """
    lo, hi = earlier_dt, later_dt
    for _ in range(_BISECTION_ITERATIONS):
        mid = lo + (hi - lo) / 2
        if _planet_rashi_on_day(planet_name, mid) == earlier_rashi:
            lo = mid
        else:
            hi = mid
    return hi  # always already on the new-sign side; converges to the true boundary from above


def _find_sign_boundaries(planet_name: str, count: int, direction: str = "forward"):
    """U4C.1 -- the ONE canonical boundary-detection routine (see report
    Sec.3/4). Returns up to `count` chronologically-ordered boundary
    crossings as (instant_utc, older_rashi, newer_rashi) tuples, where
    `older_rashi`/`newer_rashi` ALWAYS refer to true chronological order
    (the sign immediately before / immediately after the instant) --
    never scan order, regardless of `direction`.

    Retrograde re-entries are never deduplicated by sign name: each
    detected boundary is its own tuple, so a Sign A -> B -> A -> B
    retrograde dance yields 4 separate, independently-dated boundaries,
    exactly as many as the coarse day-level scan actually detects (see
    U4C.1 report Sec.11 for a real Jupiter/Saturn example).

    Anchored at today's IST MIDNIGHT, by design -- this is what makes
    the "next 12 upcoming transitions" contract well-defined and stable
    across a single calendar day (U4C.1, frozen). get_current_sign_
    residency() below deliberately does NOT reuse this anchor -- see
    its own docstring (U4C.2) for why a midnight anchor is wrong for
    "which segment contains the live instant right now"."""
    if planet_name not in NAME_TO_ID and planet_name not in ("Rahu", "Ketu"):
        raise ValueError(f"Invalid planet: {planet_name}")
    if direction not in ("forward", "backward"):
        raise ValueError("direction must be 'forward' or 'backward'")

    step = timedelta(days=1) if direction == "forward" else timedelta(days=-1)
    anchor = _ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_cap = anchor + (timedelta(days=365 * 40) if direction == "forward" else -timedelta(days=365 * 40))

    prev_point = anchor
    prev_rashi = _planet_rashi_on_day(planet_name, prev_point)

    boundaries = []
    day = prev_point + step
    while ((direction == "forward" and day <= end_cap) or (direction == "backward" and day >= end_cap)) and len(boundaries) < count:
        r = _planet_rashi_on_day(planet_name, day)
        if r != prev_rashi:
            if direction == "forward":
                earlier_dt, later_dt, earlier_rashi, later_rashi = prev_point, day, prev_rashi, r
            else:
                earlier_dt, later_dt, earlier_rashi, later_rashi = day, prev_point, r, prev_rashi
            instant = _bisect_boundary(planet_name, earlier_dt, later_dt, earlier_rashi)
            boundaries.append((instant, earlier_rashi, later_rashi))
            prev_rashi = r
        prev_point = day
        day += step

    return boundaries


def _get_rashi_transits(planet_name: str, direction: str = "forward", count: int = 12) -> list:
    """U4C.1 -- public-shape ingress/exit event list. FROZEN CONTRACT:
    entering_date is the Asia/Kolkata calendar date CONTAINING THE
    ACTUAL INGRESS INSTANT (never "the first following midnight whose
    sign already differs" -- the U4C.0-confirmed bug). exit_date keeps
    its existing public meaning -- the last calendar date the reported
    sign is still occupied, i.e. one day before the NEXT boundary's own
    entering_date -- now derived from a real chained boundary instant
    instead of a separate day-by-day probe. That day-by-day probe is
    what previously made every backward (`direction="backward"`) event
    degenerate to entering_date == exit_date (see U4C.1 report Sec.7/8):
    probing forward one day past an already-mislabelled entering_date
    immediately found a different sign and closed the "exit" on the
    same day it started. This chains real boundaries instead, so
    backward events now get a genuine, non-degenerate exit_date for the
    first time.

    from_rashi/to_rashi keep their EXISTING per-direction meaning
    exactly: forward events read (from=older/current, to=newer/future),
    backward events read (from=newer/closer-to-today,
    to=older/further-in-the-past) -- unchanged from the pre-U4C.1
    contract, verified against live smart_transit_engine.get_prev_
    transits() output before this fix (see U4C.1 report Sec.7)."""
    ist = pytz.timezone("Asia/Kolkata")
    boundaries = _find_sign_boundaries(planet_name, count + 1, direction=direction)
    usable = max(0, len(boundaries) - 1)

    events = []
    for i in range(usable):
        instant_i, older_i, newer_i = boundaries[i]
        instant_next, _older_next, _newer_next = boundaries[i + 1]
        if direction == "forward":
            from_rashi, to_rashi = older_i, newer_i
            entering_instant, exit_boundary_instant = instant_i, instant_next
        else:
            from_rashi, to_rashi = newer_i, older_i
            entering_instant, exit_boundary_instant = instant_next, instant_i
        motion = _planet_motion_on_day(planet_name, entering_instant)
        events.append({
            "planet": planet_name,
            "from_rashi": from_rashi,
            "to_rashi": to_rashi,
            "entering_date": entering_instant.astimezone(ist).strftime("%Y-%m-%d"),
            "motion": motion,
            "exit_date": (exit_boundary_instant.astimezone(ist) - timedelta(days=1)).strftime("%Y-%m-%d"),
        })
    return events


def _nearest_boundary_from(planet_name: str, live_instant: datetime.datetime, live_sign: str, direction: str):
    """U4C.2 -- helper for get_current_sign_residency() below. Starting
    from `live_instant` (an arbitrary, un-truncated instant -- NOT
    midnight), steps one calendar day at a time in `direction` until
    the sign differs from `live_sign`, then bisects that <=24h bracket
    with the SAME _bisect_boundary() primitive every other boundary
    search in this file uses. Returns the boundary instant where
    `live_sign` begins (direction="backward") or ends
    (direction="forward"). Bounded by the same 40-year cap used
    elsewhere; returns None if nothing is found within it (should not
    happen in practice)."""
    step = timedelta(days=1) if direction == "forward" else timedelta(days=-1)
    prev_point = live_instant
    point = live_instant + step
    for _ in range(365 * 40):
        r = _planet_rashi_on_day(planet_name, point)
        if r != live_sign:
            if direction == "forward":
                return _bisect_boundary(planet_name, prev_point, point, live_sign)
            return _bisect_boundary(planet_name, point, prev_point, r)
        prev_point = point
        point += step
    return None


def get_current_sign_residency(planet_name: str, as_of: datetime.datetime = None) -> dict:
    """U4C.1A/U4C.2 -- returns the sign residency segment CONTAINING
    `as_of` (default None -- the real live "now"; every production call
    path uses this default), never a past or future segment merely
    sharing the same sign name, and ALWAYS agreeing with
    get_current_positions()'s own live sign for the same instant (see
    U4C.2 report Sec.4 -- this is a mandatory invariant, verified by
    regression test).

    This is what services/sadhesati_report_generator.py's phase_dates
    loop needs for a user's currently ACTIVE phase (U4C.1A), and what
    the website's transit pages need for a correct "Current Period"
    (U4C.2) -- both were missing entirely: _get_rashi_transits()'s own
    forward/backward lists only ever contain COMPLETED past segments or
    NOT-YET-STARTED future segments -- the segment presently in
    progress never appears as a "to_rashi" match in either list, so a
    plain sign-name search falls through to the next FUTURE re-entry of
    the same sign, however far away, and reports that as if it were the
    current period.

    IMPORTANT (U4C.2 fix to the U4C.1A version of this function): this
    does NOT reuse _find_sign_boundaries()'s day-stepping, because that
    helper anchors at IST MIDNIGHT (correct for _get_rashi_transits()'s
    own "next 12 upcoming transitions" contract, frozen in U4C.1) --
    which silently disagreed with the TRUE live sign whenever an
    ingress had already happened earlier the same day: querying this
    function in the afternoon, after a same-day morning ingress, used
    to still report the sign that had already ended, because both its
    backward and forward searches were anchored at that day's midnight
    (still the OLD sign) rather than the actual live instant. Caught
    live during U4C.2's own regression testing before shipping.

    The fix: get the LIVE sign directly via _planet_rashi_on_day() at
    the exact instant (the same primitive get_current_positions() uses,
    zero precision difference), then search for its start/end boundary
    using _nearest_boundary_from() above, anchored at that SAME live
    instant -- never midnight. No new ingress-date algorithm is
    introduced; _bisect_boundary()/_planet_rashi_on_day() are the exact
    same primitives every other boundary search in this file already
    uses; only the anchor point (live instant vs. midnight) differs,
    and only within this function -- _find_sign_boundaries()/
    _get_rashi_transits()/get_next_12_rashi_segments() are completely
    untouched, so U4C.1's frozen future_transits contract is unaffected.

    `as_of` exists ONLY to let tests prove retrograde-re-entry
    disambiguation (Sign A -> B -> A) against real historical data at a
    chosen instant (see U4C.1A/U4C.2 reports) -- no production caller
    passes it.

    Returns None if a bounding boundary could not be found on either
    side within the 40-year cap (should not happen in practice for any
    of the 9 tracked planets)."""
    if planet_name not in NAME_TO_ID and planet_name not in ("Rahu", "Ketu"):
        raise ValueError(f"Invalid planet: {planet_name}")
    ist = pytz.timezone("Asia/Kolkata")
    live_instant = as_of or _ist_now()
    live_sign = _planet_rashi_on_day(planet_name, live_instant)

    start_instant = _nearest_boundary_from(planet_name, live_instant, live_sign, "backward")
    end_instant = _nearest_boundary_from(planet_name, live_instant, live_sign, "forward")
    if start_instant is None or end_instant is None:
        return None

    from_rashi = _planet_rashi_on_day(planet_name, start_instant - timedelta(minutes=2))
    return {
        "planet": planet_name,
        "from_rashi": from_rashi,
        "to_rashi": live_sign,
        "entering_date": start_instant.astimezone(ist).strftime("%Y-%m-%d"),
        "exit_date": (end_instant.astimezone(ist) - timedelta(days=1)).strftime("%Y-%m-%d"),
        "motion": _planet_motion_on_day(planet_name, start_instant),
    }


def get_next_12_rashi_segments(planet_name: str):
    # U4C.1 -- public signature/behavior contract unchanged (still the
    # next 12 future rashi segments for one planet); dates are now
    # correct, per the canonical implementation above.
    return _get_rashi_transits(planet_name, direction="forward", count=12)

def get_all_planets_next_12():
    planets = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Rahu","Ketu"]
    return {p: get_next_12_rashi_segments(p) for p in planets}

# -------------------------------
# 🔹 ASTRO EVENT WRAPPER
# -------------------------------
def get_transit_events(date):
    # N3 -- Moon was previously excluded here (while already fully supported
    # by _planet_rashi_on_day/_planet_motion_on_day above, and already
    # included by get_all_planets_next_12()'s /api/transit/current). Moon is
    # not a special product exception; it goes through the exact same
    # sign-ingress detection, personalized-house calculation
    # (services/personalization_engine.py::get_users_for_transit(), which
    # already filters to houses [1,4,7,8,10,12] uniformly for every planet
    # and needed no change), and notification pipeline as every other
    # planet. Its faster ~2-3 day cadence is expected and intentional.
    planets = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Rahu","Ketu"]

    events = []

    for planet in planets:
        transitions = get_next_12_rashi_segments(planet)

        for t in transitions:
            if t["entering_date"] != date.strftime("%Y-%m-%d"):
                continue

            events.append({
                "name": f"{planet} enters {t['to_rashi']}",
                "type": "transit",
                "date": date,
                "priority": 2,
                "notify_before_days": 1,
                "notify_same_day": True,
                "meta": {
                    "planet": planet,
                    "rashi": t["to_rashi"].lower()
                }
            })

    return events