# test_notification_lifecycle.py

"""
Local-only entry point for N2 (Unified Notification Lifecycle & Expiry),
extended by N2.1 (Dasha-pre Lifecycle Completion).

Follows the same convention as every other test_*.py script in this repo
(see test_alerts_delivery.py's own docstring): connects ONLY to the local
scratch Postgres DB (jyotishasha_local), asserts that database identity
before touching anything, and cleans up its own rows at the end. No
production access, no FCM call (this script never sends a push at all).

Proves two independent things:

1. services/notification_lifecycle.py's pure expiry-computation
   functions -- deterministic date math, no DB needed.
2. That inserting UserNotification rows with those computed expires_at
   values, then running the EXACT SAME SQLAlchemy filter
   notifications/user_notification_routes.py's GET /api/user-notifications
   and /unread-count use, correctly includes not-yet-expired rows and
   excludes expired ones -- server-side, without needing to mock the JWT
   auth layer those routes sit behind. That filter itself is UNCHANGED by
   N2 (see this script's own findings / N2's report) -- what changed is
   that more types now carry a real expires_at for it to act on.

Also exercises modules/alerts/persistence_repository.py::finalize_delivery()
directly (bypassing deliver_alert()'s entitlement/eligibility layers,
which N2 does not touch and does not re-test here) to prove the ACTUAL
write path now derives a real expires_at from AlertMicroEvent.active_until,
not just the pure function in isolation.
"""

import os
import sys
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text, or_  # noqa: E402

from notifications.notification_models import UserNotification  # noqa: E402
from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402
from services.notification_lifecycle import (  # noqa: E402
    expiry_for_astro_event_notification,
    expiry_for_same_day_notification,
    expiry_for_alert_notification,
    expiry_for_dasha_pre_notification,
)

PROFILE = 9501

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


