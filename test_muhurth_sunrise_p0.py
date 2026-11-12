"""
test_muhurth_sunrise_p0.py
--------------------------
Regression tests for the sunrise/sunset P0 behind /api/muhurth/month returning
HTTP 500 for April 2027 (and /api/panchang for 2027-04-30).

Root cause: astral 3.2 anchors sunrise to a UTC date, so a sunrise that falls
moments before UTC midnight (~05:30 IST) is returned for no UTC date and astral
raises "Unable to find a sunrise time on the date specified". sun_calc returned
(None, None) and calculate_panchang crashed on `None - timedelta`. One such day
exists per year per location (Lucknow: 2026-04-30, 2027-04-30, 2028-04-29).

Uses REAL astral / Swiss Ephemeris calculations; nothing astronomical is mocked.
Only the resilience test replaces calculate_panchang for one date to prove one
failing day cannot erase a month. No database, Celery or OpenAI.

Run:  python test_muhurth_sunrise_p0.py
"""

import io
import contextlib
import sys
from datetime import date, timedelta
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from astral import Observer
from astral.sun import sunrise as astral_sunrise, sunset as astral_sunset

from services.sun_calc import calculate_sunrise_sunset
from services.panchang_engine import calculate_panchang
import services.muhurth_engine as engine

IST = ZoneInfo("Asia/Kolkata")
START, END = date(2026, 1, 1), date(2028, 12, 31)
LUCKNOW = (26.8467, 80.9462)  # reference location the website sends
CITIES = {
    "Lucknow": LUCKNOW,
    "Delhi (API default)": (28.61, 77.23),
    "Kolkata": (22.5726, 88.3639),
    "Patna": (25.5941, 85.1376),
    "Mumbai": (19.076, 72.8777),
    "Chennai": (13.0827, 80.2707),
    "Bengaluru": (12.9716, 77.5946),
    "Jaipur": (26.9124, 75.7873),
}
ACTIVITIES = ["marriage", "grah_pravesh", "vehicle", "naamkaran", "childbirth", "gold", "travel", "property"]

passed = 0
failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# 1. Sunrise/sunset exists, lies on the requested IST date and is continuous, for every day.
for city, (lat, lon) in CITIES.items():
    problems = []
    prev = None
    for d in days(START, END):
        sr, ss = quiet(calculate_sunrise_sunset, d, lat, lon)
        if sr is None or ss is None:
            problems.append(f"{d} missing")
            prev = None
            continue
        if sr.date() != d or ss.date() != d or not sr < ss:
            problems.append(f"{d} off-date/order {sr} {ss}")
        if prev is not None:
            step = abs((sr - prev).total_seconds() - 86400)
            if step > 180:  # day-to-day sunrise change is ~0-2 min in India
                problems.append(f"{d} discontinuity {step:.0f}s")
        prev = sr
    check(f"{city}: sunrise/sunset present, on-date and continuous for all {(END - START).days + 1} days 2026-2028",
          not problems, problems[:5])

# 2. Unchanged values: wherever astral already worked, the result is byte-identical to astral.
for city, (lat, lon) in CITIES.items():
    obs = Observer(latitude=lat, longitude=lon)
    diffs = []
    for d in days(START, END):
        try:
            a_sr = astral_sunrise(obs, date=d, tzinfo=IST).astimezone(IST)
            a_ss = astral_sunset(obs, date=d, tzinfo=IST).astimezone(IST)
        except ValueError:
            continue  # the repaired days; covered by tests 1 and 3
        sr, ss = quiet(calculate_sunrise_sunset, d, lat, lon)
        if (sr, ss) != (a_sr, a_ss):
            diffs.append(str(d))
    check(f"{city}: identical to astral on every day astral could already calculate", not diffs, diffs[:5])

# 3. The repaired Lucknow days sit between their neighbours (sunrise is moving earlier in late April).
for d in [date(2026, 4, 30), date(2027, 4, 30), date(2028, 4, 29)]:
    before = quiet(calculate_sunrise_sunset, d - timedelta(days=1), *LUCKNOW)[0]
    today = quiet(calculate_sunrise_sunset, d, *LUCKNOW)[0]
    after = quiet(calculate_sunrise_sunset, d + timedelta(days=1), *LUCKNOW)[0]
    t = lambda x: x.hour * 3600 + x.minute * 60 + x.second + x.microsecond / 1e6
    check(f"Lucknow {d}: repaired sunrise {today:%H:%M:%S} lies between {before:%H:%M:%S} and {after:%H:%M:%S}",
          t(after) < t(today) < t(before))

# 4. calculate_panchang succeeds for every day through December 2028 at the reference location.
errors = []
for d in days(START, END):
    try:
        quiet(calculate_panchang, d, *LUCKNOW, "en")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{d}: {exc}")
check("calculate_panchang works for every day 2026-2028 (Lucknow)", not errors, errors[:5])

