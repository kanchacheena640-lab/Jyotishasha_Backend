"""Kharmas engine + /api/events/kharmas tests (standalone check() convention).

No database, network, FCM or production access: the API is exercised through a
minimal Flask app that registers only the events blueprint.

Run:  python test_kharmas_engine.py

Reference values below are TEST DATA ONLY (never used by the engine): the
"Sankranti Moment" and observance ("Sankranti on") dates published by Drik
Panchang for New Delhi (28°38'08"N 77°13'28"E, Asia/Kolkata), read 2026-11-27.
Drik shows minutes only. The site's existing Sankranti engine (which this
service reuses, ayanamsha unchanged) is 2-7 minutes earlier on these dates; the
cause of that difference has not been established. Times are therefore checked
against a 10-minute tolerance and observance DATES must match exactly.
"""

import os
import sys
import threading
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import swisseph as swe  # noqa: E402
from flask import Flask  # noqa: E402

from services import kharmas_engine as k  # noqa: E402
from services.sankranti_engine import _find_exact_ingress, get_sankranti_details  # noqa: E402
from routes.routes_events import routes_events  # noqa: E402

IST = k.IST
DELHI = (28.6356, 77.2244)
passed = failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def ist(*a):
    return datetime(*a, tzinfo=IST)


# (Kharmas id, boundary, Drik moment IST, Drik observance date)
DRIK = [
    ("dhanu-2025", "start", "2025-12-16 04:27", "2025-12-16"),
    ("dhanu-2025", "end",   "2026-01-14 15:13", "2026-01-14"),
    ("meena-2026", "start", "2026-03-15 01:08", "2026-03-15"),
    ("meena-2026", "end",   "2026-04-14 09:39", "2026-04-14"),
    ("dhanu-2026", "start", "2026-12-16 10:29", "2026-12-16"),
    ("dhanu-2026", "end",   "2027-01-14 21:14", "2027-01-15"),
    ("meena-2027", "start", "2027-03-15 07:04", "2027-03-15"),
    ("meena-2027", "end",   "2027-04-14 15:33", "2027-04-14"),
    ("dhanu-2027", "start", "2027-12-16 16:42", "2027-12-16"),
    ("dhanu-2027", "end",   "2028-01-15 03:26", "2028-01-15"),
]


def periods_by_id(years, **kw):
    out = {}
    for y in years:
        for p in k.get_kharmas_periods(y, latitude=DELHI[0], longitude=DELHI[1], **kw):
            out[p["id"]] = p
    return out