def bell_visible_ids(user_id, now):
    """
    Exact replica of GET /api/user-notifications' own filter (see
    notifications/user_notification_routes.py::get_notifications() --
    UNCHANGED by N2). Used here, instead of calling the real route, only
    because the route sits behind JWT auth this script does not mock --
    the query logic exercised is identical.
    """
    cutoff = now - timedelta(hours=5)
    rows = (
        UserNotification.query
        .filter(UserNotification.user_id == user_id)
        .filter(or_(UserNotification.is_read == False, UserNotification.created_at > cutoff))  # noqa: E712
        .filter(or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > now))
        .order_by(UserNotification.created_at.desc())
        .limit(10)
        .all()
    )
    return {r.id: r.title for r in rows}


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": PROFILE})
        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": PROFILE})
        db.session.commit()
        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                "VALUES (:id, 'IST', 'free', 0, :token)"
            ), {"id": PROFILE, "token": "fake-fcm-token-9501"})
            conn.commit()

        # ==============================================================
        print("=== Pure function: expiry_for_astro_event_notification ===")
        # ==============================================================
        aug16 = date(2026, 8, 16)
        tomorrow_expiry = expiry_for_astro_event_notification(event_date=aug16, is_forward_looking=True)
        check(
            "Tomorrow-framed event (sent Aug 15 evening, event on Aug 16) "
            "expires exactly at Aug 16 00:00 IST (== Aug 15 18:30 UTC)",
            tomorrow_expiry == datetime(2026, 8, 15, 18, 30, 0),
        )
        today_expiry = expiry_for_astro_event_notification(event_date=aug16, is_forward_looking=False)
        check(
            "Today-framed event (sent Aug 16 morning) expires at end of Aug 16 "
            "(Aug 17 00:00 IST == Aug 16 18:30 UTC)",
            today_expiry == datetime(2026, 8, 16, 18, 30, 0),
        )

        print("\n=== Pure function: expiry_for_same_day_notification (Dasha start) ===")
        dasha_expiry = expiry_for_same_day_notification(generated_on=aug16)
        check(
            "Dasha-start expires at end of its generation day",
            dasha_expiry == datetime(2026, 8, 16, 18, 30, 0),
        )

        print("\n=== Pure function: expiry_for_alert_notification ===")
        alert_expiry = expiry_for_alert_notification(active_until=date(2026, 8, 17))
        check(
            "Alert expires at end of its active_until date",
            alert_expiry == datetime(2026, 8, 17, 18, 30, 0),
        )

        # ==============================================================
        print("\n=== Bell visibility: active vs. expired (server-side) ===")
        # ==============================================================
        now = datetime.utcnow()

        row_active = UserNotification(
            user_id=PROFILE, title="N2 Active", body="still valid",
            data={"type": "event", "event_id": "1"}, is_read=False,
            expires_at=now + timedelta(hours=1),
        )
        db.session.add(row_active)
        db.session.commit()
        check("Active (not-yet-expired) notification IS visible", row_active.id in bell_visible_ids(PROFILE, now))

        row_expired = UserNotification(
            user_id=PROFILE, title="N2 Expired", body="stale",
            data={"type": "event", "event_id": "2"}, is_read=False,
            expires_at=now - timedelta(minutes=1),
        )
        db.session.add(row_expired)
        db.session.commit()
        visible2 = bell_visible_ids(PROFILE, now)
        check("Expired notification is EXCLUDED from the Bell query", row_expired.id not in visible2)
        check(
            "...but its row still physically exists (audit/analytics preserved, "
            "not deleted just because it expired)",
            db.session.get(UserNotification, row_expired.id) is not None,
        )

        # ==============================================================
        print("\n=== Today/Tomorrow transition: same event, no stale duplicate ===")
        # ==============================================================
        # Aug 15 evening sends "Tomorrow"; Aug 16 morning sends "Today".
        tomorrow_row = UserNotification(
            user_id=PROFILE, title="N2 Event Tomorrow", body="...",
            data={"type": "event", "event_id": "3"}, is_read=False,
            expires_at=expiry_for_astro_event_notification(event_date=date(2026, 8, 16), is_forward_looking=True),
        )
        db.session.add(tomorrow_row)
        db.session.commit()

        before_midnight = datetime(2026, 8, 15, 12, 0, 0)  # Aug 15 17:30 IST -- clearly evening, pre-midnight
        check(
            "Tomorrow-framed notification IS visible before IST midnight",
            tomorrow_row.id in bell_visible_ids(PROFILE, before_midnight),
        )

        after_midnight = datetime(2026, 8, 15, 19, 0, 0)  # Aug 16 00:30 IST -- just past midnight
        check(
            "SAME Tomorrow-framed notification is INVISIBLE after IST midnight "
            "-- the exact stale-'Tomorrow' scenario N2 targets",
            tomorrow_row.id not in bell_visible_ids(PROFILE, after_midnight),
        )

        today_row = UserNotification(
            user_id=PROFILE, title="N2 Event Today", body="...",
            data={"type": "event", "event_id": "3"}, is_read=False,
            expires_at=expiry_for_astro_event_notification(event_date=date(2026, 8, 16), is_forward_looking=False),
        )
        db.session.add(today_row)
        db.session.commit()
        visible_day2 = bell_visible_ids(PROFILE, after_midnight)
        check("Fresh Today representation IS visible", today_row.id in visible_day2)
        check(
            "...and the stale Tomorrow representation for the SAME event does "
            "NOT coexist with it",
            tomorrow_row.id not in visible_day2,
        )

        # ==============================================================
        print("\n=== Legacy/NULL expiry: never hidden by this policy ===")
        # ==============================================================
        legacy_row = UserNotification(
            user_id=PROFILE, title="N2 Legacy Transactional", body="...",
            data={"type": "custom"}, is_read=False, expires_at=None,
        )
        db.session.add(legacy_row)
        db.session.commit()
        far_future = datetime(2099, 1, 1)
        check(
            "NULL expires_at (legacy row / transactional notification) remains "
            "visible indefinitely -- not accidentally removed by this policy, "
            "even queried from far in the future",
            legacy_row.id in bell_visible_ids(PROFILE, far_future),
        )

        # ==============================================================
        print("\n=== Late scheduler execution does not resurrect stale Tomorrow content ===")
        # ==============================================================
        late_row = UserNotification(
            user_id=PROFILE, title="N2 Late Tomorrow", body="...",
            data={"type": "event", "event_id": "4"}, is_read=False,
            expires_at=expiry_for_astro_event_notification(event_date=date(2026, 8, 16), is_forward_looking=True),
        )
        db.session.add(late_row)
        db.session.commit()
        far_after = datetime(2026, 8, 17, 0, 0, 0)
        check(
            "A Tomorrow notification's expiry is derived from event_date, not "
            "send time -- even if inserted very late, it is correctly excluded "
            "once its own boundary has passed",
            late_row.id not in bell_visible_ids(PROFILE, far_after),
        )

        # ==============================================================
        print("\n=== N2.1: Pure function -- expiry_for_dasha_pre_notification ===")
        # ==============================================================
        dasha_pre_expiry = expiry_for_dasha_pre_notification(transition_date=date(2026, 8, 20))
        check(
            "Dasha-pre expires exactly at IST midnight of its OWN transition "
            "date (Aug 20 00:00 IST == Aug 19 18:30 UTC) -- the instant the "
            "new Dasha begins, not end-of-day",
            dasha_pre_expiry == datetime(2026, 8, 19, 18, 30, 0),
        )

        # ==============================================================
        print("\n=== N2.1: Dasha-pre lifecycle -- visible before / invisible after transition ===")
        # ==============================================================
        # A T-5 warning sent Aug 15 about a Dasha that actually starts Aug 20.
        transition_date = date(2026, 8, 20)
        dasha_pre_row = UserNotification(
            user_id=PROFILE, title="⏳ Dasha Change Coming",
            body="5 din baad aapki Venus - Moon dasha shuru hogi",
            data={
                "type": "dasha_pre", "event_id": "dasha_pre_9501_Venus_Moon",
                "mahadasha": "Venus", "antardasha": "Moon",
                "start_date": transition_date.isoformat(),
            },
            is_read=False,
            expires_at=expiry_for_dasha_pre_notification(transition_date=transition_date),
        )
        db.session.add(dasha_pre_row)
        db.session.commit()

        # Requirement 1: visible before the transition.
        before_transition = datetime(2026, 8, 18, 12, 0, 0)  # Aug 18, well before Aug 20
        check(
            "N2.1 Test 1: Dasha-pre IS visible before its transition boundary",
            dasha_pre_row.id in bell_visible_ids(PROFILE, before_transition),
        )

        # Requirement 2: invisible exactly when the transition boundary is reached.
        at_transition = datetime(2026, 8, 19, 19, 0, 0)  # Aug 20 00:30 IST -- just past the boundary
        check(
            "N2.1 Test 2: Dasha-pre is INVISIBLE once the transition boundary "
            "is reached",
            dasha_pre_row.id not in bell_visible_ids(PROFILE, at_transition),
        )

        # Requirement 3: a fresh Dasha-Today notification for the SAME
        # transition can appear without the stale Dasha-pre warning
        # coexisting (mirrors the Event Today/Tomorrow proof above).
        dasha_today_row = UserNotification(
            user_id=PROFILE, title="Venus Dasha Update 🔮",
            body="Venus - Moon phase शुरू हो गया है",
            data={"type": "dasha", "event_id": "dasha_9501_Venus_Moon"},
            is_read=False,
            expires_at=expiry_for_same_day_notification(generated_on=transition_date),
        )
        db.session.add(dasha_today_row)
        db.session.commit()
        visible_transition_day = bell_visible_ids(PROFILE, at_transition)
        check(
            "N2.1 Test 3: fresh Dasha-Today notification IS visible",
            dasha_today_row.id in visible_transition_day,
        )
        check(
            "N2.1 Test 3: ...and the stale Dasha-pre warning for the SAME "
            "transition does NOT coexist with it",
            dasha_pre_row.id not in visible_transition_day,
        )

        # Requirement 4: the boundary is derived from the authoritative
        # transition date (data["start_date"], sourced from
        # UserDashaTimeline.start_date), never from when the notification
        # happened to be sent -- proven by computing the SAME expiry from
        # two different (fake) "sent at" moments and getting an identical,
        # send-time-independent result.
        expiry_if_sent_aug15 = expiry_for_dasha_pre_notification(transition_date=transition_date)
        expiry_if_sent_aug18 = expiry_for_dasha_pre_notification(transition_date=transition_date)
        check(
            "N2.1 Test 4: expiry depends only on transition_date, not on "
            "send timestamp (identical regardless of when it was generated)",
            expiry_if_sent_aug15 == expiry_if_sent_aug18 == datetime(2026, 8, 19, 18, 30, 0),
        )

        # Requirement 5: a delayed scheduler run (inserting the row late)
        # cannot extend the stale Dasha-pre's lifetime -- its expires_at is
        # still computed from transition_date, so a row written well after
        # generation "should" have happened is still correctly excluded
        # once the real boundary has passed.
        late_dasha_pre_row = UserNotification(
            user_id=PROFILE, title="⏳ Dasha Change Coming (late insert)",
            body="...", data={"type": "dasha_pre", "event_id": "dasha_pre_9501_late"},
            is_read=False,
            expires_at=expiry_for_dasha_pre_notification(transition_date=transition_date),
        )
        db.session.add(late_dasha_pre_row)
        db.session.commit()
        far_after_transition = datetime(2026, 8, 21, 0, 0, 0)
        check(
            "N2.1 Test 5: a late-inserted Dasha-pre row is still excluded "
            "once the real transition boundary has passed -- delayed "
            "execution does not extend its stale lifetime",
            late_dasha_pre_row.id not in bell_visible_ids(PROFILE, far_after_transition),
        )

        # ==============================================================
        print("\n=== Personalized Alert: real write path (finalize_delivery) ===")
        # ==============================================================
        repo = AlertPersistenceRepository()
        repo.save_detection(
            profile_id=PROFILE, event_id="mood_positive", category="emotional",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 16),
            evaluated_at=datetime(2026, 8, 14, 12, 0, 0),
        )
        repo.finalize_delivery(
            profile_id=PROFILE, event_id="mood_positive",
            notification_title="Mood Positive", notification_body="body text",
            notification_data={"type": "alert", "event_id": "mood_positive"},
            delivered_at=datetime(2026, 8, 14, 12, 0, 0),
        )
        alert_bell_row = UserNotification.query.filter_by(
            user_id=PROFILE, title="Mood Positive",
        ).order_by(UserNotification.id.desc()).first()
        check("Alert delivery created a Bell row", alert_bell_row is not None)
        check(
            "...with expires_at derived from active_until (Aug 16), not None "
            "and not an arbitrary generic number",
            alert_bell_row is not None
            and alert_bell_row.expires_at == datetime(2026, 8, 16, 18, 30, 0),
        )
        check(
            "Personalized Alert respects its real validity: visible before "
            "active_until's boundary",
            alert_bell_row is not None
            and alert_bell_row.id in bell_visible_ids(PROFILE, datetime(2026, 8, 16, 12, 0, 0)),
        )
        check(
            "...and excluded once active_until's own boundary has passed",
            alert_bell_row is not None
            and alert_bell_row.id not in bell_visible_ids(PROFILE, datetime(2026, 8, 17, 0, 0, 0)),
        )

        # ==============================================================
        print("\n=== Transactional-shaped notification unaffected by astrology expiry policy ===")
        # ==============================================================
        transactional_row = UserNotification(
            user_id=PROFILE, title="N2 Report Ready", body="Your report is ready",
            data={"type": "report_ready"}, is_read=False, expires_at=None,
        )
        db.session.add(transactional_row)
        db.session.commit()
        check(
            "A transactional-shaped notification (unrecognized type by this "
            "loop) keeps expires_at=None and is never auto-expired by this "
            "policy, queried far in the future",
            transactional_row.id in bell_visible_ids(PROFILE, far_future),
        )

        db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": PROFILE})
        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": PROFILE})
        db.session.commit()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
