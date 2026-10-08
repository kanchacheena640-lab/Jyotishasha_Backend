"""
test_chhath_engine.py
-------------------------------------------------
Kartik Chhath engine + POST /api/festivals/chhath (CHHATH-02 / 02C).

No DB / app.py dependency -- calls services.festivals.chhath_engine directly
and mounts only the festivals blueprint on a bare Flask app.

Every check carries a tag saying what kind of evidence backs it:
  [PUBLISHED]  golden value copied from a published Panchang (Drik Panchang,
               Patna geoname-id 1260086). Independent of this code base, but
               Drik also applies a per-location sunrise-tithi rule.
  [OBSERVED]   independently reported festival observance (news / government
               holiday), see OBSERVED_SOURCES. Observance != calculation.
  [CONTRACT]   API / response contract and owner-approved display policy.
  [INTERNAL]   consistency of the engine's own output (not external truth).
  [SYNTHETIC]  hand-built inputs (no real calendar case exists).
  [MOCK]       a dependency is monkeypatched to force a failure path.

Sections:
  A. Published Drik Patna dates 2010, 2015-2026
  B. Published Drik tithi / new-moon / sunrise-sunset golden values
  C. Observed festival dates 2016, 2017, 2021, 2023, 2024, 2025
  D. 2025 and 2026 display policy
  E. Edge cases: 2010 vriddhi, 2022 boundary, 2023 month, 2037 normal,
     synthetic kshaya / Adhik Kartik / kshaya-masa
  F. 2000-2100 completion, four-day integrity, all configured cities
  G. Input validation (engine)
  H. API contract, errors, IST default year
"""
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask

import routes.routes_festivals as rf
import services.festivals.chhath_engine as ce
from routes.routes_festivals import routes_festivals
from services.lunar_month_engine import get_amanta_month
from services.sun_calc import calculate_sunrise_sunset

passed = 0
failed = 0


def check(label, ok):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


def dates_of(result):
    return [d["date"] for d in result["days"]]


def minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def within(a_iso, b_iso, mins=2):
    return abs(datetime.fromisoformat(a_iso) - datetime.fromisoformat(b_iso)) <= timedelta(minutes=mins)


def four_days(start):
    d = date.fromisoformat(start)
    return [(d + timedelta(days=k)).isoformat() for k in range(4)]


def input_code(fn):
    try:
        fn()
    except ce.ChhathInputError as e:
        return e.code
    return None


def calc_code(fn):
    try:
        fn()
    except ce.ChhathCalculationError as e:
        return e.code
    return None


PATNA = (25.5941, 85.1376)
DELHI = (28.6139, 77.2090)