print("\n[1] Reference comparison vs Drik Panchang (New Delhi)")
P = periods_by_id((2025, 2026, 2027))
print(f"  {'period':11} {'bound':5} {'engine ingress (IST)':26} {'Drik':16} {'diff':>7}  obs engine / Drik")
for pid, bound, drik_moment, drik_obs in DRIK:
    b = P[pid][bound]
    eng = datetime.fromisoformat(b["ingress"])
    ref = datetime.strptime(drik_moment, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    diff = (eng - ref).total_seconds() / 60
    print(f"  {pid:11} {bound:5} {b['ingress']:26} {drik_moment:16} {diff:+6.1f}m  {b['observance_date']} / {drik_obs}")
    check(f"{pid} {bound}: ingress within 10 min of Drik", abs(diff) <= 10, f"diff={diff:+.1f}m")
    check(f"{pid} {bound}: observance date matches Drik", b["observance_date"] == drik_obs, b["observance_date"])

print("\n[2] Same instants as the existing Sankranti engine (no duplicated astronomy)")
for pid, p in P.items():
    for bound in ("start", "end"):
        eng = datetime.fromisoformat(p[bound]["ingress"])
        legacy = get_sankranti_details(eng.date(), DELHI[0], DELHI[1], "en")
        check(f"{pid} {bound} == get_sankranti_details() ingress_time",
              legacy is not None and legacy["ingress_time"] == eng.strftime("%H:%M")
              and legacy["sun_enters"] == p[bound]["sun_enters"]["name"], str(legacy))

print("\n[3] Structure for every year 2000-2060")
bad = []
for y in range(2000, 2061):
    ps = {p["kind"]: p for p in k.get_kharmas_periods(y, at=ist(y, 6, 1))}
    d, m = ps["dhanu"], ps["meena"]
    ds, de = datetime.fromisoformat(d["start"]["ingress"]), datetime.fromisoformat(d["end"]["ingress"])
    ms, me = datetime.fromisoformat(m["start"]["ingress"]), datetime.fromisoformat(m["end"]["ingress"])
    ok = (ds.year == y and ds.month == 12 and de.year == y + 1 and de.month == 1
          and ms.year == y and ms.month == 3 and me.month == 4
          and d["sun_sign"]["index"] == 8 and d["end"]["sun_enters"]["index"] == 9
          and m["sun_sign"]["index"] == 11 and m["end"]["sun_enters"]["index"] == 0
          and 28.5 <= d["duration_days"] <= 30.5 and 29.5 <= m["duration_days"] <= 31.5
          and ds.utcoffset() == timedelta(hours=5, minutes=30))
    if not ok:
        bad.append(y)
check("61 years: Dhanu Dec(y)->Jan(y+1), Meena Mar->Apr, correct signs, durations, +05:30 offsets", not bad, bad)

print("\n[4] Boundaries: start inclusive, end exclusive")
d26 = P["dhanu-2026"]
S = datetime.fromisoformat(d26["start"]["ingress"])
E = datetime.fromisoformat(d26["end"]["ingress"])
# exact internal instants (sub-second) from the cached yearly calculation
_, s_exact, _, e_exact, _ = [p for p in k._periods_starting_in(2026)[0] if p[0] == "dhanu"][0]
st = lambda at: k.get_kharmas_status(at=at)
check("1 s before start: not Kharmas, dhanu-2026 upcoming",
      not st(s_exact - timedelta(seconds=1))["is_kharmas"] and st(s_exact - timedelta(seconds=1))["upcoming"]["id"] == "dhanu-2026")
check("exactly at start: Kharmas, current dhanu-2026 active",
      st(s_exact)["is_kharmas"] and st(s_exact)["current"]["id"] == "dhanu-2026" and st(s_exact)["current"]["status"] == "active")
check("1 s before end: still Kharmas", st(e_exact - timedelta(seconds=1))["is_kharmas"])
r = st(e_exact)
check("exactly at end: not Kharmas, dhanu-2026 now previous (completed)",
      not r["is_kharmas"] and r["previous"]["id"] == "dhanu-2026" and r["previous"]["status"] == "completed")
check("at end: upcoming is meena-2027", r["upcoming"]["id"] == "meena-2027")
check("period list status flips with the same rule",
      [p["status"] for p in k.get_kharmas_periods(2026, at=e_exact) if p["kind"] == "dhanu"] == ["completed"]
      and [p["status"] for p in k.get_kharmas_periods(2026, at=s_exact) if p["kind"] == "dhanu"] == ["active"])

print("\n[5] Year rollover")
for at in (ist(2026, 12, 31, 23, 59, 59), ist(2027, 1, 1, 0, 0, 0), ist(2027, 1, 10, 12, 0)):
    r = st(at)
    check(f"{at.isoformat()}: current dhanu-2026, previous meena-2026, upcoming meena-2027",
          r["current"]["id"] == "dhanu-2026" and r["previous"]["id"] == "meena-2026" and r["upcoming"]["id"] == "meena-2027", r)
r = st(ist(2026, 11, 27, 12, 0))
check("2026-11-27: no current; previous meena-2026; upcoming dhanu-2026",
      r["current"] is None and r["previous"]["id"] == "meena-2026" and r["upcoming"]["id"] == "dhanu-2026")
r = st(ist(2026, 1, 5, 9, 0))
check("2026-01-05: current dhanu-2025 (started previous calendar year)",
      r["current"]["id"] == "dhanu-2025" and r["upcoming"]["id"] == "meena-2026" and r["previous"]["id"] == "meena-2025")

print("\n[6] IST midnight and timezone handling")
utc_midnight_ist = datetime(2026, 12, 15, 18, 30, tzinfo=timezone.utc)           # = 2026-12-16 00:00 IST
check("UTC input is converted: as_of = 2026-12-16T00:00:00+05:30",
      st(utc_midnight_ist)["as_of"] == "2026-12-16T00:00:00+05:30")
check("IST midnight on the start day (before the 10:25 ingress) is not Kharmas", not st(utc_midnight_ist)["is_kharmas"])
check("naive input is interpreted as IST", st(datetime(2026, 12, 16, 0, 0))["as_of"] == "2026-12-16T00:00:00+05:30")
check("same instant in UTC and IST gives the same status",
      st(s_exact.astimezone(timezone.utc))["is_kharmas"] and st(s_exact.astimezone(timezone.utc))["current"]["id"] == "dhanu-2026")
check("23:59:59 IST on 2027-01-14 (after 21:10 ingress) is not Kharmas", not st(ist(2027, 1, 14, 23, 59, 59))["is_kharmas"])
check("all timestamps are ISO 8601 with +05:30",
      all(d26[b]["ingress"].endswith("+05:30") and "T" in d26[b]["ingress"] for b in ("start", "end")))
check("ingress date and observance date are separate fields (Makar 2027: 14 Jan vs 15 Jan)",
      d26["end"]["ingress"].startswith("2027-01-14") and d26["end"]["observance_date"] == "2027-01-15")

print("\n[7] Threaded execution (Swiss Ephemeris sidereal mode is thread-local)")
main_vals = [p["start"]["ingress"] for p in k.get_kharmas_periods(2030)]
res = {}


def in_fresh_thread(name, fn):
    t = threading.Thread(target=lambda: res.__setitem__(name, fn()))
    t.start()
    t.join()


def unguarded():
    swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)  # what a never-initialised thread effectively has
    return _find_exact_ingress(datetime(2030, 12, 16).date())


