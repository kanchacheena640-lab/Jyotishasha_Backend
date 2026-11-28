"""Pradosh notification migration tests (standalone check() convention).

No database, FCM or network: the scheduler's own functions (event_master,
festival_adapter, notification_builder, event_resolver) are exercised
directly; /api/events/home-upcoming runs on a minimal Flask app with a
pinned clock; the migration planner runs on synthetic rows.

Run:  python test_pradosh_notifications.py
"""
import os
import sys
from datetime import date, datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

from services.events_engine import find_next_pradosh, get_pradosh_details  # noqa: E402
from services.panchang_engine import calculate_panchang  # noqa: E402
from services.event_master import generate_events_for_date  # noqa: E402
from services.event_adapters.festival_adapter import normalize_event  # noqa: E402
from services.notification_builder import build_event_content  # noqa: E402
from services.event_resolver import resolve_resource  # noqa: E402
import routes.routes_events as routes_module  # noqa: E402
from routes.routes_events import routes_events  # noqa: E402
from scripts.migrate_pradosh_events import plan  # noqa: E402

LKO = (26.8467, 80.9462)   # scheduler location (event_scheduler DEFAULT_LAT/LON)
passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


class FakeEvent:
    def __init__(self, **kw):
        self.__dict__.update(kw)


print("\n[1] find_next_pradosh now uses the documented engine (legacy shape kept)")
a = find_next_pradosh(date(2026, 11, 28), *LKO)
b = find_next_pradosh(date(2026, 12, 7), *LKO)
check("28 Nov -> 6 Dec 2026, legacy name 'Krishna Pradosh Vrat', slug, meta for the live page",
      a["date"] == "2026-12-06" and a["name_en"] == "Krishna Pradosh Vrat" and a["slug"] == "pradosh-vrat"
      and a["meta"] == {"type": "pradosh", "slug": "pradosh-vrat"} and a["type"] == "pradosh", a)
check("7 Dec -> 21 Dec 2026 Soma Pradosh (missed by the old detector), legacy name 'Shukla Pradosh Vrat'",
      b["date"] == "2026-12-21" and b["name_en"] == "Shukla Pradosh Vrat" and b["vrat_name_en"] == "Soma Pradosh Vrat"
      and b["puja_muhurat"]["start"].startswith("2026-12-21T17:"), b)
check("legacy keys present", {"type", "name_en", "name_hi", "slug", "date", "paksha", "sunset_time", "tithi_at_sunset"} <= set(b))
check("days_ahead still bounds the search", find_next_pradosh(date(2026, 11, 28), *LKO, days_ahead=5) is None)
check("strictly after start_date (a Pradosh day returns the following one)", find_next_pradosh(date(2026, 12, 21), *LKO)["date"] == "2027-01-05")
check("unsupported coordinates -> None (no IST-model guess)", find_next_pradosh(date(2026, 11, 28), 40.71, -74.0) is None)
check("datetime input accepted", find_next_pradosh(datetime(2026, 12, 7, 9, 0), *LKO)["date"] == "2026-12-21")

print("\n[2] De-duplication key stability vs rows the OLD detector already stored")
old_rows, d = {}, date(2026, 11, 28)
while d <= date(2027, 1, 12):
    r = get_pradosh_details(calculate_panchang(d, *LKO, "en"))
    if r:
        old_rows[r["date"]] = r["name_en"]
    d = date.fromordinal(d.toordinal() + 1)
new_rows, d = {}, date(2026, 11, 27)
while d < date(2027, 1, 12):
    r = find_next_pradosh(d, *LKO)
    if r and r["date"] <= "2027-01-12":
        new_rows[r["date"]] = r["name_en"]
    d = date.fromordinal(d.toordinal() + 1)
check("every old stored row in the current window is reproduced with the SAME name and date (no duplicate)",
      all(new_rows.get(k) == v for k, v in old_rows.items()), (old_rows, new_rows))
check("the only addition in the window is 21 Dec 2026 Shukla Pradosh",
      sorted(set(new_rows) - set(old_rows)) == ["2026-12-21"] and new_rows["2026-12-21"] == "Shukla Pradosh Vrat", sorted(new_rows))