# Drik Panchang Patna Chhath calendars:
#   https://www.drikpanchang.com/chhath/chhath-puja-calendar.html?year=YYYY&geoname-id=1260086
# (Nahay Khay first day; four consecutive days).
DRIK_PATNA_NAHAY_KHAY = {
    2010: "2010-11-09", 2015: "2015-11-15", 2016: "2016-11-04", 2017: "2017-10-24",
    2018: "2018-11-11", 2019: "2019-10-31", 2020: "2020-11-18", 2021: "2021-11-08",
    2022: "2022-10-28", 2023: "2023-11-17", 2024: "2024-11-05", 2025: "2025-10-26",
    2026: "2026-11-13",
}
# Drik Patna Shashthi window (chhath-puja-date-time.html?year=YYYY&geoname-id=1260086).
DRIK_SHASHTHI = {
    2010: ("2010-11-11T05:46", "2010-11-12T07:05"),
    2021: ("2021-11-09T10:35", "2021-11-10T08:25"),
    2022: ("2022-10-30T05:49", "2022-10-31T03:27"),
    2023: ("2023-11-18T09:18", "2023-11-19T07:23"),
    2024: ("2024-11-07T00:41", "2024-11-08T00:34"),
    2025: ("2025-10-27T06:04", "2025-10-28T07:59"),
    2026: ("2026-11-14T23:23", "2026-11-16T02:00"),
}
# Drik Patna day Panchang (panchang/day-panchang.html?date=DD/MM/YYYY&geoname-id=1260086):
# "Amavasya upto" = Kartik new moon (Diwali Amavasya end).
DRIK_NEW_MOON = {
    2023: "2023-11-13T14:56", 2024: "2024-11-01T18:16",
    2025: "2025-10-21T17:54", 2026: "2026-11-09T12:31",
}
# Drik Patna sunrise / sunset (calendar + day Panchang pages).
DRIK_PATNA_SUN = [
    ("2010-11-11", "06:04", "17:03"), ("2021-11-10", "06:03", "17:03"),
    ("2022-10-30", "05:56", "17:10"), ("2023-11-19", "06:09", "17:00"),
    ("2023-11-13", "06:05", "17:02"), ("2024-11-01", "05:58", "17:08"),
    ("2025-10-21", "05:51", "17:17"), ("2026-11-09", "06:03", "17:04"),
]
# Independently reported Sandhya Arghya (evening) observance.
OBSERVED_SANDHYA = {
    2016: "2016-11-06",  # newsgram.com/general/2016/11/06/millions-of-people-...-across-bihar
    2017: "2017-10-26",  # indiatvnews.com/photos/india-chhath-puja-2017-...-setting-sun-408629 (Oct 26, 2017)
    2021: "2021-11-10",  # deccanherald.com ... public-holiday-on-november-10-for-chhath-puja-1047673
    2023: "2023-11-19",  # amarujala.com ... chhath-puja-2023 ... 2023-11-19
    2024: "2024-11-07",  # newsonair.gov.in/chhath-festival-2024-devotees-to-offer-sandhya-arghya-...
    2025: "2025-10-27",  # newsonair.gov.in/bihar-witnesses-grand-chhath-celebrations-as-lakhs-offer-sandhya-arghya
}

cache = {}


def chhath(year, **kw):
    key = (year, tuple(sorted(kw.items())))
    if key not in cache:
        cache[key] = ce.calculate_chhath(year, **kw)
    return cache[key]


# ---------------------------------------------------------------- A
print("A. [PUBLISHED] Drik Patna Chhath calendars")
for y, first in DRIK_PATNA_NAHAY_KHAY.items():
    check(f"[PUBLISHED] {y} four days = Drik Patna {first}..", dates_of(chhath(y)) == four_days(first))

# ---------------------------------------------------------------- B
print("B. [PUBLISHED] Tithi, new-moon and sun-time golden values")
for y, (s, e) in DRIK_SHASHTHI.items():
    r = chhath(y)["shashthi"]
    check(f"[PUBLISHED] {y} Shashthi window within 2 min of Drik",
          within(r["start_ist"], s) and within(r["end_ist"], e))
for y, nm in DRIK_NEW_MOON.items():
    check(f"[PUBLISHED] {y} Kartik new moon within 2 min of Drik ({nm})",
          within(chhath(y)["lunar_month"]["new_moon_ist"], nm))
for ds, sr_exp, ss_exp in DRIK_PATNA_SUN:
    sr, ss = ce._sun_times(date.fromisoformat(ds), *PATNA)
    check(f"[PUBLISHED] Patna {ds} sunrise/sunset within 2 min of Drik ({sr_exp}/{ss_exp})",
          abs(minutes(sr.strftime("%H:%M")) - minutes(sr_exp)) <= 2
          and abs(minutes(ss.strftime("%H:%M")) - minutes(ss_exp)) <= 2)
sr, _ = ce._sun_times(date(2025, 10, 27), *DELHI)
check("[PUBLISHED] New Delhi 2025-10-27 sunrise within 2 min of Drik (06:30)",
      abs(minutes(sr.strftime("%H:%M")) - minutes("06:30")) <= 2)

# ---------------------------------------------------------------- C
print("C. [OBSERVED] Independently reported Sandhya Arghya dates")
for y, observed in OBSERVED_SANDHYA.items():
    r = chhath(y)
    primary = r["days"][2]["date"]
    candidate_dates = {c["sandhya_arghya"] for c in r["candidates"]}
    if primary == observed:
        check(f"[OBSERVED] {y} calculated Sandhya Arghya equals observed {observed}", True)
    else:
        check(f"[OBSERVED] {y} calculation differs from observed {observed}: must be needs_review "
              f"with the observed date among candidates",
              r["status"] == "needs_review" and observed in candidate_dates)