def guarded():
    swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
    k.clear_caches()
    return [p["start"]["ingress"] for p in k.get_kharmas_periods(2030)]


in_fresh_thread("unguarded", unguarded)
in_fresh_thread("guarded", guarded)
dhanu_main = [p for p in k.get_kharmas_periods(2030) if p["kind"] == "dhanu"][0]["start"]["ingress"]
check("control: the raw engine in a thread with the wrong mode gives a different answer",
      res["unguarded"] is None or res["unguarded"].strftime("%Y-%m-%dT%H:%M") != dhanu_main[:16], res["unguarded"])
check("kharmas engine in a fresh thread with the wrong mode == main thread (ensure_lahiri_mode works)",
      res["guarded"] == main_vals, (res["guarded"], main_vals))
k.clear_caches()
outs, errs = [], []


def worker(y):
    try:
        outs.append((y, tuple(p["start"]["ingress"] for p in k.get_kharmas_periods(y))))
    except Exception as e:  # pragma: no cover
        errs.append(repr(e))


ts = [threading.Thread(target=worker, args=(2031 + (i % 4),)) for i in range(16)]
[t.start() for t in ts]
[t.join() for t in ts]
check("16 concurrent threads over 4 years: no errors, identical results per year",
      not errs and all(len({o for (y, o) in outs if y == yy}) == 1 for yy in range(2031, 2035)), errs)

print("\n[8] Caching: yearly results bounded and reused; live status never cached")
k.clear_caches()
k.get_kharmas_periods(2026)
k.get_kharmas_periods(2026)
info = k._periods_starting_in.cache_info()
check("second yearly call is a cache hit", info.hits >= 1 and info.misses == 1, info)
check("yearly cache is bounded (maxsize 64), observance cache bounded (256)",
      info.maxsize == 64 and k._observance_date.cache_info().maxsize == 256)
a = st(s_exact - timedelta(seconds=1))
b = st(s_exact)
check("same cached year, different instants -> different live status", a["is_kharmas"] is False and b["is_kharmas"] is True)

