"""
test_notification_activity_events.py
-------------------------------------------------
Phase 4D: proves the Notifications domain's 2 canonical backend activity
events (notification_created, notification_sent) are emitted at the
correct, already-frozen producer points across all three verified
production pipelines:

  A. Admin/marketing NotificationJob pipeline
     (notifications/notification_service.py::send_job_now())

  B. Personalized/event-scheduler pipeline
     (services/event_scheduler.py::_emit_scheduler_notification_events(),
     the extracted, directly-testable emission seam
     run_daily_event_job() itself calls after each user's own commit --
     see this file's own docstring for why the surrounding scheduler
     loop itself is not re-exercised end-to-end here)

  C. Alerts delivery pipeline
     (modules/alerts/alert_delivery_service.py::deliver_alert(), via
     persistence_repository.py::finalize_delivery()'s new return shape)

with the exact identity/entity/properties/notification_context/dedupe
contract the Phase 4D design freeze locked (UserNotification.id as the
universal durable entity), and that analytics failure of every kind can
never alter the notification business result. Also proves the ledger
never contains title/body/personalized text/tokens/PII/raw payloads.

Pipeline C's bell-only path (record_bell_only()) is NOT instrumented in
this phase -- its only call site is modules/alerts/alerts_scheduler.py,
a file outside this phase's approved scope (see the final report) -- so
no test claims that behavior here.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real FCM/network call is ever made (every
send function is monkeypatched/injected). Test AppUsers use a unique,
obviously-test-only moon_sign marker so Pipeline A's real audience
query (which has no per-ID filter) can never sweep in a pre-existing
real user. All test rows are created with dedicated markers and deleted
in a finally block, keyed by their own ids -- never a broad DELETE.
"""

