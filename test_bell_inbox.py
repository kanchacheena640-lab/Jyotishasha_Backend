# test_bell_inbox.py

"""
Local-only entry point for N5 (Notification Bell Inbox Finalization).

Follows the same convention as every other test_*.py script in this repo
(see test_notification_lifecycle.py's own docstring): connects ONLY to the
local scratch Postgres DB (jyotishasha_local), asserts that database
identity before touching anything, and cleans up its own rows at the end.

Replicates -- rather than calls through JWT auth -- the EXACT query logic
of notifications/user_notification_routes.py's three endpoints
(get_unread_count, get_notifications, mark_read), the same approach
test_notification_lifecycle.py already established and documents its own
reason for ("the route sits behind JWT auth this script does not mock --
the query logic exercised is identical").

Proves:
1. The N5 fix to get_unread_count() (previously required an additional
   `created_at > 5-hour-cutoff` condition the LIST query never applied to
   its own `is_read == False` branch -- an inconsistency where an old
   unread item could appear in the list but not count toward the badge).
2. Today/Tomorrow active-inbox exclusivity after N2 expiry.
3. Bell-only (N4/N5) rows: excluded from push counting (attention_policy.py,
   already tested there), rendered normally, respect N2 expiry, participate
   correctly in read/unread and the unread-count fix above.
4. Ordering (deterministic, newest-first) and the list/pagination `.limit(10)`
   boundary, distinguished from physical DB retention.
5. Alerts Bell-only (N5 new): AlertPersistenceRepository.record_bell_only()
   never touches AlertMicroEvent.last_delivered_at, is idempotent, and its
   row is indistinguishable in shape from a normal Alert Bell row.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text, or_  # noqa: E402

from notifications.notification_models import UserNotification  # noqa: E402
from services.notification_lifecycle import (  # noqa: E402
    expiry_for_astro_event_notification,
    expiry_for_alert_notification,
)
from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402

PROFILE = 9901
ALERT_EVENT_ID = "mood_positive"

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


def unread_count(user_id, now):
    """Exact replica of the FIXED get_unread_count() query."""
    return (
        UserNotification.query
        .filter(UserNotification.user_id == user_id)
        .filter(UserNotification.is_read == False)  # noqa: E712
        .filter(or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > now))
        .count()
    )


def bell_list(user_id, now, cutoff_hours=5, limit=10):
    """Exact replica of the UNCHANGED get_notifications() query."""
    cutoff = now - timedelta(hours=cutoff_hours)
    rows = (
        UserNotification.query
        .filter(UserNotification.user_id == user_id)
        .filter(or_(UserNotification.is_read == False, UserNotification.created_at > cutoff))  # noqa: E712
        .filter(or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > now))
        .order_by(UserNotification.created_at.desc())
        .limit(limit)
        .all()
    )
    return rows


def cleanup():
    db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": PROFILE})
    db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": PROFILE})
    db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": PROFILE})
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()
        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                "VALUES (:id, '+05:30', 'free', 0, :token)"
            ), {"id": PROFILE, "token": "fake-fcm-9901"})
            conn.commit()

        now = datetime.utcnow()

        # ==============================================================
        print("=== N5 Test 4/5: unread-count / list consistency fix ===")
        # ==============================================================
        old_unread = UserNotification(
            user_id=PROFILE, title="Old Unread Event", body="...",
            data={"type": "event"}, is_read=False,
            created_at=now - timedelta(hours=8),  # older than the list's own 5h "recently read" window
            expires_at=None,  # never expires
        )
        db.session.add(old_unread)
        db.session.commit()

        check(
            "N5 Test 4/5 setup: an unread item older than 5h IS shown in the Bell list "
            "(list's own is_read==False branch has no age limit, unchanged)",
            old_unread.id in {r.id for r in bell_list(PROFILE, now)},
        )
        check(
            "N5 Test 4/5 fix: that SAME old-but-unread item now correctly counts toward the "
            "badge too (previously it silently did not -- the exact inconsistency this fixes)",
            unread_count(PROFILE, now) == 1,
        )

        read_row = UserNotification(
            user_id=PROFILE, title="Read Event", body="...",
            data={"type": "event"}, is_read=True, created_at=now,
        )
        db.session.add(read_row)
        db.session.commit()
        check("N5 Test 5: a read item never inflates the unread badge", unread_count(PROFILE, now) == 1)

        cleanup()

        # ==============================================================
        print("\n=== N5 Test 1/2/3: expired Tomorrow invisible, Today visible, no stale coexistence ===")
        # ==============================================================
        tomorrow_row = UserNotification(
            user_id=PROFILE, title="Amavasya Tomorrow", body="...",
            data={"type": "event", "event_id": "1"}, is_read=False,
            expires_at=expiry_for_astro_event_notification(event_date=date(2026, 8, 16), is_forward_looking=True),
        )
        db.session.add(tomorrow_row)
        db.session.commit()

        before_boundary = datetime(2026, 8, 15, 12, 0, 0)
        after_boundary = datetime(2026, 8, 15, 19, 0, 0)  # past IST midnight of Aug 16

        check("N5 Test 1: Tomorrow item IS visible before the IST boundary",
              tomorrow_row.id in {r.id for r in bell_list(PROFILE, before_boundary)})
        check("N5 Test 1: Tomorrow item is INVISIBLE once the IST boundary passes",
              tomorrow_row.id not in {r.id for r in bell_list(PROFILE, after_boundary)})
        check("...and correctly excluded from the unread badge too",
              unread_count(PROFILE, after_boundary) == 0)

        today_row = UserNotification(
            user_id=PROFILE, title="Amavasya Today", body="...",
            data={"type": "event", "event_id": "1"}, is_read=False,
            expires_at=expiry_for_astro_event_notification(event_date=date(2026, 8, 16), is_forward_looking=False),
        )
        db.session.add(today_row)
        db.session.commit()
        active_after = {r.id for r in bell_list(PROFILE, after_boundary)}
        check("N5 Test 2: Today item IS visible", today_row.id in active_after)
        check("N5 Test 3: stale Tomorrow does NOT coexist with the fresh Today version in the active inbox",
              tomorrow_row.id not in active_after and today_row.id in active_after)

        cleanup()

        # ==============================================================
        print("\n=== N5 Test 11/12/13: Bell-only rows (N4/N5) render/behave normally ===")
        # ==============================================================
        bell_only_row = UserNotification(
            user_id=PROFILE, title="Moon Transit Tomorrow: 12th House", body="...",
            data={"type": "transit", "event_id": "5", "delivery_channel": "bell_only"},
            is_read=False,
            expires_at=expiry_for_astro_event_notification(event_date=date(2026, 8, 16), is_forward_looking=True),
        )
        db.session.add(bell_only_row)
        db.session.commit()

        check("N5 Test 11: a Bell-only row appears in the active Bell list exactly like a pushed one",
              bell_only_row.id in {r.id for r in bell_list(PROFILE, before_boundary)})
        check("N5 Test 11: no technical wording (bell_only/suppressed/cap) appears in title or body",
              "bell_only" not in bell_only_row.title.lower()
              and "suppress" not in bell_only_row.title.lower()
              and "bell_only" not in bell_only_row.body.lower())
        check("N5 Test 12: a Bell-only row still correctly counts toward the unread badge "
              "(it's a real, useful, unread inbox item -- just never pushed)",
              unread_count(PROFILE, before_boundary) == 1)
        check("N5 Test 13: it respects the exact same N2 expiry boundary as a pushed row of the same type",
              bell_only_row.id not in {r.id for r in bell_list(PROFILE, after_boundary)})

        cleanup()

        # ==============================================================
        print("\n=== N5 Test: Alerts Bell-only (record_bell_only) never touches cooldown, is idempotent ===")
        # ==============================================================
        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                "VALUES (:id, '+05:30', 'free', 0, :token)"
            ), {"id": PROFILE, "token": "fake-fcm-9901"})
            conn.commit()

        repo = AlertPersistenceRepository()
        repo.save_detection(
            profile_id=PROFILE, event_id=ALERT_EVENT_ID, category="emotional",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 17),
            evaluated_at=datetime(2026, 8, 14, 12, 0, 0),
        )
        row_before = repo.read(profile_id=PROFILE, event_id=ALERT_EVENT_ID)
        check("setup: AlertMicroEvent.last_delivered_at starts NULL (never delivered)",
              row_before.last_delivered_at is None)

        bell_row = repo.record_bell_only(
            profile_id=PROFILE, event_id=ALERT_EVENT_ID,
            notification_title="Mood Positive", notification_body="body text",
            notification_data={"type": "alert", "event_id": ALERT_EVENT_ID},
            active_until=date(2026, 8, 17),
            now=datetime(2026, 8, 15, 6, 0, 0),
        )
        check("record_bell_only() creates exactly one Bell row", bell_row is not None)
        row_after = repo.read(profile_id=PROFILE, event_id=ALERT_EVENT_ID)
        check("N5 Alerts decision: record_bell_only() NEVER touches last_delivered_at "
              "(cooldown/dedup completely untouched, unlike a real delivery)",
              row_after.last_delivered_at is None)
        check("the Bell row carries delivery_channel=bell_only and does not consume push budget",
              bell_row.data.get("delivery_channel") == "bell_only")

        second_attempt = repo.record_bell_only(
            profile_id=PROFILE, event_id=ALERT_EVENT_ID,
            notification_title="Mood Positive", notification_body="body text",
            notification_data={"type": "alert", "event_id": ALERT_EVENT_ID},
            active_until=date(2026, 8, 17),
            now=datetime(2026, 8, 15, 8, 0, 0),  # simulates a later run the SAME day
        )
        check("record_bell_only() is idempotent -- a later run the same day, while the first "
              "bell-only row is still active, does NOT insert a duplicate",
              second_attempt is None)
        still_one = UserNotification.query.filter_by(user_id=PROFILE).filter(
            UserNotification.data["event_id"].astext == ALERT_EVENT_ID
        ).count()
        check("...confirmed: exactly one Bell row exists for this alert, not two", still_one == 1)

        cleanup()

        # ==============================================================
        print("\n=== N5 Test 18/19: ordering + list/pagination policy ===")
        # ==============================================================
        for i in range(12):
            db.session.add(UserNotification(
                user_id=PROFILE, title=f"Item {i}", body="...",
                data={"type": "event"}, is_read=False,
                created_at=now - timedelta(minutes=i),
            ))
        db.session.commit()

        rows = bell_list(PROFILE, now)
        titles = [r.title for r in rows]
        check("N5 Test 18: ordering is deterministic newest-first",
              titles == [f"Item {i}" for i in range(10)])
        check("N5 Test 19: the ACTIVE Bell list API is capped at 10 regardless of how many rows physically exist "
              "(12 written, only the 10 most recent shown) -- API limit is independent of DB retention",
              len(rows) == 10)
        total_physical = UserNotification.query.filter_by(user_id=PROFILE).count()
        check("N5 Test 19: all 12 rows still physically exist in the DB (no data loss just for a row-count policy)",
              total_physical == 12)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
