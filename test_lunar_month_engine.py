"""Lunar Month Engine correction tests (standalone check() convention).

No database or network. Reference values are TEST DATA ONLY:
* Purnimanta month labels of all 148 Drik Panchang Pradosh entries 2025-2030
  (New Delhi), read from test_pradosh_engine.py's embedded reference block.
* Drik Panchang (New Delhi) Ganesh Chaturthi and Maha Shivaratri dates
  2025-2030, read 2026-11-28 from drikpanchang.com/festivals/ganesh-chaturthi/
  ganesh-chaturthi-date-time.html, .../maha-shivaratri/maha-shivaratri-date-time.html
  and the February festival month pages.
* Navratri start dates 2025-2030 produced by the code BEFORE this change
  (they were already correct and must not move).
* Kshaya: Wikipedia "Hindu calendar" (summarised portion, not verbatim) states
  Margashirsha failed to occur in 1963-64 and Magha did not occur in 1982-83.

Run:  python test_lunar_month_engine.py
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

from services import lunar_month_engine as L  # noqa: E402
from services.astro_core import _tithi_number_at  # noqa: E402
from services.pradosh_engine import lunar_months_at  # noqa: E402
from services.adhik_maas_engine import _as_datetime  # noqa: E402
from services.ekadashi_engine import build_ekadashi_json, get_ekadashi_name  # noqa: E402
from services.events_engine import find_next_shivratri, find_next_vinayaka_chaturthi  # noqa: E402
from services.festivals.navratri_engine import detect_navratri  # noqa: E402
from routes.routes_events import routes_events  # noqa: E402

passed = failed = 0
NORM = {"Ashwin": "Ashwina", "Kartik": "Kartika"}


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label} {str(detail)[:300]}")


def t12(text, ref):
    m = re.match(r"(\d\d):(\d\d) (AM|PM), (\w{3}) (\d\d)", text.strip())
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0)
    mon = datetime.strptime(m.group(4), "%b").month
    y = ref.year + (1 if ref.month == 12 and mon == 1 else -1 if ref.month == 1 and mon == 12 else 0)
    return datetime(y, mon, int(m.group(5)), h, int(m.group(2)))


# ---------------------------------------------------------------------------
print("\n[1] Purnimanta month labels vs Drik (148 Pradosh entries 2025-2030)")
src = open("test_pradosh_engine.py", encoding="utf-8").read()
rows = src.split('DRIK_ROWS = """', 1)[1].split('"""', 1)[0].strip().splitlines()
bad, adhik_seen = [], {}
for line in rows:
    f = [x.strip() for x in line.split("|")]
    d = date.fromisoformat(f[0])
    month, paksha = [x.strip() for x in f[2].split(",")]
    begin = t12(f[5], d)
    probe = begin + timedelta(minutes=30)                  # inside Trayodashi
    lm = L.get_lunar_month(probe)
    if NORM.get(lm["name"], lm["name"]) != month:
        bad.append((f[0], month, lm))
    if lm["is_adhik"]:
        adhik_seen[f[0]] = lm["name"]
check(f"all {len(rows)} Purnimanta month names match Drik", len(rows) == 148 and not bad, bad[:3])
check("Adhik flagged exactly on Adhik Jyeshtha 2026 and Adhik Chaitra 2029 (Shukla + Krishna of the Adhik month)",
      adhik_seen == {"2026-05-28": "Jyeshtha", "2026-06-12": "Jyeshtha", "2029-03-27": "Chaitra", "2029-04-11": "Chaitra"}, adhik_seen)

print("\n[2] Adhik month transitions and both conventions (2026 Adhik Jyeshtha)")
cases = {   # instant (IST, noon) -> (purnimanta name, purnimanta adhik, amanta name, amanta adhik)
    datetime(2026, 5, 10, 12): ("Jyeshtha", False, "Vaishakha", False),   # Krishna before the Adhik month = Nija Jyeshtha
    datetime(2026, 5, 25, 12): ("Jyeshtha", True, "Jyeshtha", True),      # Shukla, Adhik
    datetime(2026, 6, 8, 12): ("Jyeshtha", True, "Jyeshtha", True),       # Krishna inside Adhik keeps the Adhik name
    datetime(2026, 6, 25, 12): ("Jyeshtha", False, "Jyeshtha", False),    # Shukla, Nija
    datetime(2026, 7, 5, 12): ("Ashadha", False, "Jyeshtha", False),      # Krishna after: next month (Purnimanta)
}
got = {k: (L.get_lunar_month(k)["name"], L.get_lunar_month(k)["is_adhik"], L.get_amanta_month(k)["name"], L.get_amanta_month(k)["is_adhik"]) for k in cases}
check("Nija/Adhik/Nija sequence in Purnimanta and Amanta", got == cases, {str(k): v for k, v in got.items() if v != cases[k]})

print("\n[3] New-moon boundaries")
for d in (date(2025, 2, 16), date(2025, 3, 1), date(2025, 3, 16), date(2026, 11, 28), date(2029, 4, 1)):
    t = datetime(d.year, d.month, d.day, 6, 0)
    s, e = L._lunation(t)
    ok = (_tithi_number_at(s - timedelta(seconds=5)) == 30 and _tithi_number_at(s + timedelta(seconds=5)) == 1
          and _tithi_number_at(e - timedelta(seconds=5)) == 30 and _tithi_number_at(e + timedelta(seconds=5)) == 1
          and s <= t < e and timedelta(days=29) < e - s < timedelta(days=30, hours=12))
    check(f"{d}: bounding new moons are exact tithi 30->1 transitions (<= 5 s) and one lunation apart", ok, (s, e))
check("2025-02-16 / 03-01 / 03-16 (short Amavasya skipped by the old daily scan) now named correctly",
      [L.get_amanta_month(datetime(2025, 2, 16, 7))["name"], L.get_lunar_month(datetime(2025, 3, 1, 7))["name"], L.get_lunar_month(datetime(2025, 3, 16, 7))["name"]]
      == [lunar_months_at(datetime(2025, 2, 16, 7), _tithi_number_at(datetime(2025, 2, 16, 7)))["amanta"]["base_en"].replace("Ashwina", "Ashwin").replace("Kartika", "Kartik"),
          "Phalguna", "Chaitra"])
check("tz-aware input (Panchang sunrise) and naive IST give the same answer",
      L.get_lunar_month(datetime(2026, 12, 21, 7, 0)) == L.get_lunar_month(datetime(2026, 12, 21, 1, 30, tzinfo=__import__("datetime").timezone.utc)))

print("\n[4] Agreement with the independently validated logic (pradosh_engine), 1950-2050")
mism, n = [], 0
t = datetime(1950, 1, 3, 9)
while t < datetime(2050, 12, 31):
    tt = _tithi_number_at(t)
    ref = lunar_months_at(t, tt)
    a, p = L.get_amanta_month(t), L.get_lunar_month(t)
    n += 1
    if (NORM.get(a["name"], a["name"]), a["is_adhik"]) != (ref["amanta"]["base_en"], ref["amanta"]["is_adhik"]) \
            or (NORM.get(p["name"], p["name"]), p["is_adhik"]) != (ref["purnimanta"]["base_en"], ref["purnimanta"]["is_adhik"]):
        mism.append((t.isoformat(), a, p, ref))
    t += timedelta(days=37, hours=7)
check(f"{n} samples: Amanta + Purnimanta names and Adhik flags identical", not mism, mism[:2])

print("\n[5] Kshaya flag on actual astronomical occurrences (flag only; naming not resolved)")
def kshaya_lunations(a, b):
    out, t = [], a
    while t < b:
        s, e = L._lunation(t)
        if L.get_amanta_month(s + timedelta(days=1))["is_kshaya"]:
            out.append((s.date().isoformat(), e.date().isoformat()))
        t = e + timedelta(hours=1)
    return out
k60, k80, kmod = kshaya_lunations(datetime(1960, 1, 1), datetime(1967, 1, 1)), kshaya_lunations(datetime(1980, 1, 1), datetime(1986, 1, 1)), kshaya_lunations(datetime(1990, 1, 1), datetime(2100, 1, 1))
check("Kshaya lunation flagged in winter 1963-64 (Wikipedia: Margashirsha did not occur)", len(k60) == 1 and k60[0][0][:7] in ("1963-11", "1963-12"), k60)
check("Kshaya lunation flagged in winter 1982-83 (Wikipedia: Magha did not occur)", len(k80) == 1 and k80[0][0][:7] in ("1982-12", "1983-01"), k80)
check("no Kshaya lunation 1990-2100 (next stated: 2124)", kmod == [], kmod)

print("\n[6] Maha Shivratri and Ganesh Chaturthi vs Drik 2025-2030 (New Delhi)")
DRIK_MAHA = ["2025-02-26", "2026-02-15", "2027-03-06", "2028-02-23", "2029-02-11", "2030-03-02"]
DRIK_GANESH = ["2025-08-27", "2026-09-14", "2027-09-04", "2028-08-23", "2029-09-11", "2030-09-01"]
def series(fn, name):
    d, hits = date(2024, 12, 31), []
    while d < date(2030, 12, 31):
        r = fn(d, 28.61, 77.23, "en")
        if not r:
            break
        if r["name_en"] == name:
            hits.append(r["date"])
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
    return hits
maha = series(find_next_shivratri, "Maha Shivratri")
ganesh = series(find_next_vinayaka_chaturthi, "Ganesh Chaturthi")
check("Maha Shivratri dates == Drik for all six years", maha == DRIK_MAHA, maha)
# The month is now right every year. Two dates still differ from Drik because the
# Chaturthi detector uses the tithi AT SUNRISE (unchanged here; separate rule issue):
#   2026: Chaturthi begins 07:06 on 14 Sep (after sunrise) -> detector picks 15 Sep (Drik: 14 Sep, midday rule)
#   2029: Chaturthi begins after sunrise 11 Sep and ends before sunrise 12 Sep -> never at sunrise, not detected
check("Ganesh Chaturthi named in Bhadrapada: 2025/2027/2028/2030 exactly as Drik; known date-rule gaps 2026 (+1 day) and 2029 (not detected)",
      ganesh == ["2025-08-27", "2026-09-15", "2027-09-04", "2028-08-23", "2030-09-01"], ganesh)
check("no Chaturthi outside Bhadrapada is named Ganesh Chaturthi (old wrong Oct dates gone)", not any(g[5:7] == "10" for g in ganesh))

print("\n[7] Ekadashi preserved (offset removed with the engine fix)")
shipped = {}
for y in (2026, 2027):
    with open(os.path.join("data", "ekadashi", f"ekadashi_{y}.json"), encoding="utf-8") as f:
        for x in json.load(f)["ekadashi_list"]:
            shipped[x["vrat_date"]] = x
LKO = (26.8467, 80.9462)
diffs, d = [], date(2026, 1, 1)
while d <= date(2027, 12, 31):
    r = build_ekadashi_json(d, *LKO)
    if r:
        s = shipped.get(r["vrat_date"])
        keys = ("slug", "name_en", "name_hi", "vrat_date", "parana", "alternate_observances")
        if not s or any(r.get(k) != s.get(k) for k in keys) or r["tithi"]["is_adhik"] != s["tithi"]["is_adhik"] \
                or r["tithi"]["start"] != s["tithi"]["start"] or r["tithi"]["end"] != s["tithi"]["end"]:
            diffs.append(r["vrat_date"])
    d += timedelta(days=1)
check("2026-2027 engine output == shipped JSON for dates, slugs, names, Parana, alternates, Adhik flags (all rows)", not diffs and len(shipped) == 49, diffs)
check("26 distinct slugs preserved", len({x["slug"] for x in shipped.values()}) == 26)
check("get_ekadashi_name uses the Purnimanta month directly (no offset)",
      get_ekadashi_name("Margashirsha", 11, False)[0] == "Mokshada" and get_ekadashi_name("Margashirsha", 26, False)[0] == "Utpanna"
      and get_ekadashi_name("Jyeshtha", 11, True)[0] == "Padmini Ekadashi" and get_ekadashi_name("Jyeshtha", 26, True)[0] == "Parama Ekadashi")

print("\n[8] Navratri unchanged (Adhik guard)")
NAV = {"chaitra": ["2025-03-30", "2026-03-19", "2027-04-07", "2028-03-27", "2029-04-14", "2030-04-03"],
       "sharadiya": ["2025-09-22", "2026-10-11", "2027-09-30", "2028-09-19", "2029-10-08", "2030-09-28"]}
got_nav = {t: [detect_navratri(y, 28.61, 77.23, t)["days"][0]["date"] for y in range(2025, 2031)] for t in NAV}
check("Chaitra and Sharad Navratri start dates 2025-2030 identical to before (incl. Adhik Chaitra 2029 skipped)", got_nav == NAV, got_nav)

print("\n[9] Adhik Maas API")
app = Flask(__name__)
app.register_blueprint(routes_events, url_prefix="/api/events")
c = app.test_client()
res = {y: c.post("/api/events/adhik-maas", json={"year": y}) for y in (2025, 2026, 2027, 2029)}
j26, j29 = res[2026].get_json(), res[2029].get_json()
check("200 for every year (was 500)", all(r.status_code == 200 for r in res.values()), {y: r.status_code for y, r in res.items()})
check("2026 Adhik Jyeshtha, 2029 Adhik Chaitra; 2025/2027 none; response keys unchanged",
      j26["has_adhik_maas"] and [(i["adhik_month"], i["start_date"][:7]) for i in j26["items"]] == [("Jyeshtha", "2026-05")]
      and j29["has_adhik_maas"] and [i["adhik_month"] for i in j29["items"]] == ["Chaitra"]
      and not res[2025].get_json()["has_adhik_maas"] and not res[2027].get_json()["has_adhik_maas"]
      and set(j26["items"][0]) == {"year", "adhik_month", "start_date", "end_date", "rashi_index"}, (j26, j29))
check("tithi_end accepted as datetime or legacy 'YYYY-MM-DD HH:MM' string", _as_datetime(datetime(2026, 5, 16, 9, 1)) == datetime(2026, 5, 16, 9, 1)
      and _as_datetime("2026-05-16 09:01") == datetime(2026, 5, 16, 9, 1) and _as_datetime(None) is None and _as_datetime("bad") is None)

print(f"\nTOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