print("\n[9] Languages")
hi = periods_by_id((2026,), language="hi")["dhanu-2026"]
check("Hindi names", hi["name"] == "धनु खरमास" and hi["sun_sign"]["name"] == "धनु"
      and hi["start"]["sankranti"] == "धनु संक्रांति" and hi["end"]["sankranti"] == "मकर संक्रांति"
      and hi["end"]["sun_enters"]["name"] == "मकर", hi)
check("Hindi status label", k.get_kharmas_status(at=s_exact, language="hi")["current"]["status_label"] == "जारी")
check("Meena Hindi names", periods_by_id((2027,), language="hi")["meena-2027"]["name"] == "मीन खरमास")
check("English names", d26["name"] == "Dhanu Kharmas" and d26["start"]["sankranti"] == "Dhanu Sankranti"
      and d26["end"]["sankranti"] == "Makar Sankranti")
check("instants identical across languages", hi["start"]["ingress"] == d26["start"]["ingress"] and hi["end"]["ingress"] == d26["end"]["ingress"])

print("\n[10] Input validation")


def raises(fn):
    try:
        fn()
    except k.KharmasInputError:
        return True
    return False


check("year below range", raises(lambda: k.get_kharmas_periods(1899)))
check("year above range", raises(lambda: k.get_kharmas_periods(2101)))
check("year not int", raises(lambda: k.get_kharmas_periods("2026")) and raises(lambda: k.get_kharmas_periods(True)))
check("bad language", raises(lambda: k.get_kharmas_status(language="fr")))
check("latitude out of range", raises(lambda: k.get_kharmas_status(latitude=91)))
check("longitude not a number", raises(lambda: k.get_kharmas_status(longitude="x")))
check("NaN coordinate", raises(lambda: k.get_kharmas_status(latitude=float("nan"))))
check("instant outside supported range", raises(lambda: k.get_kharmas_status(at=ist(2101, 1, 1))))
check("range edges accepted (1900, 2100)", len(k.get_kharmas_periods(1900)) == 2 and len(k.get_kharmas_periods(2100)) == 2)

print("\n[11] Polar latitude: window still computed, observance unknown")
polar = k.get_kharmas_periods(2026, latitude=70, longitude=20)
dh = [p for p in polar if p["kind"] == "dhanu"][0]
check("ingress unchanged at 70N, observance_date None (no sunset)",
      dh["start"]["ingress"] == d26["start"]["ingress"] and dh["start"]["observance_date"] is None)

print("\n[12] Ephemeris fallback is reported")
eph = k.ephemeris_in_use()
check("ephemeris_in_use() reports a known value", eph in ("moshier_builtin", "swiss_ephemeris_files"), eph)
jd = swe.julday(2026, 12, 16, 5.0)
lon_req = swe.calc_ut(jd, swe.SUN, swe.FLG_SIDEREAL | swe.FLG_SWIEPH)[0][0]
lon_mos = swe.calc_ut(jd, swe.SUN, swe.FLG_SIDEREAL | swe.FLG_MOSEPH)[0][0]
print(f"  info: ephemeris in use = {eph}; Sun lon requested-SWIEPH {lon_req:.6f} vs Moshier {lon_mos:.6f}")
if eph == "moshier_builtin":
    check("without data files the requested ephemeris silently equals Moshier", abs(lon_req - lon_mos) < 1e-9)

print("\n[13] API /api/events/kharmas")
app = Flask(__name__)
app.register_blueprint(routes_events, url_prefix="/api/events")
c = app.test_client()
r = c.post("/api/events/kharmas", json={"at": "2026-12-20T12:00:00+05:30"})
j = r.get_json()
check("EN 200, current dhanu-2026", r.status_code == 200 and j["is_kharmas"] and j["current"]["id"] == "dhanu-2026"
      and j["language"] == "en" and j["timezone"] == "Asia/Kolkata", j)