# ---------------------------------------------------------------- D
print("D. [CONTRACT] Display policy for 2025 and 2026")
r25 = chhath(2025)
check("[CONTRACT] 2025 calculated dates stay visible (Oct 26-29, Sandhya Arghya Oct 28)",
      dates_of(r25) == four_days("2025-10-26"))
check("[CONTRACT] 2025 status needs_review", r25["status"] == "needs_review")
cand25 = {c["rule_id"]: c for c in r25["candidates"]}
check("[CONTRACT] 2025 primary candidate = Oct 28 and drives days",
      cand25[ce.PRIMARY_RULE_ID]["is_primary"]
      and cand25[ce.PRIMARY_RULE_ID]["sandhya_arghya"] == "2025-10-28"
      and list(cand25[ce.PRIMARY_RULE_ID]["dates"].values()) == dates_of(r25))
check("[CONTRACT] 2025 Oct 27 present via Delhi-sunrise and Patna-sunset candidates",
      cand25[ce.DELHI_RULE_ID]["sandhya_arghya"] == "2025-10-27"
      and cand25[ce.SUNSET_RULE_ID]["sandhya_arghya"] == "2025-10-27")
check("[CONTRACT] 2025 boundary convention marked policy_unapproved",
      "near_sunrise_boundary_threshold_30min" in r25["rule"]["policy_unapproved"])
check("[CONTRACT] 2025 review reasons present", len(r25["review_reasons"]) >= 2)

r26 = chhath(2026)
check("[CONTRACT] 2026 Nov 13-16 confirmed", dates_of(r26) == four_days("2026-11-13") and r26["status"] == "confirmed")
check("[CONTRACT] 2026 Patna Arghya times 17:00 / 06:07",
      r26["days"][2]["arghya_time"] == "17:00" and r26["days"][3]["arghya_time"] == "06:07")
check("[CONTRACT] 2026 all three rules agree on Nov 15",
      {c["sandhya_arghya"] for c in r26["candidates"]} == {"2026-11-15"})
for r in (r25, r26):
    check(f"[CONTRACT] {r['year']} verification says observance not verified",
          r["verification"]["regional_observance_verified"] is False
          and r["verification"]["status_scope"] == "astronomical_calculation_under_selected_rule")
    check(f"[CONTRACT] {r['year']} rule metadata complete",
          r["rule"]["rule_id"] == ce.PRIMARY_RULE_ID and r["rule"]["rule_version"] == ce.RULE_VERSION
          and r["rule"]["reference_location"]["city"] == "patna"
          and r["rule"]["policy_status"] == ce.POLICY_STATUS and r["rule"]["calculation_basis"])

# ---------------------------------------------------------------- E
print("E. Edge cases")
r10 = chhath(2010)
check("[PUBLISHED] 2010 vriddhi: earlier day Nov 11 (Drik Patna)", r10["days"][2]["date"] == "2010-11-11")
check("[INTERNAL] 2010 vriddhi flagged, needs_review, convention policy_unapproved",
      r10["flags"]["vriddhi"] and r10["status"] == "needs_review"
      and "vriddhi_earlier_day" in r10["rule"]["policy_unapproved"]
      and r10["diagnostics"]["reference_udaya_days"] == ["2010-11-11", "2010-11-12"])
r22 = chhath(2022)
check("[INTERNAL] 2022 near-boundary only (Shashthi begins 6-7 min before Patna sunrise)",
      [k for k in ce.STATUS_FLAGS if r22["flags"][k]] == ["near_sunrise_boundary"]
      and r22["status"] == "needs_review")
r23 = chhath(2023)
check("[PUBLISHED] 2023 Kartik new moon 2023-11-13 and Sandhya Arghya Nov 19",
      r23["lunar_month"]["new_moon_ist"].startswith("2023-11-13") and r23["days"][2]["date"] == "2023-11-19")
legacy = get_amanta_month(calculate_sunrise_sunset(date(2023, 11, 19), *PATNA)[0].replace(tzinfo=None))["name"]
print(f"        (info) legacy get_amanta_month at Patna sunrise 2023-11-19 -> {legacy} (not used by engine)")
check("[INTERNAL] 2023 reported as non-Adhik Kartik Shukla",
      r23["lunar_month"]["amanta"] == "Kartik" and r23["lunar_month"]["is_adhik"] is False)