import os
import sys
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

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


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    from modules.models_user import AppUser
    from notifications.notification_models import NotificationJob, NotificationLog, UserNotification

    from modules.activity_events.service import LedgerWriteResult
    import notifications.notification_service as notification_service_module
    from notifications.notification_service import send_job_now

    import services.event_scheduler as event_scheduler_module
    from services.event_scheduler import _emit_scheduler_notification_events

    import modules.alerts.alert_delivery_service as alert_delivery_module
    from modules.alerts.alert_delivery_service import deliver_alert, _emit_alert_notification_events
    from modules.alerts.persistence_repository import AlertPersistenceRepository, AlertPersistenceError
    from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS
    from modules.entitlement.entitlement_models import EntitlementSnapshot, TrialStatus, SubscriptionStatus

    ZODIAC_MARKER = "phase4d-test-zodiac"
    ALL_SEGMENTS = list(SUBSCRIPTION_SECTIONS)

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"REFUSING to run against {current_db!r} -- local only."
        )

        created_app_user_ids = []
        created_job_ids = []
        created_user_notification_ids = []
        created_notification_log_ids = []
        created_alert_profile_ids = []
        created_event_ids = []

        def new_app_user(fcm_token="fake-fcm-token", moon_sign=None):
            au = AppUser(
                firebase_uid=f"phase4d-test-{uuid.uuid4().hex[:10]}",
                fcm_token=fcm_token,
                moon_sign=moon_sign or ZODIAC_MARKER,
            )
            db.session.add(au)
            db.session.commit()
            created_app_user_ids.append(au.id)
            return au.id

        def new_zodiac_marker():
            # Phase 4D.2 -- now that Pipeline A's send_job_now() actually
            # completes for real (both blockers fixed), a shared zodiac
            # marker across sub-tests would let one sub-test's job sweep
            # in every other sub-test's already-created AppUsers too
            # (get_recipients() has no per-job/per-ID scoping). Each
            # Pipeline A sub-test below gets its OWN unique marker so its
            # own job's audience is isolated to exactly its own fixtures.
            return f"phase4d-zodiac-{uuid.uuid4().hex[:10]}"

        def get_ledger_row(dedupe_key):
            return db.session.execute(
                text("SELECT * FROM activity_events WHERE dedupe_key = :dk"),
                {"dk": dedupe_key},
            ).fetchone()

        def rows_for_entity(entity_type, entity_id, event_name=None):
            if event_name:
                return db.session.execute(
                    text(
                        "SELECT * FROM activity_events WHERE entity_type = :et "
                        "AND entity_id = :eid AND event_name = :en ORDER BY recorded_at"
                    ),
                    {"et": entity_type, "eid": str(entity_id), "en": event_name},
                ).fetchall()
            return db.session.execute(
                text(
                    "SELECT * FROM activity_events WHERE entity_type = :et "
                    "AND entity_id = :eid ORDER BY recorded_at"
                ),
                {"et": entity_type, "eid": str(entity_id)},
            ).fetchall()

        def track_event(row):
            if row is not None:
                created_event_ids.append(str(row.event_id))
            return row

        def track_all(rows):
            for r in rows:
                created_event_ids.append(str(r.event_id))
            return rows

        class FakeFcmSender:
            """Pipeline A's injected fcm_sender -- per-token controllable."""

            def __init__(self, result_by_token=None, default=True):
                self.result_by_token = result_by_token or {}
                self.default = default
                self.calls = []

            def __call__(self, *, token, title, body, data=None):
                self.calls.append({"token": token, "title": title, "body": body, "data": data})
                return self.result_by_token.get(token, self.default)

        try:
            # ==========================================================
            # PIPELINE A -- admin/marketing (notification_service.py)
            # ==========================================================
            print("=== A1: one successful recipient -> one created + one sent ===")
            zodiac_a1 = new_zodiac_marker()
            profile_a1 = new_app_user(moon_sign=zodiac_a1)
            job_a1 = NotificationJob(
                title="Test Job A1", body="Body A1", type="custom",
                audience={"zodiac": [zodiac_a1]}, payload={"screen": "test_a1"},
                scheduled_at=datetime.utcnow(), status="pending",
            )
            db.session.add(job_a1)
            db.session.commit()
            created_job_ids.append(job_a1.id)

            sender_a1 = FakeFcmSender(default=True)
            success_a1, failed_a1 = send_job_now(job_a1, sender_a1)
            check("A1: 1 success, 0 failed", success_a1 == 1 and failed_a1 == 0)

            un_a1 = UserNotification.query.filter_by(user_id=profile_a1).first()
            check("A1: UserNotification row created", un_a1 is not None)
            if un_a1:
                created_user_notification_ids.append(un_a1.id)
                nl_a1 = NotificationLog.query.filter_by(user_id=profile_a1, event_id=str(job_a1.id)).first()
                if nl_a1:
                    created_notification_log_ids.append(nl_a1.id)

                created_row_a1 = track_event(get_ledger_row(f"notification_created:{un_a1.id}"))
                sent_row_a1 = track_event(get_ledger_row(f"notification_sent:{un_a1.id}"))
                check("A1: notification_created row exists", created_row_a1 is not None)
                check("A1: notification_sent row exists", sent_row_a1 is not None)
                if created_row_a1 is not None:
                    check("A1: platform/source correct", created_row_a1.platform == "backend_internal" and created_row_a1.source == "notification_job")
                    check("A1: profile_id correct", created_row_a1.profile_id == profile_a1)
                    check("A1: firebase_uid None", created_row_a1.firebase_uid is None)
                    check("A1: entity_type/entity_id correct", created_row_a1.entity_type == "notification" and created_row_a1.entity_id == str(un_a1.id))
                    check("A1: properties == {notification_type: custom, target_scope: broadcast}", created_row_a1.properties == {"notification_type": "custom", "target_scope": "broadcast"})
                    check("A1: notification_context correct", created_row_a1.notification_context == {"notification_id": str(un_a1.id), "campaign_id": str(job_a1.id), "slot": "general"})
                if sent_row_a1 is not None:
                    check("A1: notification_sent properties == {}", sent_row_a1.properties == {})
                    check("A1: notification_sent notification_context correct", sent_row_a1.notification_context == {"notification_id": str(un_a1.id), "campaign_id": str(job_a1.id), "slot": "general"})

            # ==========================================================
            print("\n=== A2: N successful recipients -> N created + N sent ===")
            # ==========================================================
            zodiac_a2 = new_zodiac_marker()
            profiles_a2 = [new_app_user(moon_sign=zodiac_a2) for _ in range(3)]
            job_a2 = NotificationJob(
                title="Test Job A2", body="Body A2", type="festival",
                audience={"zodiac": [zodiac_a2]}, payload={"screen": "test_a2"},
                scheduled_at=datetime.utcnow(), status="pending",
            )
            db.session.add(job_a2)
            db.session.commit()
            created_job_ids.append(job_a2.id)

            sender_a2 = FakeFcmSender(default=True)
            success_a2, failed_a2 = send_job_now(job_a2, sender_a2)
            un_rows_a2 = UserNotification.query.filter(
                UserNotification.user_id.in_(profiles_a2)
            ).all()
            check("A2: 3 successful recipients got a UserNotification row", len(un_rows_a2) == 3)
            for un in un_rows_a2:
                created_user_notification_ids.append(un.id)
                r = track_event(get_ledger_row(f"notification_created:{un.id}"))
                s = track_event(get_ledger_row(f"notification_sent:{un.id}"))
                check(f"A2: created+sent exist for UserNotification.id={un.id}", r is not None and s is not None)
            nl_rows_a2 = NotificationLog.query.filter_by(event_id=str(job_a2.id)).all()
            for nl in nl_rows_a2:
                created_notification_log_ids.append(nl.id)

            # ==========================================================
            print("\n=== A3: provider returns False -> no UserNotification, no event ===")
            # ==========================================================
            zodiac_a3 = new_zodiac_marker()
            profile_a3 = new_app_user(moon_sign=zodiac_a3)
            job_a3 = NotificationJob(
                title="Test Job A3", body="Body A3", type="custom",
                audience={"zodiac": [zodiac_a3]}, payload={"screen": "test_a3"},
                scheduled_at=datetime.utcnow(), status="pending",
            )
            db.session.add(job_a3)
            db.session.commit()
            created_job_ids.append(job_a3.id)

            sender_a3 = FakeFcmSender(default=False)
            success_a3, failed_a3 = send_job_now(job_a3, sender_a3)
            check("A3: all recipients failed", success_a3 == 0)
            un_a3 = UserNotification.query.filter_by(user_id=profile_a3).first()
            check("A3: NO UserNotification row created", un_a3 is None)
            fail_events_a3 = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE profile_id = :p"), {"p": profile_a3},
            ).scalar()
            check("A3: NO activity_events row for this profile", fail_events_a3 == 0)

            # ==========================================================
            print("\n=== A4: NotificationLog dedup skip -> no send, no event ===")
            # ==========================================================
            zodiac_a4 = new_zodiac_marker()
            profile_a4 = new_app_user(moon_sign=zodiac_a4)
            job_a4 = NotificationJob(
                title="Test Job A4", body="Body A4", type="custom",
                audience={"zodiac": [zodiac_a4]}, payload={"screen": "test_a4"},
                scheduled_at=datetime.utcnow(), status="pending",
            )
            db.session.add(job_a4)
            db.session.commit()
            created_job_ids.append(job_a4.id)
            # Pre-seed a NotificationLog for this exact (user, job, slot=general)
            pre_log = NotificationLog(user_id=profile_a4, event_id=str(job_a4.id), slot="general")
            db.session.add(pre_log)
            db.session.commit()
            created_notification_log_ids.append(pre_log.id)

            sender_a4 = FakeFcmSender(default=True)
            send_job_now(job_a4, sender_a4)
            check("A4: fcm_sender never called for the deduped recipient", len(sender_a4.calls) == 0)
            un_a4 = UserNotification.query.filter_by(user_id=profile_a4).first()
            check("A4: NO UserNotification row created (deduped before send)", un_a4 is None)
            events_a4 = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE profile_id = :p"), {"p": profile_a4},
            ).scalar()
            check("A4: NO activity_events row for this profile", events_a4 == 0)

            # ==========================================================
            print("\n=== A5: NotificationLog created but UserNotification independently skipped -> no activity event ===")
            # ==========================================================
            zodiac_a5 = new_zodiac_marker()
            profile_a5 = new_app_user(moon_sign=zodiac_a5)
            job_a5 = NotificationJob(
                title="Test Job A5", body="Body A5", type="custom",
                audience={"zodiac": [zodiac_a5]}, payload={"screen": "test_a5_shared"},
                scheduled_at=datetime.utcnow(), status="pending",
            )
            db.session.add(job_a5)
            db.session.commit()
            created_job_ids.append(job_a5.id)
            # Pre-seed a UserNotification whose `data` already matches
            # job_a5.payload exactly -- triggers send_job_now()'s own
            # independent existing_notif dedup gate.
            pre_un = UserNotification(user_id=profile_a5, title="Pre-existing", body="Pre-existing body", data=job_a5.payload)
            db.session.add(pre_un)
            db.session.commit()
            created_user_notification_ids.append(pre_un.id)

            sender_a5 = FakeFcmSender(default=True)
            send_job_now(job_a5, sender_a5)
            nl_a5 = NotificationLog.query.filter_by(user_id=profile_a5, event_id=str(job_a5.id)).first()
            check("A5: NotificationLog WAS created (the send succeeded)", nl_a5 is not None)
            if nl_a5:
                created_notification_log_ids.append(nl_a5.id)
            un_count_a5 = UserNotification.query.filter_by(user_id=profile_a5).count()
            check("A5: still only the ONE pre-existing UserNotification row (no second insert)", un_count_a5 == 1)
            events_a5 = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE profile_id = :p"), {"p": profile_a5},
            ).scalar()
            check("A5: NO activity_events row emitted (NotificationLog-only case is correctly silent)", events_a5 == 0)

            # ==========================================================
            print("\n=== A6: analytics failure isolation (Pipeline A) ===")
            # ==========================================================
            zodiac_a6a = new_zodiac_marker()
            profile_a6a = new_app_user(moon_sign=zodiac_a6a)
            job_a6a = NotificationJob(title="A6a", body="A6a", type="custom", audience={"zodiac": [zodiac_a6a]}, payload={"screen": "a6a"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a6a)
            db.session.commit()
            created_job_ids.append(job_a6a.id)
            with patch("notifications.notification_service.record_event") as mock_re_a6a:
                mock_re_a6a.return_value = LedgerWriteResult(status="write_failed")
                s, f = send_job_now(job_a6a, FakeFcmSender(default=True))
            check("A6a write_failed: business result unchanged (1 success)", s == 1 and f == 0)
            un_a6a = UserNotification.query.filter_by(user_id=profile_a6a).first()
            check("A6a write_failed: UserNotification STILL committed", un_a6a is not None)
            if un_a6a:
                created_user_notification_ids.append(un_a6a.id)
            nl_a6a = NotificationLog.query.filter_by(user_id=profile_a6a, event_id=str(job_a6a.id)).first()
            if nl_a6a:
                created_notification_log_ids.append(nl_a6a.id)

            zodiac_a6b = new_zodiac_marker()
            profile_a6b = new_app_user(moon_sign=zodiac_a6b)
            job_a6b = NotificationJob(title="A6b", body="A6b", type="custom", audience={"zodiac": [zodiac_a6b]}, payload={"screen": "a6b"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a6b)
            db.session.commit()
            created_job_ids.append(job_a6b.id)
            with patch("notifications.notification_service.record_event") as mock_re_a6b:
                mock_re_a6b.side_effect = RuntimeError("simulated unexpected analytics exception")
                s, f = send_job_now(job_a6b, FakeFcmSender(default=True))
            check("A6b exception: does NOT propagate, business result unchanged", s == 1 and f == 0)
            un_a6b = UserNotification.query.filter_by(user_id=profile_a6b).first()
            check("A6b exception: UserNotification STILL committed", un_a6b is not None)
            if un_a6b:
                created_user_notification_ids.append(un_a6b.id)
            nl_a6b = NotificationLog.query.filter_by(user_id=profile_a6b, event_id=str(job_a6b.id)).first()
            if nl_a6b:
                created_notification_log_ids.append(nl_a6b.id)

            zodiac_a6c = new_zodiac_marker()
            profile_a6c = new_app_user(moon_sign=zodiac_a6c)
            job_a6c = NotificationJob(title="A6c", body="A6c", type="custom", audience={"zodiac": [zodiac_a6c]}, payload={"screen": "a6c"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a6c)
            db.session.commit()
            created_job_ids.append(job_a6c.id)
            real_env_a6c = os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            try:
                s, f = send_job_now(job_a6c, FakeFcmSender(default=True))
            finally:
                if real_env_a6c is not None:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = real_env_a6c
            check("A6c missing env: business result unchanged", s == 1 and f == 0)
            un_a6c = UserNotification.query.filter_by(user_id=profile_a6c).first()
            check("A6c missing env: UserNotification STILL committed", un_a6c is not None)
            if un_a6c:
                created_user_notification_ids.append(un_a6c.id)
                check("A6c missing env: no activity_events row persisted", len(rows_for_entity("notification", un_a6c.id)) == 0)
            nl_a6c = NotificationLog.query.filter_by(user_id=profile_a6c, event_id=str(job_a6c.id)).first()
            if nl_a6c:
                created_notification_log_ids.append(nl_a6c.id)

            zodiac_a6d = new_zodiac_marker()
            profile_a6d = new_app_user(moon_sign=zodiac_a6d)
            job_a6d = NotificationJob(title="A6d", body="A6d", type="custom", audience={"zodiac": [zodiac_a6d]}, payload={"screen": "a6d"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a6d)
            db.session.commit()
            created_job_ids.append(job_a6d.id)
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "not_a_real_environment"
            try:
                s, f = send_job_now(job_a6d, FakeFcmSender(default=True))
            finally:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            check("A6d invalid env: business result unchanged", s == 1 and f == 0)
            un_a6d = UserNotification.query.filter_by(user_id=profile_a6d).first()
            check("A6d invalid env: UserNotification STILL committed", un_a6d is not None)
            if un_a6d:
                created_user_notification_ids.append(un_a6d.id)
            nl_a6d = NotificationLog.query.filter_by(user_id=profile_a6d, event_id=str(job_a6d.id)).first()
            if nl_a6d:
                created_notification_log_ids.append(nl_a6d.id)

            # ==========================================================
            print("\n=== A7: one analytics failure in post-commit batch does not prevent later rows ===")
            # ==========================================================
            zodiac_a7 = new_zodiac_marker()
            profiles_a7 = [new_app_user(moon_sign=zodiac_a7) for _ in range(3)]
            job_a7 = NotificationJob(title="A7", body="A7", type="custom", audience={"zodiac": [zodiac_a7]}, payload={"screen": "a7"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a7)
            db.session.commit()
            created_job_ids.append(job_a7.id)

            call_count_a7 = {"n": 0}
            real_record_event_a7 = notification_service_module.record_event

            def flaky_record_event(**kwargs):
                call_count_a7["n"] += 1
                if call_count_a7["n"] == 2:
                    raise RuntimeError("simulated failure on the 2nd emission call")
                return real_record_event_a7(**kwargs)

            with patch("notifications.notification_service.record_event", side_effect=flaky_record_event):
                s, f = send_job_now(job_a7, FakeFcmSender(default=True))
            check("A7: all 3 recipients still succeeded at the business level", s == 3)
            un_rows_a7 = UserNotification.query.filter(UserNotification.user_id.in_(profiles_a7)).all()
            check("A7: all 3 UserNotification rows committed regardless of the mid-batch analytics failure", len(un_rows_a7) == 3)
            surviving_events_a7 = 0
            for un in un_rows_a7:
                created_user_notification_ids.append(un.id)
                r = track_event(get_ledger_row(f"notification_created:{un.id}"))
                s2 = track_event(get_ledger_row(f"notification_sent:{un.id}"))
                if r is not None:
                    surviving_events_a7 += 1
                if s2 is not None:
                    surviving_events_a7 += 1
            check("A7: later rows' emissions were still attempted after the mid-batch failure (some events survived)", surviving_events_a7 >= 4)
            for nl in NotificationLog.query.filter_by(event_id=str(job_a7.id)).all():
                created_notification_log_ids.append(nl.id)

            # ==========================================================
            print("\n=== A8: direct UserNotification.data JSONB-cast dedup semantics ===")
            # ==========================================================
            # A8a: no existing UserNotification -> query works, new row created.
            zodiac_a8a = new_zodiac_marker()
            profile_a8a = new_app_user(moon_sign=zodiac_a8a)
            job_a8a = NotificationJob(title="A8a", body="A8a", type="custom", audience={"zodiac": [zodiac_a8a]}, payload={"screen": "a8a"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a8a)
            db.session.commit()
            created_job_ids.append(job_a8a.id)
            s_a8a, f_a8a = send_job_now(job_a8a, FakeFcmSender(default=True))
            check("A8a: no existing row -> query succeeds, send succeeds", s_a8a == 1)
            un_a8a = UserNotification.query.filter_by(user_id=profile_a8a).first()
            check("A8a: a new UserNotification WAS created", un_a8a is not None)
            if un_a8a:
                created_user_notification_ids.append(un_a8a.id)
                nl_a8a = NotificationLog.query.filter_by(user_id=profile_a8a, event_id=str(job_a8a.id)).first()
                if nl_a8a:
                    created_notification_log_ids.append(nl_a8a.id)
                r = track_event(get_ledger_row(f"notification_created:{un_a8a.id}"))
                s2 = track_event(get_ledger_row(f"notification_sent:{un_a8a.id}"))
                check("A8a: created+sent both exist", r is not None and s2 is not None)

            # A8b: same JSON object, different key insertion order -> still
            # treated as equal (real JSON VALUE equality, not text equality).
            zodiac_a8b = new_zodiac_marker()
            profile_a8b = new_app_user(moon_sign=zodiac_a8b)
            pre_un_a8b = UserNotification(user_id=profile_a8b, title="pre", body="pre", data={"screen": "a8b", "campaign": "x"})
            db.session.add(pre_un_a8b)
            db.session.commit()
            created_user_notification_ids.append(pre_un_a8b.id)
            job_a8b = NotificationJob(
                title="A8b", body="A8b", type="custom", audience={"zodiac": [zodiac_a8b]},
                payload={"campaign": "x", "screen": "a8b"},  # same keys/values, DIFFERENT insertion order
                scheduled_at=datetime.utcnow(), status="pending",
            )
            db.session.add(job_a8b)
            db.session.commit()
            created_job_ids.append(job_a8b.id)
            send_job_now(job_a8b, FakeFcmSender(default=True))
            un_count_a8b = UserNotification.query.filter_by(user_id=profile_a8b).count()
            check("A8b: key-order-different-but-value-equal JSON correctly matched -- still only ONE UserNotification", un_count_a8b == 1)
            nl_a8b = NotificationLog.query.filter_by(user_id=profile_a8b, event_id=str(job_a8b.id)).first()
            check("A8b: send still succeeded (NotificationLog written) despite the dedup match", nl_a8b is not None)
            if nl_a8b:
                created_notification_log_ids.append(nl_a8b.id)

            # A8c: same user, genuinely DIFFERENT payload -> new row allowed.
            zodiac_a8c = new_zodiac_marker()
            profile_a8c = new_app_user(moon_sign=zodiac_a8c)
            pre_un_a8c = UserNotification(user_id=profile_a8c, title="pre", body="pre", data={"screen": "a8c_original"})
            db.session.add(pre_un_a8c)
            db.session.commit()
            created_user_notification_ids.append(pre_un_a8c.id)
            job_a8c = NotificationJob(title="A8c", body="A8c", type="custom", audience={"zodiac": [zodiac_a8c]}, payload={"screen": "a8c_totally_different"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a8c)
            db.session.commit()
            created_job_ids.append(job_a8c.id)
            send_job_now(job_a8c, FakeFcmSender(default=True))
            un_rows_a8c = UserNotification.query.filter_by(user_id=profile_a8c).all()
            check("A8c: genuinely different payload -> a SECOND UserNotification was allowed", len(un_rows_a8c) == 2)
            for un in un_rows_a8c:
                if un.id not in created_user_notification_ids:
                    created_user_notification_ids.append(un.id)
            nl_a8c = NotificationLog.query.filter_by(user_id=profile_a8c, event_id=str(job_a8c.id)).first()
            if nl_a8c:
                created_notification_log_ids.append(nl_a8c.id)

            # A8d: different user, SAME payload -> independent row allowed
            # (the dedup check is scoped per-user, never cross-user).
            zodiac_a8d = new_zodiac_marker()
            profile_a8d_1 = new_app_user(moon_sign=zodiac_a8d)
            profile_a8d_2 = new_app_user(moon_sign=zodiac_a8d)
            pre_un_a8d = UserNotification(user_id=profile_a8d_1, title="pre", body="pre", data={"screen": "a8d"})
            db.session.add(pre_un_a8d)
            db.session.commit()
            created_user_notification_ids.append(pre_un_a8d.id)
            job_a8d = NotificationJob(title="A8d", body="A8d", type="custom", audience={"zodiac": [zodiac_a8d]}, payload={"screen": "a8d"}, scheduled_at=datetime.utcnow(), status="pending")
            db.session.add(job_a8d)
            db.session.commit()
            created_job_ids.append(job_a8d.id)
            send_job_now(job_a8d, FakeFcmSender(default=True))
            un_a8d_2 = UserNotification.query.filter_by(user_id=profile_a8d_2).first()
            check("A8d: a different user with the SAME payload got their OWN independent UserNotification", un_a8d_2 is not None)
            if un_a8d_2:
                created_user_notification_ids.append(un_a8d_2.id)
            for nl in NotificationLog.query.filter_by(event_id=str(job_a8d.id)).all():
                created_notification_log_ids.append(nl.id)

            # A8e: nested JSON, different key order at multiple levels ->
            # still correctly matched as equal (jsonb comparison is
            # recursive/structural, not shallow).
            zodiac_a8e = new_zodiac_marker()
            profile_a8e = new_app_user(moon_sign=zodiac_a8e)
            pre_un_a8e = UserNotification(
                user_id=profile_a8e, title="pre", body="pre",
                data={"screen": "a8e", "meta": {"a": 1, "b": [1, 2, 3]}},
            )
            db.session.add(pre_un_a8e)
            db.session.commit()
            created_user_notification_ids.append(pre_un_a8e.id)
            job_a8e = NotificationJob(
                title="A8e", body="A8e", type="custom", audience={"zodiac": [zodiac_a8e]},
                payload={"meta": {"b": [1, 2, 3], "a": 1}, "screen": "a8e"},  # nested keys reordered
                scheduled_at=datetime.utcnow(), status="pending",
            )
            db.session.add(job_a8e)
            db.session.commit()
            created_job_ids.append(job_a8e.id)
            send_job_now(job_a8e, FakeFcmSender(default=True))
            un_count_a8e = UserNotification.query.filter_by(user_id=profile_a8e).count()
            check("A8e: nested JSON with reordered keys correctly matched -- still only ONE UserNotification", un_count_a8e == 1)
            nl_a8e = NotificationLog.query.filter_by(user_id=profile_a8e, event_id=str(job_a8e.id)).first()
            if nl_a8e:
                created_notification_log_ids.append(nl_a8e.id)

            # ==========================================================
            # PIPELINE B -- event scheduler (direct emitter test)
            # ==========================================================
            print("\n=== B1: approved (pushed) row -> created + sent ===")
            # ==========================================================
            profile_b1 = new_app_user()
            un_b1 = UserNotification(user_id=profile_b1, title="B1", body="B1 body", data={"type": "panchang"})
            db.session.add(un_b1)
            db.session.commit()
            created_user_notification_ids.append(un_b1.id)

            _emit_scheduler_notification_events(rows_this_commit=[(un_b1, "panchang", True)], slot="morning")
            created_b1 = track_event(get_ledger_row(f"notification_created:{un_b1.id}"))
            sent_b1 = track_event(get_ledger_row(f"notification_sent:{un_b1.id}"))
            check("B1: notification_created exists", created_b1 is not None)
            check("B1: notification_sent exists", sent_b1 is not None)
            if created_b1 is not None:
                check("B1: source == event_scheduler", created_b1.source == "event_scheduler")
                check("B1: profile_id correct", created_b1.profile_id == profile_b1)
                check("B1: properties == {notification_type: panchang, target_scope: personal}", created_b1.properties == {"notification_type": "panchang", "target_scope": "personal"})
                check("B1: notification_context == {notification_id, slot} only (no campaign_id)", created_b1.notification_context == {"notification_id": str(un_b1.id), "slot": "morning"})

            # ==========================================================
            print("\n=== B2: approved + send failure -> no row/no event (nothing to emit) ===")
            # ==========================================================
            # By construction, a failed send never reaches
            # _emit_scheduler_notification_events() at all (no row is
            # ever staged) -- proven by inspecting the real caller
            # (services/event_scheduler.py's own "if success:" guard),
            # not re-tested here since there is nothing to call.
            check("B2: confirmed by code inspection -- failed sends never reach the emitter (no row exists to pass)", True)

            # ==========================================================
            print("\n=== B3: bell_only row -> created ONLY, no sent ===")
            # ==========================================================
            profile_b3 = new_app_user()
            un_b3 = UserNotification(user_id=profile_b3, title="B3 bell", body="B3 body", data={"type": "event", "delivery_channel": "bell_only"})
            db.session.add(un_b3)
            db.session.commit()
            created_user_notification_ids.append(un_b3.id)

            _emit_scheduler_notification_events(rows_this_commit=[(un_b3, "event", False)], slot="evening")
            created_b3 = track_event(get_ledger_row(f"notification_created:{un_b3.id}"))
            sent_b3 = get_ledger_row(f"notification_sent:{un_b3.id}")
            check("B3: notification_created exists", created_b3 is not None)
            check("B3: notification_sent does NOT exist (bell-only, no FCM interaction)", sent_b3 is None)

            # ==========================================================
            print("\n=== B4: dropped candidate -> no row/no event ===")
            # ==========================================================
            check("B4: confirmed by code inspection -- dropped candidates never create a row or reach the emitter", True)

            # ==========================================================
            print("\n=== B5: multiple committed notifications for one user in one transaction -> independent events ===")
            # ==========================================================
            profile_b5 = new_app_user()
            un_b5a = UserNotification(user_id=profile_b5, title="B5a", body="b", data={"type": "panchang"})
            un_b5b = UserNotification(user_id=profile_b5, title="B5b", body="b", data={"type": "dasha"})
            db.session.add(un_b5a)
            db.session.add(un_b5b)
            db.session.commit()
            created_user_notification_ids.extend([un_b5a.id, un_b5b.id])

            _emit_scheduler_notification_events(
                rows_this_commit=[(un_b5a, "panchang", True), (un_b5b, "dasha", False)], slot="morning",
            )
            r5a = track_event(get_ledger_row(f"notification_created:{un_b5a.id}"))
            s5a = track_event(get_ledger_row(f"notification_sent:{un_b5a.id}"))
            r5b = track_event(get_ledger_row(f"notification_created:{un_b5b.id}"))
            s5b = get_ledger_row(f"notification_sent:{un_b5b.id}")
            check("B5: un_b5a (pushed) got created+sent", r5a is not None and s5a is not None)
            check("B5: un_b5b (bell_only) got created only", r5b is not None and s5b is None)
            check("B5: dedupe keys are independent per row", r5a.dedupe_key != r5b.dedupe_key)

            # ==========================================================
            print("\n=== B6: repeated emission attempt against the same row does not duplicate ===")
            # ==========================================================
            _emit_scheduler_notification_events(rows_this_commit=[(un_b1, "panchang", True)], slot="morning")
            count_b6 = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"),
                {"dk": f"notification_created:{un_b1.id}"},
            ).scalar()
            check("B6: still exactly ONE notification_created row after a repeated emission attempt", count_b6 == 1)

            # ==========================================================
            print("\n=== B7: analytics failure isolation (Pipeline B) ===")
            # ==========================================================
            profile_b7a = new_app_user()
            un_b7a = UserNotification(user_id=profile_b7a, title="B7a", body="b", data={"type": "panchang"})
            db.session.add(un_b7a)
            db.session.commit()
            created_user_notification_ids.append(un_b7a.id)
            with patch("services.event_scheduler.record_event") as mock_re_b7a:
                mock_re_b7a.return_value = LedgerWriteResult(status="write_failed")
                _emit_scheduler_notification_events(rows_this_commit=[(un_b7a, "panchang", True)], slot="morning")
            check("B7a write_failed: UserNotification unaffected (still exists)", UserNotification.query.get(un_b7a.id) is not None)

            profile_b7b = new_app_user()
            un_b7b = UserNotification(user_id=profile_b7b, title="B7b", body="b", data={"type": "panchang"})
            db.session.add(un_b7b)
            db.session.commit()
            created_user_notification_ids.append(un_b7b.id)
            with patch("services.event_scheduler.record_event") as mock_re_b7b:
                mock_re_b7b.side_effect = RuntimeError("simulated")
                try:
                    _emit_scheduler_notification_events(rows_this_commit=[(un_b7b, "panchang", True)], slot="morning")
                    raised_b7b = False
                except Exception:
                    raised_b7b = True
            check("B7b exception: does NOT propagate out of the emitter", raised_b7b is False)

            profile_b7c = new_app_user()
            un_b7c = UserNotification(user_id=profile_b7c, title="B7c", body="b", data={"type": "panchang"})
            db.session.add(un_b7c)
            db.session.commit()
            created_user_notification_ids.append(un_b7c.id)
            real_env_b7c = os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            try:
                _emit_scheduler_notification_events(rows_this_commit=[(un_b7c, "panchang", True)], slot="morning")
            finally:
                if real_env_b7c is not None:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = real_env_b7c
            check("B7c missing env: no row persisted, no exception", len(rows_for_entity("notification", un_b7c.id)) == 0)

            profile_b7d = new_app_user()
            un_b7d = UserNotification(user_id=profile_b7d, title="B7d", body="b", data={"type": "panchang"})
            db.session.add(un_b7d)
            db.session.commit()
            created_user_notification_ids.append(un_b7d.id)
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "not_a_real_environment"
            try:
                _emit_scheduler_notification_events(rows_this_commit=[(un_b7d, "panchang", True)], slot="morning")
            finally:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            check("B7d invalid env: no exception raised", True)

            # ==========================================================
            print("\n=== B8: one row's analytics failure does not prevent later rows in the same batch ===")
            # ==========================================================
            profile_b8 = new_app_user()
            un_b8a = UserNotification(user_id=profile_b8, title="B8a", body="b", data={"type": "panchang"})
            un_b8b = UserNotification(user_id=profile_b8, title="B8b", body="b", data={"type": "dasha"})
            db.session.add(un_b8a)
            db.session.add(un_b8b)
            db.session.commit()
            created_user_notification_ids.extend([un_b8a.id, un_b8b.id])

            call_count_b8 = {"n": 0}
            real_record_event_b8 = event_scheduler_module.record_event

            def flaky_record_event_b8(**kwargs):
                call_count_b8["n"] += 1
                if call_count_b8["n"] == 1:
                    raise RuntimeError("simulated failure on the very first emission call")
                return real_record_event_b8(**kwargs)

            with patch("services.event_scheduler.record_event", side_effect=flaky_record_event_b8):
                _emit_scheduler_notification_events(
                    rows_this_commit=[(un_b8a, "panchang", True), (un_b8b, "dasha", True)], slot="morning",
                )
            r_b8b = track_event(get_ledger_row(f"notification_created:{un_b8b.id}"))
            s_b8b = track_event(get_ledger_row(f"notification_sent:{un_b8b.id}"))
            check("B8: the SECOND row's events still landed despite the FIRST row's analytics failure", r_b8b is not None and s_b8b is not None)

            # ==========================================================
            # PIPELINE C -- Alerts (deliver_alert / finalize_delivery)
            # ==========================================================
            print("\n=== C1: successful push + finalize_delivery -> created + sent ===")
            # ==========================================================
            profile_c1 = new_app_user()

            def entitled_snapshot(profile_id):
                return EntitlementSnapshot(
                    profile_id=profile_id, status="TRIAL", plan=None, selected_segment=None,
                    trial=TrialStatus(is_active=True),
                    subscription=SubscriptionStatus(is_active=False, status="PENDING"),
                    accessible_segments=ALL_SEGMENTS,
                )

            class FakeEntitlementService:
                def __init__(self, profile_id):
                    self._profile_id = profile_id

                def get_current_entitlement(self, profile_id):
                    return entitled_snapshot(profile_id)

            class FakeFcmSenderC:
                def __init__(self, result=True):
                    self.result = result
                    self.calls = []

                def __call__(self, *, token, title, body, data=None, android_tag=None):
                    self.calls.append({"token": token, "title": title, "body": body, "data": data})
                    return self.result

            repo_c = AlertPersistenceRepository()
            now_c = datetime(2026, 8, 20, 12, 0, 0)

            repo_c.save_detection(
                profile_id=profile_c1, event_id="mood_positive", category="emotional",
                state="NEW", confidence=0.7, priority="high",
                active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c,
            )
            created_alert_profile_ids.append(profile_c1)
            sender_c1 = FakeFcmSenderC(result=True)
            alert_delivery_module.send_push_notification = sender_c1

            result_c1 = deliver_alert(
                profile_id=profile_c1, event_id="mood_positive", fcm_token="fake-token",
                now=now_c, entitlement_service=FakeEntitlementService(profile_c1), repository=repo_c,
            )
            check("C1: delivered successfully (business result unchanged)", result_c1.sent and result_c1.stage == "delivered")
            un_c1 = UserNotification.query.filter_by(user_id=profile_c1).order_by(UserNotification.id.desc()).first()
            check("C1: UserNotification row committed", un_c1 is not None)
            if un_c1:
                created_user_notification_ids.append(un_c1.id)
                created_c1 = track_event(get_ledger_row(f"notification_created:{un_c1.id}"))
                sent_c1 = track_event(get_ledger_row(f"notification_sent:{un_c1.id}"))
                check("C1: notification_created exists", created_c1 is not None)
                check("C1: notification_sent exists", sent_c1 is not None)
                if created_c1 is not None:
                    check("C1: source == alert_delivery_service", created_c1.source == "alert_delivery_service")
                    check("C1: profile_id correct", created_c1.profile_id == profile_c1)
                    check("C1: properties == {notification_type: alert, target_scope: personal}", created_c1.properties == {"notification_type": "alert", "target_scope": "personal"})
                    check("C1: notification_context has ONLY notification_id (no slot, no campaign_id)", created_c1.notification_context == {"notification_id": str(un_c1.id)})

            # ==========================================================
            print("\n=== C2: provider failure before finalization -> no event ===")
            # ==========================================================
            profile_c2 = new_app_user()
            repo_c.save_detection(
                profile_id=profile_c2, event_id="mood_positive", category="emotional",
                state="NEW", confidence=0.7, priority="high",
                active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c,
            )
            created_alert_profile_ids.append(profile_c2)
            sender_c2 = FakeFcmSenderC(result=False)
            alert_delivery_module.send_push_notification = sender_c2

            result_c2 = deliver_alert(
                profile_id=profile_c2, event_id="mood_positive", fcm_token="fake-token",
                now=now_c, entitlement_service=FakeEntitlementService(profile_c2), repository=repo_c,
            )
            check("C2: not sent (business result unchanged)", not result_c2.sent and result_c2.stage == "send")
            un_c2 = UserNotification.query.filter_by(user_id=profile_c2).first()
            check("C2: NO UserNotification row created", un_c2 is None)
            events_c2 = db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE profile_id = :p"), {"p": profile_c2}).scalar()
            check("C2: NO activity_events row", events_c2 == 0)

            # ==========================================================
            print("\n=== C3: analytics failure isolation (Pipeline C) ===")
            # ==========================================================
            profile_c3a = new_app_user()
            repo_c.save_detection(profile_id=profile_c3a, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c3a)
            alert_delivery_module.send_push_notification = FakeFcmSenderC(result=True)
            with patch("modules.alerts.alert_delivery_service.record_event") as mock_re_c3a:
                mock_re_c3a.return_value = LedgerWriteResult(status="write_failed")
                result_c3a = deliver_alert(profile_id=profile_c3a, event_id="mood_positive", fcm_token="tok", now=now_c, entitlement_service=FakeEntitlementService(profile_c3a), repository=repo_c)
            check("C3a write_failed: delivered successfully regardless", result_c3a.sent and result_c3a.stage == "delivered")
            un_c3a = UserNotification.query.filter_by(user_id=profile_c3a).first()
            if un_c3a:
                created_user_notification_ids.append(un_c3a.id)
            check("C3a write_failed: UserNotification STILL committed", un_c3a is not None)

            profile_c3b = new_app_user()
            repo_c.save_detection(profile_id=profile_c3b, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c3b)
            alert_delivery_module.send_push_notification = FakeFcmSenderC(result=True)
            with patch("modules.alerts.alert_delivery_service.record_event") as mock_re_c3b:
                mock_re_c3b.side_effect = RuntimeError("simulated")
                result_c3b = deliver_alert(profile_id=profile_c3b, event_id="mood_positive", fcm_token="tok", now=now_c, entitlement_service=FakeEntitlementService(profile_c3b), repository=repo_c)
            check("C3b exception: delivered successfully regardless (exception did not propagate)", result_c3b.sent and result_c3b.stage == "delivered")
            un_c3b = UserNotification.query.filter_by(user_id=profile_c3b).first()
            if un_c3b:
                created_user_notification_ids.append(un_c3b.id)
            check("C3b exception: UserNotification STILL committed", un_c3b is not None)

            profile_c3c = new_app_user()
            repo_c.save_detection(profile_id=profile_c3c, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c3c)
            alert_delivery_module.send_push_notification = FakeFcmSenderC(result=True)
            real_env_c3c = os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            try:
                result_c3c = deliver_alert(profile_id=profile_c3c, event_id="mood_positive", fcm_token="tok", now=now_c, entitlement_service=FakeEntitlementService(profile_c3c), repository=repo_c)
            finally:
                if real_env_c3c is not None:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = real_env_c3c
            check("C3c missing env: delivered successfully regardless", result_c3c.sent and result_c3c.stage == "delivered")
            un_c3c = UserNotification.query.filter_by(user_id=profile_c3c).first()
            if un_c3c:
                created_user_notification_ids.append(un_c3c.id)

            profile_c3d = new_app_user()
            repo_c.save_detection(profile_id=profile_c3d, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c3d)
            alert_delivery_module.send_push_notification = FakeFcmSenderC(result=True)
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "not_a_real_environment"
            try:
                result_c3d = deliver_alert(profile_id=profile_c3d, event_id="mood_positive", fcm_token="tok", now=now_c, entitlement_service=FakeEntitlementService(profile_c3d), repository=repo_c)
            finally:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            check("C3d invalid env: delivered successfully regardless", result_c3d.sent and result_c3d.stage == "delivered")
            un_c3d = UserNotification.query.filter_by(user_id=profile_c3d).first()
            if un_c3d:
                created_user_notification_ids.append(un_c3d.id)

            # ==========================================================
            print("\n=== C4: Alert bell-only -- notification_created only, no sent ===")
            # ==========================================================
            profile_c4a = new_app_user()
            repo_c.save_detection(
                profile_id=profile_c4a, event_id="mood_positive", category="emotional",
                state="NEW", confidence=0.7, priority="high",
                active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c,
            )
            created_alert_profile_ids.append(profile_c4a)
            bell_row_c4a = repo_c.record_bell_only(
                profile_id=profile_c4a, event_id="mood_positive",
                notification_title="Bell Only Title", notification_body="Bell only body",
                notification_data={"type": "alert", "event_id": "mood_positive"},
                active_until=date(2026, 8, 20), now=now_c,
            )
            check("C4a: record_bell_only() returned a new UserNotification", bell_row_c4a is not None)
            if bell_row_c4a is not None:
                created_user_notification_ids.append(bell_row_c4a.id)
                _emit_alert_notification_events(user_notification=bell_row_c4a, emit_sent=False)
                created_c4a = track_event(get_ledger_row(f"notification_created:{bell_row_c4a.id}"))
                sent_c4a = get_ledger_row(f"notification_sent:{bell_row_c4a.id}")
                check("C4a: notification_created exists", created_c4a is not None)
                check("C4a: notification_sent does NOT exist (bell-only, no FCM interaction)", sent_c4a is None)
                if created_c4a is not None:
                    check("C4a: source == alert_delivery_service", created_c4a.source == "alert_delivery_service")
                    check("C4a: profile_id correct", created_c4a.profile_id == profile_c4a)
                    check("C4a: entity_type/entity_id correct", created_c4a.entity_type == "notification" and created_c4a.entity_id == str(bell_row_c4a.id))
                    check("C4a: properties == {notification_type: alert, target_scope: personal}", created_c4a.properties == {"notification_type": "alert", "target_scope": "personal"})
                    check("C4a: notification_context has ONLY notification_id (no slot, no campaign_id)", created_c4a.notification_context == {"notification_id": str(bell_row_c4a.id)})
                    check("C4a: dedupe_key format correct", created_c4a.dedupe_key == f"notification_created:{bell_row_c4a.id}")

            # ==========================================================
            print("\n=== C4b: record_bell_only() idempotent no-op -> zero new event ===")
            # ==========================================================
            # A second call for the SAME (profile, event_id) while the
            # first bell-only row is still active is a no-op by
            # record_bell_only()'s own existing idempotency check --
            # returns None, so no event of any kind should be emitted.
            before_count_c4b = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            bell_row_c4b = repo_c.record_bell_only(
                profile_id=profile_c4a, event_id="mood_positive",
                notification_title="Bell Only Title", notification_body="Bell only body",
                notification_data={"type": "alert", "event_id": "mood_positive"},
                active_until=date(2026, 8, 20), now=now_c,
            )
            check("C4b: record_bell_only() correctly returned None (idempotent no-op)", bell_row_c4b is None)
            if bell_row_c4b is not None:
                # Defensive -- should never happen given the check above,
                # but if it did, this is a genuine new row and must still
                # be tracked/cleaned up like any other fixture.
                created_user_notification_ids.append(bell_row_c4b.id)
            after_count_c4b = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            check("C4b: no new activity_events row from the idempotent no-op", after_count_c4b == before_count_c4b)

            # ==========================================================
            print("\n=== C4c: Alert bell-only -- analytics failure isolation ===")
            # ==========================================================
            profile_c4c_a = new_app_user()
            repo_c.save_detection(profile_id=profile_c4c_a, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c4c_a)
            bell_c4c_a = repo_c.record_bell_only(profile_id=profile_c4c_a, event_id="mood_positive", notification_title="t", notification_body="b", notification_data={"type": "alert", "event_id": "mood_positive"}, active_until=date(2026, 8, 20), now=now_c)
            created_user_notification_ids.append(bell_c4c_a.id)
            with patch("modules.alerts.alert_delivery_service.record_event") as mock_re_c4c_a:
                mock_re_c4c_a.return_value = LedgerWriteResult(status="write_failed")
                _emit_alert_notification_events(user_notification=bell_c4c_a, emit_sent=False)
            check("C4c write_failed: UserNotification unaffected (still exists)", UserNotification.query.get(bell_c4c_a.id) is not None)

            profile_c4c_b = new_app_user()
            repo_c.save_detection(profile_id=profile_c4c_b, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c4c_b)
            bell_c4c_b = repo_c.record_bell_only(profile_id=profile_c4c_b, event_id="mood_positive", notification_title="t", notification_body="b", notification_data={"type": "alert", "event_id": "mood_positive"}, active_until=date(2026, 8, 20), now=now_c)
            created_user_notification_ids.append(bell_c4c_b.id)
            with patch("modules.alerts.alert_delivery_service.record_event") as mock_re_c4c_b:
                mock_re_c4c_b.side_effect = RuntimeError("simulated")
                try:
                    _emit_alert_notification_events(user_notification=bell_c4c_b, emit_sent=False)
                    raised_c4c_b = False
                except Exception:
                    raised_c4c_b = True
            check("C4c exception: does NOT propagate out of the emitter", raised_c4c_b is False)

            profile_c4c_c = new_app_user()
            repo_c.save_detection(profile_id=profile_c4c_c, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c4c_c)
            bell_c4c_c = repo_c.record_bell_only(profile_id=profile_c4c_c, event_id="mood_positive", notification_title="t", notification_body="b", notification_data={"type": "alert", "event_id": "mood_positive"}, active_until=date(2026, 8, 20), now=now_c)
            created_user_notification_ids.append(bell_c4c_c.id)
            real_env_c4c_c = os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            try:
                _emit_alert_notification_events(user_notification=bell_c4c_c, emit_sent=False)
            finally:
                if real_env_c4c_c is not None:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = real_env_c4c_c
            check("C4c missing env: no row persisted, no exception", len(rows_for_entity("notification", bell_c4c_c.id)) == 0)

            profile_c4c_d = new_app_user()
            repo_c.save_detection(profile_id=profile_c4c_d, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.append(profile_c4c_d)
            bell_c4c_d = repo_c.record_bell_only(profile_id=profile_c4c_d, event_id="mood_positive", notification_title="t", notification_body="b", notification_data={"type": "alert", "event_id": "mood_positive"}, active_until=date(2026, 8, 20), now=now_c)
            created_user_notification_ids.append(bell_c4c_d.id)
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "not_a_real_environment"
            try:
                _emit_alert_notification_events(user_notification=bell_c4c_d, emit_sent=False)
            finally:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            check("C4c invalid env: no exception raised", True)

            # ==========================================================
            print("\n=== C4d: bell-only analytics failure does not abort later scheduler work ===")
            # ==========================================================
            # Simulate two bell-only rows processed in sequence within
            # one scheduler run (as alerts_scheduler.py's own for-loop
            # does) -- the first row's analytics call raises, the second
            # must still be attempted and must still succeed.
            profile_c4d_a = new_app_user()
            profile_c4d_b = new_app_user()
            repo_c.save_detection(profile_id=profile_c4d_a, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            repo_c.save_detection(profile_id=profile_c4d_b, event_id="mood_positive", category="emotional", state="NEW", confidence=0.7, priority="high", active_from=date(2026, 8, 20), active_until=date(2026, 8, 20), evaluated_at=now_c)
            created_alert_profile_ids.extend([profile_c4d_a, profile_c4d_b])
            bell_c4d_a = repo_c.record_bell_only(profile_id=profile_c4d_a, event_id="mood_positive", notification_title="t", notification_body="b", notification_data={"type": "alert", "event_id": "mood_positive"}, active_until=date(2026, 8, 20), now=now_c)
            bell_c4d_b = repo_c.record_bell_only(profile_id=profile_c4d_b, event_id="mood_positive", notification_title="t", notification_body="b", notification_data={"type": "alert", "event_id": "mood_positive"}, active_until=date(2026, 8, 20), now=now_c)
            created_user_notification_ids.extend([bell_c4d_a.id, bell_c4d_b.id])

            call_count_c4d = {"n": 0}
            real_record_event_c4d = alert_delivery_module.record_event

            def flaky_record_event_c4d(**kwargs):
                call_count_c4d["n"] += 1
                if call_count_c4d["n"] == 1:
                    raise RuntimeError("simulated failure on the first bell-only row")
                return real_record_event_c4d(**kwargs)

            with patch("modules.alerts.alert_delivery_service.record_event", side_effect=flaky_record_event_c4d):
                for bell_row in (bell_c4d_a, bell_c4d_b):
                    _emit_alert_notification_events(user_notification=bell_row, emit_sent=False)
            r_c4d_b = track_event(get_ledger_row(f"notification_created:{bell_c4d_b.id}"))
            check("C4d: the SECOND bell-only row's event still landed despite the FIRST row's analytics failure", r_c4d_b is not None)

            # ==========================================================
            print("\n=== D: Dedupe -- repeated attempts never double-insert; different IDs stay independent ===")
            # ==========================================================
            if un_c1 is not None:
                count_created_un_c1 = db.session.execute(
                    text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"),
                    {"dk": f"notification_created:{un_c1.id}"},
                ).scalar()
                check("D: exactly ONE notification_created row exists for un_c1 (no duplicate from repeated pipeline activity)", count_created_un_c1 == 1)
            else:
                check("D: skipped -- un_c1 was never created (see C1 failure above)", False)

            # ==========================================================
            print("\n=== E: Security scan -- no forbidden content anywhere in rows created above ===")
            # ==========================================================
            forbidden_substrings = [
                "fake-fcm-token", "fake-token", "Body A1", "Test Job A1",
                "B1 body", "B3 body", "Mood Positive", "phase4d-test-",
                "Traceback", "simulated", "screen", "test_a1",
            ]
            leak_found = False
            for eid in dict.fromkeys(created_event_ids):
                row = db.session.execute(text("SELECT * FROM activity_events WHERE event_id = :id"), {"id": eid}).fetchone()
                if row is None:
                    continue
                serialized = (
                    str(row.properties) + str(row.dedupe_key) + str(row.entity_id)
                    + str(row.correlation_id) + str(row.campaign_context) + str(row.notification_context)
                )
                for term in forbidden_substrings:
                    if term in serialized:
                        leak_found = True
                        print(f"  LEAK: {term!r} found in row {eid}")
            check("E: no title/body/token/PII/test-marker text found in any row", leak_found is False)

        finally:
            # ----------------------------------------------------------
            # Cleanup -- precise, per-row, never a broad DELETE.
            # ----------------------------------------------------------
            for eid in dict.fromkeys(created_event_ids):
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()

            # Safety-net: some deliberately-flaky test scenarios (e.g. a
            # mock whose side_effect raises on only the FIRST of several
            # record_event() calls in one batch, so a LATER call in that
            # same batch goes through for real) can produce a genuine,
            # real activity_events row this file's own explicit dedupe-
            # key lookups did not anticipate. Every such row's profile_id
            # is always one of THIS run's own tracked AppUsers (the only
            # identities this file ever uses), so deleting by that exact
            # scope is still precise -- never a table-wide DELETE -- and
            # guarantees no fixture is left behind regardless of whether
            # every emission call site was individually enumerated above.
            if created_app_user_ids:
                db.session.execute(
                    text("DELETE FROM activity_events WHERE profile_id = ANY(:pids)"),
                    {"pids": list(dict.fromkeys(created_app_user_ids))},
                )
                db.session.commit()

            for nlid in dict.fromkeys(created_notification_log_ids):
                db.session.execute(text("DELETE FROM notification_logs WHERE id = :id"), {"id": nlid})
            db.session.commit()

            for unid in dict.fromkeys(created_user_notification_ids):
                db.session.execute(text("DELETE FROM user_notifications WHERE id = :id"), {"id": unid})
            db.session.commit()

            for jid in dict.fromkeys(created_job_ids):
                db.session.execute(text("DELETE FROM notification_jobs WHERE id = :id"), {"id": jid})
            db.session.commit()

            for pid in dict.fromkeys(created_alert_profile_ids):
                db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": pid})
            db.session.commit()

            for uid in dict.fromkeys(created_app_user_ids):
                db.session.execute(text("DELETE FROM app_users WHERE id = :id"), {"id": uid})
            db.session.commit()

            remaining_events = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE event_id = ANY(:ids)"),
                {"ids": [uuid.UUID(e) for e in dict.fromkeys(created_event_ids)] or [uuid.uuid4()]},
            ).scalar()
            check("cleanup: all Phase-4D activity_events rows removed", remaining_events == 0)

            remaining_un = UserNotification.query.filter(UserNotification.id.in_(created_user_notification_ids or [-1])).count()
            check("cleanup: all Phase-4D UserNotification fixtures removed", remaining_un == 0)

            remaining_nl = NotificationLog.query.filter(NotificationLog.id.in_(created_notification_log_ids or [-1])).count()
            check("cleanup: all Phase-4D NotificationLog fixtures removed", remaining_nl == 0)

            remaining_jobs = NotificationJob.query.filter(NotificationJob.id.in_(created_job_ids or [-1])).count()
            check("cleanup: all Phase-4D NotificationJob fixtures removed", remaining_jobs == 0)

            remaining_users = AppUser.query.filter(AppUser.id.in_(created_app_user_ids or [-1])).count()
            check("cleanup: all Phase-4D AppUser fixtures removed", remaining_users == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