check("meta block", j["meta"]["ayanamsa"].startswith("Lahiri") and j["meta"]["ephemeris"] == [eph]
      and j["meta"]["supported_years"] == [1900, 2100] and j["meta"]["supported_as_of_years"] == [1901, 2099]
      and "exclusive" in j["meta"]["interval"] and j["meta"]["search_resolution_seconds"] == 1
      and "not established" in j["meta"]["accuracy_note"], j["meta"])
r = c.post("/api/events/kharmas", json={"language": "hi", "date": "2027-03-20", "year": 2027})
j = r.get_json()
check("HI 200 with date + year: current meena-2027, two periods, Hindi labels",
      r.status_code == 200 and j["current"]["id"] == "meena-2027" and j["language"] == "hi"
      and [p["id"] for p in j["periods"]] == ["meena-2027", "dhanu-2027"] and j["current"]["name"] == "मीन खरमास", j)
check("'lang' alias accepted", c.post("/api/events/kharmas", json={"lang": "HI"}).get_json()["language"] == "hi")
check("Z suffix accepted", c.post("/api/events/kharmas", json={"at": "2026-12-15T18:30:00Z"}).get_json()["as_of"] == "2026-12-16T00:00:00+05:30")
check("empty body -> 200 (defaults, now)", c.post("/api/events/kharmas").status_code == 200)
for body, why in [({"language": "fr"}, "language"), ({"year": 2101}, "year range"), ({"year": "abc"}, "year type"),
                  ({"year": True}, "year bool"), ({"latitude": 100}, "latitude"), ({"longitude": "x"}, "longitude"),
                  ({"at": "yesterday"}, "at format"), ({"date": "16-12-2026"}, "date format"),
                  ({"at": "2026-12-16T00:00:00", "date": "2026-12-16"}, "both at and date"), ([1, 2], "non-object body"),
                  ({"at": 123}, "at type"), ({"language": 5}, "language type")]:
    rr = c.post("/api/events/kharmas", json=body)
    check(f"400 for invalid {why}", rr.status_code == 400 and "error" in rr.get_json(), (rr.status_code, rr.get_json()))
check("GET not allowed (POST convention)", c.get("/api/events/kharmas").status_code == 405)
check("existing /api/events/sankranti still answers", c.post("/api/events/sankranti", json={"date": "2026-12-16"}).get_json()["today"]["sun_enters"] == "Sagittarius")

print("\n[14] Supported year boundaries 1900 / 2100 and adjacent years")
for y in (1900, 1901, 2099, 2100):
    ps = {p["kind"]: p for p in k.get_kharmas_periods(y, at=ist(2026, 6, 1))}
    de = datetime.fromisoformat(ps["dhanu"]["end"]["ingress"])
    check(f"year {y}: dhanu-{y} ends in Jan {y + 1}, meena-{y} Mar->Apr {y}",
          ps["dhanu"]["id"] == f"dhanu-{y}" and de.year == y + 1 and de.month == 1
          and ps["meena"]["start"]["ingress"].startswith(f"{y}-03"), ps)
r = st(ist(1901, 1, 5, 12))
check("as_of 1901-01-05 (earliest supported as_of year): current dhanu-1900, previous meena-1900",
      r["current"]["id"] == "dhanu-1900" and r["previous"]["id"] == "meena-1900" and r["upcoming"]["id"] == "meena-1901")
r = st(ist(2099, 12, 31, 23, 59, 59))
check("as_of 2099-12-31 23:59:59 (latest): current dhanu-2099, upcoming meena-2100",
      r["current"]["id"] == "dhanu-2099" and r["upcoming"]["id"] == "meena-2100")
check("as_of in 1900 or 2100 rejected (needs neighbouring years)",
      raises(lambda: st(ist(1900, 6, 1))) and raises(lambda: st(ist(2100, 6, 1))))
check("as_of whose IST year is 2100 is rejected even if given in another zone",
      raises(lambda: st(datetime(2099, 12, 31, 20, 0, tzinfo=timezone(timedelta(hours=-10))))))