check("[PUBLISHED] 2023 Usha Arghya counted from D (Drik lists Ashtami at sunrise Nov 20)",
      r23["days"][3]["tithi_at_sunrise"]["number"] == 8)
r37 = chhath(2037)
check("[INTERNAL] 2037 normal case: Shashthi at Nov 13 sunrise, confirmed, Nov 11-14",
      not r37["flags"]["kshaya"] and r37["status"] == "confirmed" and dates_of(r37) == four_days("2037-11-11"))

original_udaya = ce.udaya_days
original_lunations = ce._lunations_for_year
original_sun = ce.calculate_sunrise_sunset
original_tithi = ce._tithi_number_at
try:
    def no_patna_sunrise(start, end, lat, lon):
        return [] if (lat, lon) == PATNA else original_udaya(start, end, lat, lon)
    ce.udaya_days = no_patna_sunrise
    rk = ce.calculate_chhath(2024)
finally:
    ce.udaya_days = original_udaya
check("[MOCK] forced kshaya: needs_review, dates still returned, fallback marked policy_unapproved",
      rk["status"] == "needs_review" and rk["flags"]["kshaya"] and len(rk["days"]) == 4
      and rk["rule"]["anchor_basis"] == "kshaya_candidate_sunset"
      and "kshaya_sunset_fallback" in rk["rule"]["policy_unapproved"])

real26 = original_lunations(2026)
k = next(i for i, l in enumerate(real26) if (l["rashi_start"], l["rashi_end"]) == (6, 7))
try:
    fake_adhik = dict(real26[k - 1], rashi_start=6, rashi_end=6)
    ce._lunations_for_year = lambda y: real26[:k - 1] + [fake_adhik] + real26[k:]
    ra = ce.calculate_chhath(2026)
finally:
    ce._lunations_for_year = original_lunations
check("[SYNTHETIC] Adhik Kartik before nija Kartik: skipped, same 2026 dates",
      ra["flags"]["adhik_kartik_skipped"] and ra["lunar_month"]["adhik_kartik_skipped"]
      and dates_of(ra) == four_days("2026-11-13"))
try:
    ce._lunations_for_year = lambda y: [dict(l, rashi_end=8) if i == k else l for i, l in enumerate(real26)]
    rkm = ce.calculate_chhath(2026)
finally:
    ce._lunations_for_year = original_lunations
check("[SYNTHETIC] kshaya-masa lunation covering Kartik -> month_identification_uncertain, needs_review",
      rkm["flags"]["month_identification_uncertain"] and rkm["status"] == "needs_review")
check("[SYNTHETIC] classify_lunation: nija / Adhik / kshaya-masa",
      ce.classify_lunation(6, 7)["indices"] == [7] and ce.classify_lunation(6, 6)["is_adhik"]
      and ce.classify_lunation(6, 6)["index"] == 7 and ce.classify_lunation(7, 9)["is_kshaya_masa"])


def real_lunation(a, b):
    moons = ce.find_new_moons(a, b)
    return ce.classify_lunation(ce._sun_rashi(moons[0] + timedelta(minutes=1)),
                                ce._sun_rashi(moons[1] - timedelta(minutes=1)))


check("[PUBLISHED] real 2023 Adhik Shravana detected",
      real_lunation(datetime(2023, 7, 10), datetime(2023, 8, 20)) == {
          "index": 4, "is_adhik": True, "is_kshaya_masa": False, "indices": [4]})
check("[PUBLISHED] real 2026 Adhik Jyeshtha detected",
      real_lunation(datetime(2026, 5, 10), datetime(2026, 6, 20))["index"] == 2)

