"""One-time Pradosh AstroEvent migration (DRY RUN by default).

Context: the scheduler (event_master -> events_engine.find_next_pradosh) now
uses services/pradosh_engine.py. Rows saved by the OLD detector can sit on a
wrong date. Rows are de-duplicated by (name, date, type), so a stale row is
never replaced -- it would still be notified.

What this does, for FUTURE Pradosh rows only (date > IST tomorrow, so no
notification for them can already have been created by the scheduler, which
only reads today/tomorrow):
  * STALE    -- name/date not produced by the new engine at the scheduler's
                location  -> listed; deleted only with --apply
  * NO META  -- correct rows without meta {type, slug} -> listed; meta added
                only with --apply (lets notifications link to /panchang/pradosh)
Past/today/tomorrow rows are never touched.

Usage (review the dry run before any --apply; needs CTO approval for prod):
  python scripts/migrate_pradosh_events.py                 # dry run, prints plan
  python scripts/migrate_pradosh_events.py --apply --yes   # writes
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCHEDULER_LAT, SCHEDULER_LON = 26.8467, 80.9462      # services/event_scheduler.py DEFAULT_LAT/LON
PRADOSH_NAMES = ("Shukla Pradosh Vrat", "Krishna Pradosh Vrat")
META = {"type": "pradosh", "slug": "pradosh-vrat"}


def expected_rows(first, last):
    """{(name, date)} the new engine produces at the scheduler location in [first, last]."""
    from services.pradosh_engine import get_pradosh_calendar
    out = set()
    for y in range(first.year, last.year + 1):
        for r in get_pradosh_calendar(y, SCHEDULER_LAT, SCHEDULER_LON):
            if r["date"] and first.isoformat() <= r["date"] <= last.isoformat():
                out.add((f"{r['paksha']['en']} Pradosh Vrat", r["date"]))
    return out


def plan(rows, today):
    """Pure planning step (unit-testable): rows = [(id, name, date_iso, meta)]."""
    protect_until = today + timedelta(days=1)
    future = [r for r in rows if date.fromisoformat(r[2]) > protect_until]
    if not future:
        return {"stale": [], "add_meta": [], "missing": [], "protected": len(rows)}
    last = max(date.fromisoformat(r[2]) for r in future)
    want = expected_rows(protect_until + timedelta(days=1), last)
    stale = [r for r in future if (r[1], r[2]) not in want]
    add_meta = [r for r in future if (r[1], r[2]) in want and not ((r[3] or {}).get("type") and (r[3] or {}).get("slug"))]
    have = {(r[1], r[2]) for r in future}
    missing = sorted(w for w in want if w not in have)      # informational: the scheduler creates these itself
    return {"stale": stale, "add_meta": add_meta, "missing": missing, "protected": len(rows) - len(future)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true", help="required with --apply")
    args = ap.parse_args()
    if args.apply and not args.yes:
        sys.exit("--apply requires --yes")

    from factory import create_app
    from extensions import db
    from models import AstroEvent

    app = create_app()
    with app.app_context():
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
        q = AstroEvent.query.filter(AstroEvent.type == "vrat", AstroEvent.name.in_(PRADOSH_NAMES), AstroEvent.date >= today)
        rows = [(e.id, e.name, e.date.isoformat(), e.meta) for e in q.order_by(AstroEvent.date).all()]
        p = plan(rows, today)
        print(f"IST today {today}; Pradosh rows from today: {len(rows)} (protected today/tomorrow: {p['protected']})")
        print("STALE (delete):", [(r[0], r[1], r[2]) for r in p["stale"]])
        print("ADD META:", [(r[0], r[1], r[2]) for r in p["add_meta"]])
        print("NOT YET STORED (scheduler will create):", p["missing"])
        if not args.apply:
            print("DRY RUN -- nothing written.")
            return
        for r in p["stale"]:
            db.session.delete(AstroEvent.query.get(r[0]))
        for r in p["add_meta"]:
            e = AstroEvent.query.get(r[0])
            e.meta = {**(e.meta or {}), **META}
        db.session.commit()
        print(f"APPLIED: deleted {len(p['stale'])}, meta added to {len(p['add_meta'])}.")


if __name__ == "__main__":
    main()