check("year 2100 listing works with an as_of in range",
      [p["status"] for p in k.get_kharmas_periods(2100, at=ist(2026, 1, 1))] == ["upcoming", "upcoming"])

print("\n[15] year and as_of are independent")
listed = k.get_kharmas_periods(2030, at=ist(2026, 12, 20))
r = st(ist(2026, 12, 20))
check("year=2030 lists 2030's periods; statuses relative to as_of 2026 (all upcoming)",
      [p["id"] for p in listed] == ["meena-2030", "dhanu-2030"] and all(p["status"] == "upcoming" for p in listed))
check("previous/current/upcoming follow as_of only (current dhanu-2026), not year", r["current"]["id"] == "dhanu-2026")
past = k.get_kharmas_periods(2020, at=ist(2026, 12, 20))
check("past year listing is all completed for a later as_of", all(p["status"] == "completed" for p in past))
j = c.post("/api/events/kharmas", json={"year": 2030, "at": "2026-12-20T12:00:00+05:30"}).get_json()
check("API: same semantics, with both explained in meta.semantics",
      j["current"]["id"] == "dhanu-2026" and [p["status"] for p in j["periods"]] == ["upcoming", "upcoming"]
      and set(j["meta"]["semantics"]) == {"as_of", "year"})
j = c.post("/api/events/kharmas", json={"year": 2026}).get_json()
a0 = datetime.fromisoformat(j["as_of"])
check("API without at: every period status is consistent with the single returned as_of (now)",
      all(p["status"] == k._status(datetime.fromisoformat(p["start"]["ingress"]), datetime.fromisoformat(p["end"]["ingress"]), a0)
          for p in j["periods"] + [x for x in (j["previous"], j["current"], j["upcoming"]) if x]), j["as_of"])

print("\n[16] API validation: malformed JSON, null, booleans, timestamps")
def post_raw(data, ctype="application/json"):
    return c.post("/api/events/kharmas", data=data, content_type=ctype)
for raw, why in [(b"{bad json", "malformed JSON"), (b'{"year": 2026', "truncated JSON"), (b"\xff\xfe", "non-UTF-8 bytes"),
                 (b'"just a string"', "JSON string"), (b"[]", "JSON array"), (b"null", "JSON null body"), (b"123", "JSON number")]:
    rr = post_raw(raw)
    check(f"400 for {why}", rr.status_code == 400 and "error" in rr.get_json(), (rr.status_code, rr.get_data()[:80]))
rr = post_raw(b"{bad", "text/plain")
check("400 for malformed body even with a non-JSON Content-Type", rr.status_code == 400)
rr = post_raw(b'{"year": 2026}', "text/plain")
check("valid JSON accepted regardless of Content-Type", rr.status_code == 200 and rr.get_json()["year"] == 2026)
check("empty body and whitespace body -> 200 defaults", post_raw(b"").status_code == 200 and post_raw(b"  \n").status_code == 200)
nulls = c.post("/api/events/kharmas", json={"language": None, "lang": None, "latitude": None, "longitude": None,
                                             "at": None, "date": None, "year": None})
jn = nulls.get_json()
check("all-null fields == omitted (200, en, no year/periods)",
      nulls.status_code == 200 and jn["language"] == "en" and "periods" not in jn, jn)
check("'at': null with a 'date' value is allowed (null = omitted)",
      c.post("/api/events/kharmas", json={"at": None, "date": "2026-12-20"}).status_code == 200)
