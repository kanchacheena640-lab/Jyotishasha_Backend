"""Kharmas AWARENESS on Muhurat results (standalone check() convention).

Proves: (1) existing Muhurat output is unchanged -- every result returned by the
routes equals the engine's own output once the additive "kharmas" key is
removed, for all 8 activities; (2) only marriage / grah_pravesh / naamkaran get
metadata, the other five get no new keys; (3) full vs partial Hindu-day overlap
is correct, including dates deep inside Kharmas; (4) failures can never
partially mutate a response.

No database, network, FCM or production access. Run: python test_kharmas_muhurat_awareness.py
"""

import copy
import io
import contextlib
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

import services.kharmas_awareness as ka  # noqa: E402
from services import kharmas_engine as ke  # noqa: E402
from services.muhurth_engine import next_best_dates_for_month  # noqa: E402
import routes.routes_panchang as rp  # noqa: E402

DELHI = (28.61, 77.23)
LKO = (26.8467, 80.9462)
NYC = (40.71, -74.0)
passed = failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def item(d, score=5):
    return {"date": d, "weekday": "X", "nakshatra": "Rohini", "tithi": "Panchami",
            "score": score, "reasons": ["Tithi Panchami allowed"], "language": "en"}


def strip(results):
    return [{k: v for k, v in x.items() if k != "kharmas"} for x in results]


app = Flask(__name__)
app.register_blueprint(rp.routes_panchang)
client = app.test_client()


def month(activity, m, y, lat, lon, lang="en"):
    return quiet(client.post, "/api/muhurth/month", json={"activity": activity, "month": m, "year": y,
                                                          "latitude": lat, "longitude": lon, "language": lang}).get_json()


print("\n[1] Route results == engine results (dates, order, scores, reasons, every field), all 8 activities")
ALL = ["marriage", "grah_pravesh", "naamkaran", "vehicle", "property", "gold", "travel", "childbirth"]
for act in ALL:
    for (m, y) in ((12, 2026), (1, 2027), (4, 2027), (6, 2027)):
        for lang in ("en", "hi"):
            r = month(act, m, y, *LKO, lang)
            eng = quiet(next_best_dates_for_month, act, LKO[0], LKO[1], m, y, language=lang, skipped=[])
            check(f"{act} {y}-{m:02d} {lang}: results identical to engine output after removing 'kharmas'",
                  strip(r["results"]) == eng, (len(r["results"]), len(eng)))
    if ka.awareness_level(act) is None:
        r = month(act, 12, 2026, *LKO)
        check(f"{act}: no new keys anywhere (top level and items)",
              "kharmas_awareness" not in r and all("kharmas" not in x for x in r["results"]))

print("\n[2] Hindu-day overlap at Kharmas boundaries (New Delhi) and deep inside")
# (civil date, expected overlap, expected boundary type) -- test data derived from the audited Drik comparison
EXPECT = [("2026-03-14", "partial", "starts"), ("2026-03-15", "full", None), ("2026-03-25", "full", None),
          ("2026-04-13", "full", None), ("2026-04-14", "partial", "ends"), ("2026-04-15", None, None),
          ("2026-12-15", None, None), ("2026-12-16", "partial", "starts"), ("2026-12-30", "full", None),
          ("2027-01-05", "full", None), ("2027-01-13", "full", None), ("2027-01-14", "partial", "ends"),
          ("2027-01-15", None, None), ("2027-03-14", None, None), ("2027-03-15", "partial", "starts"),
          ("2027-03-16", "full", None), ("2027-03-30", "full", None), ("2027-04-13", "full", None),
          ("2027-04-14", "partial", "ends"), ("2027-04-15", None, None)]
res = [item(d) for d, _, _ in EXPECT]
ann, aw = ka.annotate_muhurat_results("marriage", res, DELHI[0], DELHI[1], "en", date(2026, 3, 1), date(2027, 5, 1))
for (d, ov, bt), x in zip(EXPECT, ann):
    k = x.get("kharmas")
    got = (k["overlap"], k["boundary"]["type"] if k["boundary"] else None) if k else (None, None)
    check(f"{d}: {ov or 'none'}{'/' + bt if bt else ''}", got == (ov, bt), got)
check("dates deep inside Kharmas (2026-03-25, 2026-12-30, 2027-01-05, 2027-03-30) carry FULL metadata",
      all(x["kharmas"]["overlap"] == "full" and x["kharmas"]["day_window"]["basis"] == "sunrise_to_sunrise"
          for x in ann if x["date"] in ("2026-03-25", "2026-12-30", "2027-01-05", "2027-03-30")))
m14 = [x for x in ann if x["date"] == "2026-03-14"][0]["kharmas"]
check("Hindu day vs civil date are distinct: 14 Mar 2026's Hindu day contains the 15 Mar 01:03 ingress",
      m14["day_window"]["civil_date"] == "2026-03-14" and m14["boundary"]["ingress_civil_date"] == "2026-03-15"
      and m14["day_window"]["start"].startswith("2026-03-14T") and m14["day_window"]["end"].startswith("2026-03-15T")
      and "Hindu day of 14 Mar 2026" in m14["advisory"] and "15 Mar 2026, 1:03 AM" in m14["advisory"], m14)