# 5. Month API engine: every month Jan 2026 - Dec 2028 for marriage, no skipped days.
month_errors = []
for y in (2026, 2027, 2028):
    for m in range(1, 13):
        skipped = []
        try:
            quiet(engine.next_best_dates_for_month, "marriage", *LUCKNOW, month=m, year=y, skipped=skipped)
        except Exception as exc:  # noqa: BLE001
            month_errors.append(f"{y}-{m:02d}: {exc}")
        if skipped:
            month_errors.append(f"{y}-{m:02d}: skipped {skipped}")
check("marriage month engine: all 36 months 2026-2028 succeed with no skipped days", not month_errors, month_errors[:5])

# 6. All eight activities: the months containing a repaired day, plus year boundaries.
boundary_months = [(2026, 4), (2027, 4), (2028, 4), (2026, 12), (2027, 1), (2027, 12), (2028, 1), (2028, 12)]
act_errors = []
for act in ACTIVITIES:
    for y, m in boundary_months:
        skipped = []
        try:
            res = quiet(engine.next_best_dates_for_month, act, *LUCKNOW, month=m, year=y, skipped=skipped)
            if any(not r["date"].startswith(f"{y}-{m:02d}-") for r in res):
                act_errors.append(f"{act} {y}-{m:02d}: out-of-month date")
        except Exception as exc:  # noqa: BLE001
            act_errors.append(f"{act} {y}-{m:02d}: {exc}")
        if skipped:
            act_errors.append(f"{act} {y}-{m:02d}: skipped {skipped}")
check("all 8 activities: April 2026/2027/2028 and Dec/Jan boundaries succeed, dates stay in month",
      not act_errors, act_errors[:5])

# 7. 60-day window crossing 2027-04-30 (what every topic page requests from ~2 March 2027).
window_errors = []
skipped = []
window = [quiet(engine._panchang_or_skip, date(2027, 3, 15) + timedelta(days=i), *LUCKNOW, skipped) for i in range(60)]
if skipped or any(p is None for p in window):
    window_errors.append(f"skipped {skipped}")
for act in ACTIVITIES:
    rules, _ = engine._load_rules(act)
    try:
        for p in window:
            if p is not None:
                engine._score_and_reasons(p, rules)
    except Exception as exc:  # noqa: BLE001
        window_errors.append(f"{act}: {exc}")
check("60-day window 2027-03-15..2027-05-13: all 60 days computed and scored for all 8 activities",
      not window_errors, window_errors[:3])

# 8. Resilience: one failing day is skipped and reported; the rest of the month survives.
real = engine.calculate_panchang
bad_day = date(2026, 12, 14)


def flaky(d, lat, lon, language="en", ref_dt_ist=None):
    if d == bad_day:
        raise RuntimeError("simulated single-day failure")
    return real(d, lat, lon, language)


engine.calculate_panchang = flaky
try:
    baseline_skipped = []
    skipped = []
    with contextlib.redirect_stderr(io.StringIO()):
        res = quiet(engine.next_best_dates_for_month, "marriage", *LUCKNOW, month=12, year=2026, skipped=skipped)
finally:
    engine.calculate_panchang = real
full = quiet(engine.next_best_dates_for_month, "marriage", *LUCKNOW, month=12, year=2026, skipped=baseline_skipped)
expected = [r for r in full if r["date"] != bad_day.isoformat()]
check("one failing day is skipped and reported, all other results kept",
      skipped == [bad_day.isoformat()] and res == expected and len(res) == len(full) - 1,
      f"skipped={skipped} got={len(res)} full={len(full)}")

# 9. Hindi Dvadashi translation.
item = {"tithi": "Dvadashi", "weekday": "Monday", "nakshatra": "Anuradha",
        "reasons": ["Tithi Dvadashi neutral", "Weekday Monday allowed", "Nakshatra Anuradha allowed"]}
hi = engine.translate_item_to_hindi(item)
check("Hindi translation of Dvadashi", hi["tithi"] == "द्वादशी" and "द्वादशी" in hi["reasons"][0] and "Dvadashi" not in str(hi))

# 10. Route: /api/muhurth/month April 2027 returns 200 with results and an empty skipped_dates.
try:
    from flask import Flask
    from routes.routes_panchang import routes_panchang
    app = Flask(__name__)
    app.register_blueprint(routes_panchang)
    client = app.test_client()
    with contextlib.redirect_stdout(io.StringIO()):
        r = client.post("/api/muhurth/month", json={"activity": "marriage", "month": 4, "year": 2027,
                                                    "latitude": LUCKNOW[0], "longitude": LUCKNOW[1], "language": "hi"})
        body = r.get_json()
        r2 = client.post("/api/panchang", json={"date": "2027-04-30", "latitude": LUCKNOW[0], "longitude": LUCKNOW[1]})
    check("POST /api/muhurth/month April 2027 -> 200, skipped_dates empty, results in April 2027",
          r.status_code == 200 and body.get("skipped_dates") == [] and
          all(x["date"].startswith("2027-04-") for x in body.get("results", [])),
          f"status={r.status_code} body={str(body)[:200]}")
    check("POST /api/panchang 2027-04-30 -> 200", r2.status_code == 200, f"status={r2.status_code}")
except ImportError as exc:
    check("route test imports", False, str(exc))

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