for body, why in [({"latitude": True}, "latitude true"), ({"longitude": False}, "longitude false"),
                  ({"language": True}, "language true"), ({"year": False}, "year false"), ({"at": True}, "at true"),
                  ({"date": True}, "date true"), ({"date": 20261220}, "date number"), ({"year": 2026.5}, "year float"),
                  ({"year": "2026x"}, "year junk"), ({"year": "99999999"}, "year huge string"), ({"latitude": "nan"}, "latitude 'nan'"),
                  ({"longitude": "inf"}, "longitude 'inf'"), ({"latitude": []}, "latitude list"),
                  ({"at": "2026-13-01T00:00:00"}, "month 13"), ({"at": "2026-12-32T00:00:00"}, "day 32"),
                  ({"at": "2026-12-16T25:00:00"}, "hour 25"), ({"at": "2026-12-16T10:00:00+25:00"}, "offset +25:00"),
                  ({"at": ""}, "empty at"), ({"at": "9999-12-31T23:59:59"}, "year 9999"), ({"at": "0001-01-01T00:00:00+05:30"}, "year 1"),
                  ({"date": "2026-02-30"}, "Feb 30"), ({"date": " "}, "blank date")]:
    rr = c.post("/api/events/kharmas", json=body)
    check(f"400 for {why}", rr.status_code == 400 and "error" in rr.get_json(), (rr.status_code, rr.get_json()))
check("numeric strings for coordinates still accepted (existing convention)",
      c.post("/api/events/kharmas", json={"latitude": "26.85", "longitude": "80.95"}).status_code == 200)
check("year as digit string accepted", c.post("/api/events/kharmas", json={"year": " 2027 "}).get_json()["year"] == 2027)
check("offsets other than IST accepted and converted",
      c.post("/api/events/kharmas", json={"at": "2026-12-16T04:55:03+00:00"}).get_json()["as_of"] == "2026-12-16T10:25:03+05:30")

print("\n[17] Ephemeris metadata comes from the actual calculation flags")
from services.sankranti_engine import FLAGS as SFLAGS  # noqa: E402
k.clear_caches()
periods, eph_year = k._periods_starting_in(2026)
_pos, ret = swe.calc_ut(swe.julday(2026, 12, 16, 4.9), swe.SUN, SFLAGS)
expected = "moshier_builtin" if ret & swe.FLG_MOSEPH else "swiss_ephemeris_files"
check("engine records the ephemeris from the Sankranti engine's own flags at the ingress instants",
      eph_year == (expected,), (eph_year, ret))
check("Sankranti engine requests sidereal + SWIEPH (no ephemeris path set => Moshier fallback)",
      SFLAGS == swe.FLG_SIDEREAL | swe.FLG_SWIEPH)
j = c.post("/api/events/kharmas", json={"year": 2026, "at": "2026-12-20T12:00:00+05:30"}).get_json()
check("API meta.ephemeris equals the flags observed for the periods it used", j["meta"]["ephemeris"] == [expected], j["meta"]["ephemeris"])

print("\n[18] Observance dates only where the IST-based sunrise model is valid")
nyc = c.post("/api/events/kharmas", json={"year": 2026, "latitude": 40.71, "longitude": -74.0, "at": "2026-12-20T12:00:00+05:30"}).get_json()
check("New York: ingress instants returned, observance_date null, meta.observance_supported false",
      nyc["current"]["start"]["ingress"] == d26["start"]["ingress"] and nyc["current"]["start"]["observance_date"] is None
      and all(p[b]["observance_date"] is None for p in nyc["periods"] for b in ("start", "end"))
      and nyc["meta"]["observance_supported"] is False, nyc["meta"])
dl = c.post("/api/events/kharmas", json={"year": 2026, "at": "2026-12-20T12:00:00+05:30"}).get_json()
check("default (New Delhi): observance dates present, observance_supported true",
      dl["meta"]["observance_supported"] is True and dl["current"]["end"]["observance_date"] == "2027-01-15")
check("region edges: inside at (45, 140) and (-45, 25), outside at (45.01, 80) and (28, 24.99)",
      k.observance_supported(45, 140) and k.observance_supported(-45, 25)
      and not k.observance_supported(45.01, 80) and not k.observance_supported(28, 24.99))
check("Atlantic point from the benchmark (-7.80, -4.45) is outside -> null, never a wrong date",
      all(p[b]["observance_date"] is None for p in k.get_kharmas_periods(1945, latitude=-7.7999, longitude=-4.4472, at=ist(2026, 1, 1))
          for b in ("start", "end")))

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