# ---------------------------------------------------------------- F
print("F. [INTERNAL] 2000-2100 completion, four-day integrity, configured cities")
problems = []
for y in range(ce.MIN_YEAR, ce.MAX_YEAR + 1):
    try:
        r = chhath(y)
    except Exception as e:  # noqa: BLE001 -- recorded as a failure
        problems.append((y, f"raised {type(e).__name__}"))
        continue
    ds = dates_of(r)
    flags_raised = any(r["flags"][f] for f in ce.STATUS_FLAGS)
    prim = [c for c in r["candidates"] if c["is_primary"]]
    expected_unapproved = (
        (["vriddhi_earlier_day"] if r["flags"]["vriddhi"] else [])
        + (["kshaya_sunset_fallback"] if r["flags"]["kshaya"] else [])
        + (["near_sunrise_boundary_threshold_30min"] if r["flags"]["near_sunrise_boundary"] else []))
    if not (len(ds) == 4 and ds == four_days(ds[0])
            and [d["key"] for d in r["days"]] == ["nahay_khay", "kharna", "sandhya_arghya", "usha_arghya"]
            and r["days"][2]["arghya_event"] == "sunset" and r["days"][3]["arghya_event"] == "sunrise"
            and all(re.fullmatch(r"\d\d:\d\d", d["sunrise"]) and re.fullmatch(r"\d\d:\d\d", d["sunset"])
                    for d in r["days"])):
        problems.append((y, "four-day output"))
    if (r["status"] == "needs_review") != flags_raised or (flags_raised and not r["review_reasons"]):
        problems.append((y, "status/flags"))
    if (len(prim) != 1 or list(prim[0]["dates"].values()) != ds
            or len({c["rule_id"] for c in r["candidates"]}) != 3):
        problems.append((y, "candidates"))
    if r["rule"]["policy_unapproved"] != expected_unapproved:
        problems.append((y, "policy_unapproved"))
    if r["days"][2]["tithi_at_sunrise"]["number"] != 6 and not r["flags"]["kshaya"]:
        problems.append((y, "Sandhya Arghya day lacks Shashthi at Patna sunrise"))
    if r["verification"]["regional_observance_verified"] is not False:
        problems.append((y, "verification"))
check(f"[INTERNAL] {ce.MIN_YEAR}-{ce.MAX_YEAR}: every year computes with valid four-day output, "
      f"consistent status/flags/candidates/policy  {problems[:5]}", not problems)
review_years = [y for y in range(ce.MIN_YEAR, ce.MAX_YEAR + 1) if chhath(y)["status"] == "needs_review"]
print(f"        (info) needs_review years: {review_years}")
check("[INTERNAL] needs_review years are exactly the audited set",
      review_years == [2010, 2022, 2025, 2051, 2072, 2082, 2087])

city_problems = []
for y in (2025, 2026):
    base = dates_of(chhath(y))
    for key in ce.CITIES:
        r = chhath(y, city=key)
        if dates_of(r) != base or r["location"]["city"] != key or r["location"]["tz"] != "Asia/Kolkata":
            city_problems.append((y, key))
check(f"[INTERNAL] all {len(ce.CITIES)} cities: Patna-reference dates, own IST times  {city_problems}",
      not city_problems)
r = {c: chhath(2026, city=c) for c in ("patna", "delhi", "kolkata", "mumbai")}
check("[INTERNAL] local times differ by city (Kolkata < Patna < Mumbai sunset; Delhi sunrise later)",
      minutes(r["kolkata"]["days"][2]["arghya_time"]) < minutes(r["patna"]["days"][2]["arghya_time"])
      < minutes(r["mumbai"]["days"][2]["arghya_time"])
      and minutes(r["delhi"]["days"][3]["arghya_time"]) > minutes(r["patna"]["days"][3]["arghya_time"]))
check("[INTERNAL] 2025 Delhi city: date_differs_by_city flag, dates unchanged",
      chhath(2025, city="delhi")["flags"]["date_differs_by_city"]
      and dates_of(chhath(2025, city="delhi")) == four_days("2025-10-26"))
check("[INTERNAL] every configured city lies inside India bounds",
      all(ce.INDIA_LAT_RANGE[0] <= c["lat"] <= ce.INDIA_LAT_RANGE[1]
          and ce.INDIA_LON_RANGE[0] <= c["lon"] <= ce.INDIA_LON_RANGE[1] for c in ce.CITIES.values()))