print("\n[3] Levels, badge label, advisory wording")
p = [x for x in ann if x["date"] == "2026-12-30"][0]["kharmas"]
check("marriage: level badge, label 'Kharmas'", p["level"] == "badge" and p["badge"] == {"label": "Kharmas"})
g, _ = ka.annotate_muhurat_results("grah_pravesh", [item("2026-12-30")], *DELHI, "hi", date(2026, 12, 1), date(2027, 1, 1))
check("grah_pravesh (hi): badge label 'खरमास' and Hindi Griha Pravesh sentence",
      g[0]["kharmas"]["badge"] == {"label": "खरमास"} and "गृह प्रवेश" in g[0]["kharmas"]["advisory"])
n, naw = ka.annotate_muhurat_results("naamkaran", [item("2026-12-30")], *DELHI, "en", date(2026, 12, 1), date(2027, 1, 1))
check("naamkaran: level info, NO badge, informational sentence",
      n[0]["kharmas"]["level"] == "info" and "badge" not in n[0]["kharmas"] and naw["badge_label"] is None
      and "For information only" in n[0]["kharmas"]["advisory"])
texts, hi_texts, en_texts = [], [], []
for act in ("marriage", "grah_pravesh", "naamkaran"):
    for lang in ("en", "hi"):
        a, w = ka.annotate_muhurat_results(act, res, *DELHI, lang, date(2026, 3, 1), date(2027, 5, 1))
        batch = [x["kharmas"]["advisory"] for x in a if x.get("kharmas")] + [w["notice"]]
        texts += batch
        (hi_texts if lang == "hi" else en_texts).extend(batch)
check("no relative wording ('today', 'tomorrow', 'आज', 'कल') in any advisory or notice",
      not any(re.search(r"\btoday\b|\btomorrow\b|आज|कल ", t, re.I) for t in texts))
check("no claims about how many regions/communities observe it",
      not any(re.search(r"\b(many|most|several|majority|widely|millions)\b|कई|अधिकांश|ज़्यादातर|अधिकतर|लाखों", t, re.I) for t in texts))
check("every advisory names explicit dates and IST", all(re.search(r"\d{4}", t) and "IST" in t for t in texts))
check("Hindi advisories and notices are in Devanagari; English ones contain none",
      hi_texts and all(re.search(r"[ऀ-ॿ]", t) for t in hi_texts) and en_texts and not any(re.search(r"[ऀ-ॿ]", t) for t in en_texts),
      (len(hi_texts), len(en_texts)))

print("\n[4] IST calendar-day fallback is explicit")
ny, nyaw = ka.annotate_muhurat_results("marriage", [item("2026-12-30"), item("2026-12-16")], *NYC, "en",
                                       date(2026, 12, 1), date(2027, 1, 1))
check("out-of-region (New York): basis ist_calendar_day, window 00:00-24:00 IST, note in advisory",
      all(x["kharmas"]["day_window"]["basis"] == "ist_calendar_day" for x in ny)
      and ny[0]["kharmas"]["day_window"]["start"] == "2026-12-30T00:00:00+05:30"
      and ny[0]["kharmas"]["day_window"]["end"] == "2026-12-31T00:00:00+05:30"
      and "IST calendar day 30 Dec 2026" in ny[0]["kharmas"]["advisory"]
      and "not available for this location" in ny[0]["kharmas"]["advisory"] and nyaw["day_basis"] == "ist_calendar_day")
nyhi, _ = ka.annotate_muhurat_results("marriage", [item("2026-12-30")], *NYC, "hi", date(2026, 12, 1), date(2027, 1, 1))
check("Hindi fallback note", "IST कैलेंडर दिन" in nyhi[0]["kharmas"]["advisory"])
orig_sr = ka.calculate_sunrise_sunset
ka.calculate_sunrise_sunset = lambda *a, **k: (None, None)
try:
    fb, _ = ka.annotate_muhurat_results("marriage", [item("2026-12-30")], *DELHI, "en", date(2026, 12, 1), date(2027, 1, 1))
finally:
    ka.calculate_sunrise_sunset = orig_sr
check("in-region but sunrise unavailable -> per-item ist_calendar_day fallback",
      fb[0]["kharmas"]["day_window"]["basis"] == "ist_calendar_day")

print("\n[5] No mutation, failure isolation")
src = [item("2026-12-30"), item("2026-12-16"), item("2026-12-03")]
snap = copy.deepcopy(src)
out, _ = ka.annotate_muhurat_results("marriage", src, *DELHI, "en", date(2026, 12, 1), date(2027, 1, 1))
check("annotator never mutates its input", src == snap and out is not src and all(o is not s for o, s in zip(out, src)))
check("order preserved and existing fields identical", strip(out) == snap)
calls = {"n": 0}


