"""
test_alerts_delivery_atomicity.py
--------------------------------------
Local-only entry point for Phase 5.1 (delivery atomicity hardening):
  - modules/alerts/persistence_repository.py::finalize_delivery()
  - modules/alerts/alert_delivery_service.py's use of it (replacing
    Phase 5's original mark_delivered() + separate Bell-insert commit)

Uses the LOCAL scratch Postgres DB ONLY, exactly like every other
test_alerts_*.py script. `send_push_notification` is monkeypatched --
no real FCM call is ever made.
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
from sqlalchemy import text  # noqa: E402

from modules.models_ai_reports import AI_REPORT_SEGMENTS  # noqa: E402
from modules.entitlement.entitlement_models import EntitlementSnapshot, TrialStatus, SubscriptionStatus  # noqa: E402
from modules.alerts.persistence_repository import AlertPersistenceRepository, AlertPersistenceError  # noqa: E402
import modules.alerts.alert_delivery_service as delivery_module  # noqa: E402
from modules.alerts.alert_delivery_service import deliver_alert  # noqa: E402
from notifications.notification_models import UserNotification  # noqa: E402

PROFILE = 9501
ALL_SEGMENTS = list(AI_REPORT_SEGMENTS)

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


class FakeEntitlementService:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get_current_entitlement(self, profile_id):
        return self._snapshot


def entitled_snapshot():
    return EntitlementSnapshot(
        profile_id=1, status="TRIAL", plan=None, selected_segment=None,
        trial=TrialStatus(is_active=True),
        subscription=SubscriptionStatus(is_active=False, status="PENDING"),
        accessible_segments=ALL_SEGMENTS,
    )


class FakeFcmSender:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def __call__(self, *, token, title, body, data=None, android_tag=None):
        self.calls.append({"token": token, "title": title, "body": body, "data": data})
        return self.result


def reset(repo):
    db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": PROFILE})
    db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": PROFILE})
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": PROFILE})
        db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": PROFILE})
        db.session.commit()
        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                "VALUES (:id, 'IST', 'free', 0, 'fake-token')"
            ), {"id": PROFILE})
            conn.commit()

        repo = AlertPersistenceRepository()
        entitled = FakeEntitlementService(entitled_snapshot())
        now = datetime(2026, 8, 14, 12, 0, 0)

        # ==============================================================
        print("=== Test 1: successful FCM + successful DB finalization -> both committed ===")
        # ==============================================================
        reset(repo)
        repo.save_detection(
            profile_id=PROFILE, event_id="mood_positive", category="emotional",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14), evaluated_at=now,
        )
        sender = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender

        result = deliver_alert(profile_id=PROFILE, event_id="mood_positive", fcm_token="fake-token", now=now, entitlement_service=entitled, repository=repo)
        check("delivered successfully", result.sent and result.stage == "delivered")
        row = repo.read(profile_id=PROFILE, event_id="mood_positive")
        check("last_delivered_at committed", row.last_delivered_at == now)
        bell = UserNotification.query.filter_by(user_id=PROFILE).all()
        check("exactly one Bell row committed", len(bell) == 1)
        check("Bell row content matches", bell[0].title == "Mood Positive")

        # ==============================================================
        print("\n=== Test 2: Bell insert failure -> timestamp update ALSO rolled back ===")
        # ==============================================================
        reset(repo)
        repo.save_detection(
            profile_id=PROFILE, event_id="mood_low", category="emotional",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14), evaluated_at=now,
        )
        # Force the Bell insert to violate UserNotification.title's
        # NOT NULL constraint -- a real, deterministic DB-level
        # failure on the Bell side specifically.
        raised = False
        try:
            repo.finalize_delivery(
                profile_id=PROFILE, event_id="mood_low",
                notification_title=None,  # violates NOT NULL
                notification_body="body", notification_data={"type": "alert", "event_id": "mood_low"},
                delivered_at=now,
            )
        except AlertPersistenceError:
            raised = True
        check("finalize_delivery() raises AlertPersistenceError on Bell-side failure", raised)

        row_after = repo.read(profile_id=PROFILE, event_id="mood_low")
        check("last_delivered_at rolled back to None (NOT committed without the Bell row)", row_after.last_delivered_at is None)
        bell_after = UserNotification.query.filter_by(user_id=PROFILE).all()
        check("no Bell row was left behind either", len(bell_after) == 0)

        # ==============================================================
        print("\n=== Test 3: timestamp update failure -> Bell insert ALSO rolled back ===")
        # ==============================================================
        reset(repo)
        repo.save_detection(
            profile_id=PROFILE, event_id="energy_high", category="vitality",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14), evaluated_at=now,
        )
        # Force the AlertMicroEvent-side write to fail: an invalid
        # (non-date-coercible) delivered_at value fails at flush/commit
        # time on the psycopg2/Postgres side (DataError), while the
        # Bell insert's own values are otherwise perfectly valid --
        # proving the SAME shared commit/rollback governs both sides,
        # not just the Bell side (Test 2).
        raised2 = False
        try:
            repo.finalize_delivery(
                profile_id=PROFILE, event_id="energy_high",
                notification_title="Energy High", notification_body="body",
                notification_data={"type": "alert", "event_id": "energy_high"},
                delivered_at="not-a-real-datetime",  # invalid type for a DateTime column
            )
        except AlertPersistenceError:
            raised2 = True
        except Exception as exc:
            # If SQLAlchemy/psycopg2 raises a lower-level error type
            # that isn't caught and re-wrapped, that itself would be a
            # real defect -- fail the check explicitly rather than
            # silently accepting a different exception type.
            print(f"  (unexpected raw exception type: {type(exc).__name__}: {exc})")
        check("finalize_delivery() raises AlertPersistenceError on AlertMicroEvent-side failure", raised2)

        db.session.rollback()  # defensive -- ensure session is clean before re-querying
        row_after2 = repo.read(profile_id=PROFILE, event_id="energy_high")
        check("last_delivered_at rolled back to None", row_after2.last_delivered_at is None)
        bell_after2 = UserNotification.query.filter_by(user_id=PROFILE).all()
        check("Bell insert was ALSO rolled back (not left as an orphan row)", len(bell_after2) == 0)

        # ==============================================================
        print("\n=== Test 4: no duplicate Bell row from one successful finalization ===")
        # ==============================================================
        reset(repo)
        repo.save_detection(
            profile_id=PROFILE, event_id="learning_focus", category="learning",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14), evaluated_at=now,
        )
        sender2 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender2
        result4 = deliver_alert(profile_id=PROFILE, event_id="learning_focus", fcm_token="fake-token", now=now, entitlement_service=entitled, repository=repo)
        check("delivered", result4.sent and result4.stage == "delivered")
        bell4 = UserNotification.query.filter_by(user_id=PROFILE).all()
        check("exactly ONE Bell row (not duplicated by the atomic path)", len(bell4) == 1)

        # ==============================================================
        print("\n=== Test 5: entitlement/cooldown/FCM failure behavior unchanged ===")
        # ==============================================================
        # Cooldown: repeated attempt right after Test 1's successful
        # delivery of mood_positive.
        sender3 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender3
        result5 = deliver_alert(profile_id=PROFILE, event_id="learning_focus", fcm_token="fake-token", now=now + timedelta(minutes=1), entitlement_service=entitled, repository=repo)
        check("repeated attempt inside cooldown still blocked (stage=eligibility)", not result5.sent and result5.stage == "eligibility")
        check("no FCM call for the blocked repeat", len(sender3.calls) == 0)

        # FCM failure: still leaves last_delivered_at untouched.
        repo.save_detection(
            profile_id=PROFILE, event_id="opportunity_window", category="timing",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14), evaluated_at=now,
        )
        failing_sender = FakeFcmSender(result=False)
        delivery_module.send_push_notification = failing_sender
        result6 = deliver_alert(profile_id=PROFILE, event_id="opportunity_window", fcm_token="fake-token", now=now, entitlement_service=entitled, repository=repo)
        check("FCM failure -> not sent, stage=send (unchanged from Phase 5)", not result6.sent and result6.stage == "send")
        row6 = repo.read(profile_id=PROFILE, event_id="opportunity_window")
        check("last_delivered_at still untouched after FCM failure", row6.last_delivered_at is None)

        # Entitlement failure: still blocks before touching persistence.
        unentitled_snapshot = EntitlementSnapshot(
            profile_id=1, status="PENDING", plan=None, selected_segment=None,
            trial=TrialStatus(is_active=False),
            subscription=SubscriptionStatus(is_active=False, status="PENDING"),
            accessible_segments=[],
        )
        unentitled = FakeEntitlementService(unentitled_snapshot)
        sender4 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender4
        result7 = deliver_alert(profile_id=PROFILE, event_id="opportunity_window", fcm_token="fake-token", now=now, entitlement_service=unentitled, repository=repo)
        check("entitlement failure -> not sent, stage=entitlement (unchanged)", not result7.sent and result7.stage == "entitlement")
        check("no FCM call for unentitled profile", len(sender4.calls) == 0)

        reset(repo)
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": PROFILE})
        db.session.commit()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