# ---------------------------------------------------------------- G
print("G. [CONTRACT] Engine input validation")
for bad in (2026.0, 2026.5, True, False, "abc", "2026.5", "", [2026], {"y": 2026}, 1999, 2101, "1999"):
    check(f"[CONTRACT] year {bad!r} -> INVALID_YEAR",
          input_code(lambda: ce.calculate_chhath(bad)) == "INVALID_YEAR")
check("[CONTRACT] year '2026' (digit string) accepted", ce.calculate_chhath("2026")["year"] == 2026)
for lat, lon in ((True, 85.0), ("nan", 85.0), ("inf", 85.0), ("x", "y"), (51.5, -0.12), (25.0, None), (None, 85.0)):
    check(f"[CONTRACT] coordinates ({lat!r}, {lon!r}) -> INVALID_COORDINATES",
          input_code(lambda: ce.calculate_chhath(2026, latitude=lat, longitude=lon)) == "INVALID_COORDINATES")
check("[CONTRACT] numeric-string coordinates inside India accepted",
      ce.calculate_chhath(2026, latitude="25.3176", longitude="82.9739")["location"]["city"] == "custom")
check("[CONTRACT] city + coordinates -> CONFLICTING_LOCATION",
      input_code(lambda: ce.calculate_chhath(2026, city="patna", latitude=25.0, longitude=85.0))
      == "CONFLICTING_LOCATION")
check("[CONTRACT] city + one coordinate -> CONFLICTING_LOCATION",
      input_code(lambda: ce.calculate_chhath(2026, city="patna", longitude=85.0)) == "CONFLICTING_LOCATION")
check("[CONTRACT] unknown city -> INVALID_CITY", input_code(lambda: ce.calculate_chhath(2026, city="london")) == "INVALID_CITY")
check("[CONTRACT] non-string city -> INVALID_CITY", input_code(lambda: ce.calculate_chhath(2026, city=7)) == "INVALID_CITY")
check("[CONTRACT] city key is case/space-insensitive", ce.calculate_chhath(2026, city=" Patna ")["location"]["city"] == "patna")
for lang in ("fr", 1, ""):
    check(f"[CONTRACT] language {lang!r} -> INVALID_LANGUAGE",
          input_code(lambda: ce.calculate_chhath(2026, language=lang)) == "INVALID_LANGUAGE")
for t in ("chaiti", 5, ""):
    check(f"[CONTRACT] type {t!r} -> INVALID_TYPE",
          input_code(lambda: ce.calculate_chhath(2026, festival_type=t)) == "INVALID_TYPE")
rhi = ce.calculate_chhath(2026, language="HI")
check("[CONTRACT] language 'hi' localises name, weekday, location, tithi; keeps bilingual fields",
      rhi["language"] == "hi" and rhi["days"][2]["name"] == "संध्या अर्घ्य"
      and rhi["days"][2]["weekday_local"] == "रविवार" and rhi["location"]["name"] == "पटना"
      and rhi["days"][2]["tithi_at_sunrise"]["name"] == "षष्ठी" and rhi["days"][2]["name_en"] == "Sandhya Arghya")
check("[CONTRACT] language default 'en'",
      r26["language"] == "en" and r26["days"][2]["name"] == "Sandhya Arghya" and r26["location"]["name"] == "Patna")

# ---------------------------------------------------------------- H
print("H. [CONTRACT] API")
app = Flask(__name__)
app.register_blueprint(routes_festivals, url_prefix="/api/festivals")
client = app.test_client()
URL = "/api/festivals/chhath"


def post(payload=None, **kw):
    resp = client.post(URL, json=payload, **kw) if payload is not None else client.post(URL, **kw)
    return resp.status_code, resp.get_json()


code, body = post({"year": 2026})
check("[CONTRACT] 200 default Patna", code == 200 and body["location"]["city"] == "patna")
for key in ("year", "status", "source", "rule_version", "rule", "verification", "location", "lunar_month",
            "shashthi", "days", "flags", "review_reasons", "candidates", "diagnostics", "language", "type"):
    check(f"[CONTRACT] response has '{key}'", key in body)
code, body = post({"year": 2025, "city": "kolkata"})
check("[CONTRACT] 200 needs_review still returns four dates and candidates",
      code == 200 and body["status"] == "needs_review" and len(body["days"]) == 4 and len(body["candidates"]) == 3)