def flaky(*a, **k):
    calls["n"] += 1
    if calls["n"] == 3:
        raise RuntimeError("injected failure mid-annotation")
    return orig_sr(*a, **k)


resp = {"activity": "marriage", "month": 12, "year": 2026, "language": "en", "results": copy.deepcopy(src), "skipped_dates": []}
resp_snap = copy.deepcopy(resp)
ka.calculate_sunrise_sunset = flaky
try:
    got = quiet(rp._with_kharmas_awareness, resp, "marriage", *DELHI, "en", date(2026, 12, 1), date(2027, 1, 1))
finally:
    ka.calculate_sunrise_sunset = orig_sr
check("failure after partial work -> the ORIGINAL response object, unmodified, no awareness keys",
      calls["n"] >= 3 and got is resp and resp == resp_snap and all("kharmas" not in x for x in resp["results"]))
orig_int = ka.get_kharmas_intervals
ka.get_kharmas_intervals = lambda *a: (_ for _ in ()).throw(RuntimeError("engine down"))
try:
    got2 = quiet(rp._with_kharmas_awareness, resp, "marriage", *DELHI, "en", date(2026, 12, 1), date(2027, 1, 1))
finally:
    ka.get_kharmas_intervals = orig_int
check("Kharmas engine failure -> original response unchanged", got2 is resp and resp == resp_snap)
check("non-awareness activity -> same object returned", rp._with_kharmas_awareness(resp, "vehicle", *DELHI, "en", date(2026, 12, 1), date(2027, 1, 1)) is resp)
bad = {"activity": "marriage", "results": [{"date": "not-a-date", "score": 5}]}
bad_snap = copy.deepcopy(bad)
check("malformed result item -> original response unchanged",
      quiet(rp._with_kharmas_awareness, bad, "marriage", *DELHI, "en", date(2026, 12, 1), date(2027, 1, 1)) is bad and bad == bad_snap)

print("\n[6] Top-level awareness block and API wiring")
r = month("marriage", 12, 2026, *LKO)
aw = r["kharmas_awareness"]
check("month API: block present with the overlapping period and an explicit notice",
      aw["level"] == "badge" and aw["badge_label"] == "Kharmas" and [p["id"] for p in aw["periods"]] == ["dhanu-2026"]
      and aw["window"] == {"start": "2026-12-01", "end_exclusive": "2027-01-01"} and "16 Dec 2026, 10:25 AM" in aw["notice"])
r = month("marriage", 6, 2027, *LKO)
check("month without Kharmas: block present, periods [], notice null, no item metadata",
      r["kharmas_awareness"]["periods"] == [] and r["kharmas_awareness"]["notice"] is None
      and all("kharmas" not in x for x in r["results"]))
lst = quiet(client.post, "/api/muhurth/list", json={"activity": "grah_pravesh", "latitude": LKO[0], "longitude": LKO[1], "days": 60}).get_json()
check("list API: awareness block with window = today .. today+60",
      "kharmas_awareness" in lst and lst["kharmas_awareness"]["window"]["start"] == datetime.now().date().isoformat())
lv = quiet(client.post, "/api/muhurth/list", json={"activity": "vehicle", "latitude": LKO[0], "longitude": LKO[1], "days": 60}).get_json()
check("list API: vehicle has no awareness keys", "kharmas_awareness" not in lv and all("kharmas" not in x for x in lv["results"]))
check("activity alias 'grah-pravesh' maps to the same policy", ka.awareness_level("grah-pravesh") == "badge")

print("\n[7] Interval helper")
iv = ke.get_kharmas_intervals(datetime(2026, 12, 1), datetime(2027, 5, 1))
check("get_kharmas_intervals: dhanu-2026 and meena-2027 in order, exact datetimes",
      [p["id"] for p in iv] == ["dhanu-2026", "meena-2027"] and iv[0]["start"].tzinfo is not None)
check("interval helper matches the public period API",
      ke.get_kharmas_periods(2026, at=datetime(2026, 6, 1))[1]["start"]["ingress"] == iv[0]["start"].isoformat(timespec="seconds"))

print("\n[8] Overhead of the annotation step")
ke.clear_caches()
big = [item(f"2026-12-{d:02d}") for d in range(1, 32)]
t = time.perf_counter(); ka.annotate_muhurat_results("marriage", big, *LKO, "en", date(2026, 12, 1), date(2027, 1, 1)); cold = (time.perf_counter() - t) * 1000
warm = []
for _ in range(20):
    t = time.perf_counter(); ka.annotate_muhurat_results("marriage", big, *LKO, "en", date(2026, 12, 1), date(2027, 1, 1)); warm.append((time.perf_counter() - t) * 1000)
warm.sort()
print(f"  info: annotate 31 items (16 overlapping) cold {cold:.1f} ms, warm median {warm[10]:.1f} ms, max {warm[-1]:.1f} ms")
check("warm annotation of a full month < 100 ms", warm[10] < 100, warm[10])

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
