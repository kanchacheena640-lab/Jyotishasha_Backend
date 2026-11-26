# test_notification_personalization_precompute.py

"""
Local-only regression for the notification-cron scan elimination
(services/notification_builder.py::build_personalization_context()).

Same convention as test_transit_personalization.py: connects ONLY to the
local scratch Postgres DB (jyotishasha_local), asserts that identity before
touching anything, and cleans up its own rows. No FCM send (the builder
only builds content).

Proves:
1. Parity -- for every fixture user, in both slots, get_user_notifications()
   returns exactly the same list with the run-level context as without it
   (the original per-user path).
2. The full-table selections run ONCE per run, not once per user.
3. Per-part fallback -- a part that fails during precompute falls back to
   the original per-user call, still producing identical output.
4. The new parameter is keyword-only (positional third argument still
   rejected, exactly as before).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from models import AstroEvent  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
import services.notification_builder as nb  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
BASE = 9700
N = 24
NAME = "PRECOMPUTE-TEST-%"

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


def cleanup():
    ids = {"lo": BASE, "hi": BASE + N}
    db.session.execute(text("DELETE FROM user_dasha_timeline WHERE user_id >= :lo AND user_id < :hi"), ids)
    db.session.execute(text("DELETE FROM app_users WHERE id >= :lo AND id < :hi"), ids)
    db.session.execute(text("DELETE FROM astro_events WHERE name LIKE :n"), {"n": NAME})
    db.session.commit()


def seed(today):
    rashis = ["aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
              "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
    for i in range(N):
        uid = BASE + i
        db.session.execute(text(
            "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token, lagna, lang) "
            "VALUES (:id, '+05:30', 'free', 0, :t, :l, :g)"),
            {"id": uid, "t": f"fake-{uid}", "l": None if i % 7 == 6 else rashis[i % 12],
             "g": "hi" if i % 2 else "en"})
        rows = []
        if i % 3 == 0:
            rows.append(("Jupiter", "Saturn", today + timedelta(days=5)))
        if i % 4 == 0:
            rows.append(("Venus", "Moon", today))
            rows.append(("Venus", "Mars", today))
        for m, a, s in rows:
            db.session.execute(text(
                "INSERT INTO user_dasha_timeline (user_id, mahadasha, antardasha, start_date, end_date) "
                "VALUES (:u, :m, :a, :s, :e)"),
                {"u": uid, "m": m, "a": a, "s": s, "e": s + timedelta(days=90)})

    def ev(name, d, typ, meta=None):
        e = AstroEvent(name=f"PRECOMPUTE-TEST {name}", date=d, type=typ, meta=meta)
        db.session.add(e)
        return e

    events = [
        ev("transit Jupiter", today + timedelta(days=1), "transit", {"planet": "Jupiter", "rashi": "capricorn"}),
        ev("transit Moon", today + timedelta(days=1), "transit", {"planet": "Moon", "rashi": "leo"}),
        ev("transit Mars today", today, "transit", {"planet": "Mars", "rashi": "aries"}),
        ev("transit no meta", today + timedelta(days=1), "transit", None),
        ev("panchak today", today, "panchak"),
        ev("panchak tomorrow", today + timedelta(days=1), "panchak"),
        ev("vrat today", today, "vrat"),
        ev("vrat tomorrow", today + timedelta(days=1), "vrat"),
        ev("panchang today", today, "panchang", {"tithi": "Ekadashi"}),
    ]
    db.session.commit()
    return events


def all_users():
    return db.session.query(AppUser).filter(AppUser.id >= BASE, AppUser.id < BASE + N).order_by(AppUser.id).all()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()
        today = datetime.now(IST).date()
        events = seed(today)
        users = all_users()

        try:
            for slot in ("morning", "evening"):
                os.environ["NOTIFICATION_SLOT"] = slot

                print(f"\n=== 1. Parity, slot={slot} ===")
                ctx = nb.build_personalization_context(events)
                mismatches = [u.id for u in users
                              if nb.get_user_notifications(u, events) != nb.get_user_notifications(u, events, context=ctx)]
                non_empty = sum(1 for u in users if nb.get_user_notifications(u, events, context=ctx))
                check(f"all {len(users)} users identical with/without context ({non_empty} non-empty)", not mismatches)
                if mismatches:
                    print("    mismatching user ids:", mismatches[:10])

            print("\n=== 2. Full-table selections run once per run ===")
            os.environ["NOTIFICATION_SLOT"] = "evening"
            calls = {"transit": 0, "dasha": 0}
            real_t, real_d = nb.get_users_for_transit, nb.get_users_for_dasha_change

            def count_t(event):
                calls["transit"] += 1
                return real_t(event)

            def count_d(*a, **k):
                calls["dasha"] += 1
                return real_d(*a, **k)

            nb.get_users_for_transit, nb.get_users_for_dasha_change = count_t, count_d
            try:
                ctx = nb.build_personalization_context(events)
                for u in users:
                    nb.get_user_notifications(u, events, context=ctx)
                n_transit = sum(1 for e in events if e.type == "transit")
                check(f"transit selection called {calls['transit']}x == transit events ({n_transit}), not x{len(users)} users",
                      calls["transit"] == n_transit)
                check(f"dasha selection called {calls['dasha']}x == 2", calls["dasha"] == 2)

                print("\n=== 3. Per-part fallback when precompute fails ===")

                def boom(*a, **k):
                    raise RuntimeError("simulated precompute failure")

                nb.get_users_for_transit, nb.get_users_for_dasha_change = boom, boom
                broken_ctx = nb.build_personalization_context(events)
                check("failed transit parts are left out of the context", broken_ctx["transit"] == {})
                check("failed dasha parts are None", broken_ctx["dasha_pre"] is None and broken_ctx["dasha_today"] is None)
                nb.get_users_for_transit, nb.get_users_for_dasha_change = real_t, real_d
                mismatches = [u.id for u in users
                              if nb.get_user_notifications(u, events) != nb.get_user_notifications(u, events, context=broken_ctx)]
                check("fallback output identical to original per-user path", not mismatches)
            finally:
                nb.get_users_for_transit, nb.get_users_for_dasha_change = real_t, real_d

            print("\n=== 4. context is keyword-only ===")
            try:
                nb.get_user_notifications(users[0], events, {})
                check("positional third argument rejected", False)
            except TypeError:
                check("positional third argument rejected", True)
        finally:
            cleanup()

    print(f"\nRESULT: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