print("\n[3] 21 Dec 2026 notification eligibility (scheduler path)")
# run_daily_event_job: evening slot on D targets D+1 and generates/saves for [D+1, D+2]; morning slot on D
# targets D and generates/saves for [D, D+1]; it then notifies the stored events dated in its window.
created = set()
d = date(2026, 12, 7)
while d <= date(2026, 12, 20):          # every daily run from 7 Dec (after the 6 Dec Pradosh) to 20 Dec morning
    for g in (d, date.fromordinal(d.toordinal() + 1)):
        created |= {e["date"] for e in generate_events_for_date(g, *LKO) if e.get("type") == "pradosh"}
    d = date.fromordinal(d.toordinal() + 1)
check("the 21 Dec 2026 row is created by the daily runs before 20 Dec (old detector never created it)", "2026-12-21" in created, sorted(created))
check("20 Dec evening run (window 21-22 Dec) and 21 Dec morning run (window 21-22 Dec) both include 21 Dec",
      all("2026-12-21" in {date.fromordinal(t.toordinal() + i).isoformat() for i in (0, 1)} for t in (date(2026, 12, 21),)))
gen = [normalize_event(e) for e in generate_events_for_date(date(2026, 12, 20), *LKO) if e.get("type") == "pradosh"][0]
check("normalized row: type vrat, legacy name, meta kept (resource link)", gen["type"] == "vrat" and gen["name"] == "Shukla Pradosh Vrat"
      and gen["date"] == "2026-12-21" and gen["meta"] == {"type": "pradosh", "slug": "pradosh-vrat"}, gen)
content = build_event_content(FakeEvent(type="vrat", name=gen["name"], id=101, date=date(2026, 12, 21)))
check("push content links the live Pradosh page with Pradosh wording", content and "jyotishasha.com/panchang/pradosh" in content["body"]
      and "Pradosh Kaal aur Puja Muhurat jaane" in content["body"] and "Paran" not in content["body"], content and content["body"])
ek = build_event_content(FakeEvent(type="vrat", name="Utpanna Ekadashi", id=102, date=date(2026, 12, 4)))
check("Ekadashi push content unchanged (Paran wording, Ekadashi link)", "Vrat vidhi, mahatva aur Paran time jaane" in ek["body"] and "jyotishasha.com/ekadashi" in ek["body"])
res = resolve_resource(FakeEvent(meta=gen["meta"]))
res_hi = resolve_resource(FakeEvent(meta=gen["meta"]), lang="hi")
check("notification tap resource -> live page (EN/HI)", res["url"] == "https://www.jyotishasha.com/panchang/pradosh" and res_hi["url"] == "https://www.jyotishasha.com/hi/panchang/pradosh")

print("\n[4] /api/events/home-upcoming (pinned clock)")
real_dt = routes_module.datetime


class _Clock(real_dt):
    @classmethod
    def now(cls, tz=None):
        return real_dt(2026, 12, 7, 12, 0)


routes_module.datetime = _Clock
try:
    app = Flask(__name__)
    app.register_blueprint(routes_events, url_prefix="/api/events")
    j = app.test_client().post("/api/events/home-upcoming", json={"latitude": 28.6139, "longitude": 77.209}).get_json()
finally:
    routes_module.datetime = real_dt
pr = [e for e in j["events"] if "Pradosh" in e["name"]]
check("home-upcoming on 7 Dec lists 21 Dec 2026 'Shukla Pradosh Vrat' (legacy name, slug unchanged)",
      pr and pr[0]["date"] == "2026-12-21" and pr[0]["name"] == "Shukla Pradosh Vrat" and pr[0]["slug"] == "/pradosh-vrat", j)

print("\n[5] Migration planner (synthetic rows, no database)")
rows = [
    (1, "Krishna Pradosh Vrat", "2026-11-29", {}),                       # tomorrow -> protected
    (2, "Krishna Pradosh Vrat", "2026-12-06", {}),                       # correct, no meta -> add meta
    (3, "Shukla Pradosh Vrat", "2027-10-13", {}),                        # old-detector date (new: 12 Oct) -> stale
    (4, "Krishna Pradosh Vrat", "2027-01-05", {"type": "pradosh", "slug": "pradosh-vrat"}),   # correct + meta -> untouched
]
p = plan(rows, date(2026, 11, 28))
check("plan: stale=[3], add_meta=[2], tomorrow protected, correct row untouched",
      [r[0] for r in p["stale"]] == [3] and [r[0] for r in p["add_meta"]] == [2] and p["protected"] == 1, p)
check("plan reports dates the scheduler will create (21 Dec 2026 included)", ("Shukla Pradosh Vrat", "2026-12-21") in p["missing"])

print(f"\nTOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