for payload, err in (({"year": 2026, "city": "atlantis"}, "INVALID_CITY"),
                     ({"year": 1800}, "INVALID_YEAR"),
                     ({"year": 2026.5}, "INVALID_YEAR"),
                     ({"year": 2026.0}, "INVALID_YEAR"),
                     ({"year": True}, "INVALID_YEAR"),
                     ({"year": "abc"}, "INVALID_YEAR"),
                     ({"year": 0}, "INVALID_YEAR"),
                     ({"year": 2026, "latitude": 40.7, "longitude": -74.0}, "INVALID_COORDINATES"),
                     ({"year": 2026, "city": "patna", "latitude": 25.6, "longitude": 85.1}, "CONFLICTING_LOCATION"),
                     ({"year": 2026, "type": "chaiti"}, "INVALID_TYPE"),
                     ({"year": 2026, "language": "fr"}, "INVALID_LANGUAGE"),
                     ([2026], "INVALID_BODY"),
                     ("2026", "INVALID_BODY")):
    code, body = post(payload)
    check(f"[CONTRACT] 400 {err} for {payload!r}",
          code == 400 and body["code"] == err and isinstance(body["error"], str))

check("[CONTRACT] current_ist_year() uses Asia/Kolkata",
      ce.current_ist_year() == datetime.now(ZoneInfo("Asia/Kolkata")).year)
original_year_fn = rf.current_ist_year
try:
    rf.current_ist_year = lambda: 2024
    code, body = post({})
    check("[MOCK] missing year defaults to current_ist_year()", code == 200 and body["year"] == 2024)
finally:
    rf.current_ist_year = original_year_fn
code, body = post(data="not json", content_type="text/plain")
check("[CONTRACT] non-JSON body -> defaults (200, current IST year)",
      code == 200 and body["year"] == ce.current_ist_year())

try:
    ce.calculate_sunrise_sunset = lambda *a, **k: (None, None)
    check("[MOCK] missing sun times -> SUN_TIMES_UNAVAILABLE",
          calc_code(lambda: ce.calculate_chhath(2026)) == "SUN_TIMES_UNAVAILABLE")
    code, body = post({"year": 2026})
    check("[MOCK] API 422 SUN_TIMES_UNAVAILABLE, no dates fabricated",
          code == 422 and body["code"] == "SUN_TIMES_UNAVAILABLE" and "days" not in body)
finally:
    ce.calculate_sunrise_sunset = original_sun

try:
    ce._lunations_for_year = lambda y: []
    check("[MOCK] no Kartik lunation -> KARTIK_NOT_FOUND",
          calc_code(lambda: ce.calculate_chhath(2026)) == "KARTIK_NOT_FOUND")
    code, body = post({"year": 2026})
    check("[MOCK] API 422 KARTIK_NOT_FOUND", code == 422 and body["code"] == "KARTIK_NOT_FOUND" and "days" not in body)
finally:
    ce._lunations_for_year = original_lunations

try:
    ce._lunations_for_year = lambda y: real26
    ce._tithi_number_at = lambda dt: 1
    check("[MOCK] Shashthi never reached -> TITHI_NOT_FOUND",
          calc_code(lambda: ce.calculate_chhath(2026)) == "TITHI_NOT_FOUND")
    code, body = post({"year": 2026})
    check("[MOCK] API 422 TITHI_NOT_FOUND", code == 422 and body["code"] == "TITHI_NOT_FOUND" and "days" not in body)
finally:
    ce._lunations_for_year = original_lunations
    ce._tithi_number_at = original_tithi

original_calc = rf.calculate_chhath
try:
    def boom(*a, **k):
        raise RuntimeError("secret internals /path/to/file")
    rf.calculate_chhath = boom
    code, body = post({"year": 2026})
    check("[MOCK] 500 sanitized: generic message, code ENGINE_ERROR, no internals",
          code == 500 and body == {"error": "Chhath calculation failed", "code": "ENGINE_ERROR"})
finally:
    rf.calculate_chhath = original_calc

code, body = post({"year": 2026})
check("[CONTRACT] mocks restored (2026 back to normal)", code == 200 and body["days"][2]["date"] == "2026-11-15")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
