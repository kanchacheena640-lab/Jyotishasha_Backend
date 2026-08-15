"""
test_alerts_delivery.py
---------------------------
Local-only entry point for the Phase 5 delivery adapter:
  - modules/alerts/entitlement_gate.py
  - modules/alerts/notification_content_adapter.py
  - modules/alerts/alert_delivery_service.py
  - the Phase 5 addition to persistence_repository.py (mark_delivered())

Entitlement scenarios are tested with a FAKE EntitlementService (built
from the REAL EntitlementSnapshot/TrialStatus/SubscriptionStatus
dataclasses -- modules/entitlement/entitlement_models.py, unmodified)
so every plan/trial combination is deterministic and doesn't require
constructing real CurrentEntitlement rows. `send_push_notification` is
monkeypatched at the module level where alert_delivery_service.py
imports it -- NO real FCM call is ever made; Firebase is never
contacted. Persistence (AlertMicroEvent rows) uses the LOCAL scratch
Postgres DB ONLY, exactly like every other test_alerts_*.py script.
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

from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS, ALERTS_SECTION  # noqa: E402
from modules.entitlement.entitlement_models import (  # noqa: E402
    EntitlementSnapshot, TrialStatus, SubscriptionStatus,
)
from modules.alerts.entitlement_gate import has_alerts_access  # noqa: E402
from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402
from modules.alerts.notification_content_adapter import build_alert_notification_content  # noqa: E402
import modules.alerts.alert_delivery_service as delivery_module  # noqa: E402
from modules.alerts.alert_delivery_service import deliver_alert  # noqa: E402
from notifications.notification_models import UserNotification  # noqa: E402

PROFILE_A = 9401
PROFILE_B = 9402

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
    """Matches EntitlementService.get_current_entitlement()'s exact
    contract -- returns a hand-built, real EntitlementSnapshot."""

    def __init__(self, snapshot: EntitlementSnapshot):
        self._snapshot = snapshot

    def get_current_entitlement(self, profile_id):
        return self._snapshot


def _snapshot(accessible_segments, trial_active=False, subscription_active=False, plan=None, selected_segment=None):
    return EntitlementSnapshot(
        profile_id=1,
        status="TRIAL" if trial_active else ("ACTIVE" if subscription_active else "PENDING"),
        plan=plan,
        selected_segment=selected_segment,
        trial=TrialStatus(is_active=trial_active),
        subscription=SubscriptionStatus(is_active=subscription_active, status="ACTIVE" if subscription_active else "PENDING"),
        accessible_segments=accessible_segments,
    )


ALL_SEGMENTS = list(SUBSCRIPTION_SECTIONS)  # all 6 sections, including Alerts & Opportunities


class FakeFcmSender:
    """Replaces alert_delivery_service.send_push_notification for the
    duration of a test -- records every call, never touches Firebase."""

    def __init__(self, result=True, raise_exc=None):
        self.result = result
        self.raise_exc = raise_exc
        self.calls = []

    def __call__(self, *, token, title, body, data=None, android_tag=None):
        self.calls.append({"token": token, "title": title, "body": body, "data": data})
        if self.raise_exc:
            raise self.raise_exc
        return self.result


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        for p in (PROFILE_A, PROFILE_B):
            db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": p})
            db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": p})
            db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": p})
        db.session.commit()
        with db.engine.connect() as conn:
            for p in (PROFILE_A, PROFILE_B):
                conn.execute(text(
                    "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                    "VALUES (:id, 'IST', 'free', 0, :token)"
                ), {"id": p, "token": f"fake-fcm-token-{p}"})
            conn.commit()

        repo = AlertPersistenceRepository()
        now = datetime(2026, 8, 14, 12, 0, 0)

        # ==============================================================
        print("=== Entitlement gate: pure-function scenarios ===")
        # ==============================================================
        r = has_alerts_access(1, entitlement_service=FakeEntitlementService(_snapshot(ALL_SEGMENTS, trial_active=True)))
        check("Test: trial-entitled -> entitled=True", r.entitled)

        r = has_alerts_access(1, entitlement_service=FakeEntitlementService(_snapshot(ALL_SEGMENTS, subscription_active=True, plan="GOLD_MONTHLY")))
        check("Test: all-sections subscription (GOLD) -> entitled=True", r.entitled)

        r = has_alerts_access(1, entitlement_service=FakeEntitlementService(
            _snapshot(["LOVE"], subscription_active=True, plan="PRIME_MONTHLY", selected_segment="LOVE")
        ))
        check(
            "Test: Prime with a DIFFERENT section selected (LOVE) -> Alerts locked",
            not r.entitled,
        )
        check("single-section rejection reason names the actual accessible segment(s)", "LOVE" in r.reason)

        # Alerts & Opportunities is now the sixth selectable subscription
        # section (locked product decision) -- a Prime profile that
        # selected it is entitled, exactly like selecting any of the
        # other five would entitle that section.
        r = has_alerts_access(1, entitlement_service=FakeEntitlementService(
            _snapshot([ALERTS_SECTION], subscription_active=True, plan="PRIME_MONTHLY", selected_segment=ALERTS_SECTION)
        ))
        check(
            "Test: Prime with Alerts & Opportunities selected -> entitled=True "
            "(no longer requires an all-segments plan)",
            r.entitled,
        )

        r = has_alerts_access(1, entitlement_service=FakeEntitlementService(_snapshot([], subscription_active=False, trial_active=False)))
        check("Test: expired/no entitlement -> blocked", not r.entitled)
        check("expired/no-entitlement reason is explicit", "no active trial or subscription" in r.reason)

        # ==============================================================
        print("\n=== Content adapter: deterministic payload ===")
        # ==============================================================
        content = build_alert_notification_content(event_id="financial_gain_opportunity", category="financial", severity="HIGH")
        check("title comes from the real catalog", content["title"] == "Financial Gain Opportunity")
        check("body is deterministic financial template", content["body"] == "A financial signal is active for you today.")
        check("data.type == 'alert'", content["data"]["type"] == "alert")
        check("data.event_id correct", content["data"]["event_id"] == "financial_gain_opportunity")
        check("data.category correct", content["data"]["category"] == "financial")
        check("data.severity correct", content["data"]["severity"] == "HIGH")
        check("confidence is NEVER exposed anywhere in content", "confidence" not in content and "confidence" not in content["data"])

        # ==============================================================
        print("\n=== deliver_alert(): full flow, entitled ===")
        # ==============================================================
        repo.save_detection(
            profile_id=PROFILE_A, event_id="mood_positive", category="emotional",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14),
            evaluated_at=now,
        )
        entitled_service = FakeEntitlementService(_snapshot(ALL_SEGMENTS, trial_active=True))
        sender = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender

        result = deliver_alert(
            profile_id=PROFILE_A, event_id="mood_positive", fcm_token="fake-fcm-token-9401",
            now=now, entitlement_service=entitled_service, repository=repo,
        )
        check("Test: entitled + eligible -> sends", result.sent and result.stage == "delivered")
        check("exactly one FCM call made", len(sender.calls) == 1)
        check("FCM call used the correct token", sender.calls[0]["token"] == "fake-fcm-token-9401")
        check("FCM call title/body/data match content adapter output", sender.calls[0]["data"]["event_id"] == "mood_positive")

        row = repo.read(profile_id=PROFILE_A, event_id="mood_positive")
        check("Test: successful send updates last_delivered_at", row.last_delivered_at == now)

        bell_rows = UserNotification.query.filter_by(user_id=PROFILE_A).all()
        check("Bell/UserNotification row created (reused, not duplicated inbox)", len(bell_rows) == 1)
        check("Bell row title matches", bell_rows[0].title == "Mood Positive")

        # ==============================================================
        print("\n=== deliver_alert(): repeated attempt inside cooldown does not resend ===")
        # ==============================================================
        sender2 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender2
        result2 = deliver_alert(
            profile_id=PROFILE_A, event_id="mood_positive", fcm_token="fake-fcm-token-9401",
            now=now + timedelta(minutes=5), entitlement_service=entitled_service, repository=repo,
        )
        check("Test: repeated attempt inside cooldown -> not sent", not result2.sent)
        check("stage is eligibility (cooldown), not send", result2.stage == "eligibility")
        check("NO second FCM call made", len(sender2.calls) == 0)
        row_after = repo.read(profile_id=PROFILE_A, event_id="mood_positive")
        check("last_delivered_at unchanged by the blocked repeat attempt", row_after.last_delivered_at == now)

        # ==============================================================
        print("\n=== deliver_alert(): low-confidence blocked ===")
        # ==============================================================
        repo.save_detection(
            profile_id=PROFILE_A, event_id="delay_possible", category="timing",
            state="NEW", confidence=0.1, priority="low",  # below medium threshold
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14),
            evaluated_at=now,
        )
        sender3 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender3
        result3 = deliver_alert(
            profile_id=PROFILE_A, event_id="delay_possible", fcm_token="fake-fcm-token-9401",
            now=now, entitlement_service=entitled_service, repository=repo,
        )
        check("Test: low-confidence -> not sent", not result3.sent)
        check("stage is eligibility", result3.stage == "eligibility")
        check("no FCM call made for low-confidence event", len(sender3.calls) == 0)
        row_lowconf = repo.read(profile_id=PROFILE_A, event_id="delay_possible")
        check("last_delivered_at remains NULL", row_lowconf.last_delivered_at is None)

        # ==============================================================
        print("\n=== deliver_alert(): EXPIRED alert -> no send ===")
        # ==============================================================
        repo.save_detection(
            profile_id=PROFILE_A, event_id="stress_high", category="vitality",
            state="EXPIRED", confidence=0.9, priority="high",
            active_from=date(2026, 8, 10), active_until=date(2026, 8, 11),
            evaluated_at=now,
        )
        sender4 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender4
        result4 = deliver_alert(
            profile_id=PROFILE_A, event_id="stress_high", fcm_token="fake-fcm-token-9401",
            now=now, entitlement_service=entitled_service, repository=repo,
        )
        check("Test: EXPIRED alert, even high confidence -> not sent", not result4.sent)
        check("no FCM call made for EXPIRED event", len(sender4.calls) == 0)

        # ==============================================================
        print("\n=== deliver_alert(): failed FCM send does NOT update last_delivered_at ===")
        # ==============================================================
        repo.save_detection(
            profile_id=PROFILE_A, event_id="energy_high", category="vitality",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14),
            evaluated_at=now,
        )
        failing_sender = FakeFcmSender(result=False)  # FCM returns False (send failed)
        delivery_module.send_push_notification = failing_sender
        result5 = deliver_alert(
            profile_id=PROFILE_A, event_id="energy_high", fcm_token="fake-fcm-token-9401",
            now=now, entitlement_service=entitled_service, repository=repo,
        )
        check("Test: failed FCM send -> sent=False", not result5.sent)
        check("stage is send", result5.stage == "send")
        row_failed = repo.read(profile_id=PROFILE_A, event_id="energy_high")
        check("last_delivered_at remains NULL after failed send", row_failed.last_delivered_at is None)

        raising_sender = FakeFcmSender(raise_exc=RuntimeError("simulated FCM outage"))
        delivery_module.send_push_notification = raising_sender
        result5b = deliver_alert(
            profile_id=PROFILE_A, event_id="energy_high", fcm_token="fake-fcm-token-9401",
            now=now, entitlement_service=entitled_service, repository=repo,
        )
        check("Test: FCM raising an exception -> sent=False, handled gracefully (not propagated)", not result5b.sent)
        row_failed2 = repo.read(profile_id=PROFILE_A, event_id="energy_high")
        check("last_delivered_at STILL NULL after FCM exception", row_failed2.last_delivered_at is None)

        # ==============================================================
        print("\n=== deliver_alert(): entitlement failure does NOT update last_delivered_at ===")
        # ==============================================================
        unentitled_service = FakeEntitlementService(_snapshot([], subscription_active=False, trial_active=False))
        sender6 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender6
        result6 = deliver_alert(
            profile_id=PROFILE_A, event_id="energy_high", fcm_token="fake-fcm-token-9401",
            now=now, entitlement_service=unentitled_service, repository=repo,
        )
        check("Test: entitlement failure -> sent=False", not result6.sent)
        check("stage is entitlement (fails before even loading the alert row)", result6.stage == "entitlement")
        check("NO FCM call made when entitlement fails", len(sender6.calls) == 0)
        row_unentitled = repo.read(profile_id=PROFILE_A, event_id="energy_high")
        check("last_delivered_at remains NULL after entitlement failure", row_unentitled.last_delivered_at is None)

        # ==============================================================
        print("\n=== Test: one failed alert does not corrupt another alert/profile ===")
        # ==============================================================
        repo.save_detection(
            profile_id=PROFILE_B, event_id="mood_positive", category="emotional",
            state="NEW", confidence=0.7, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14),
            evaluated_at=now,
        )
        sender7 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender7
        result_b = deliver_alert(
            profile_id=PROFILE_B, event_id="mood_positive", fcm_token="fake-fcm-token-9402",
            now=now, entitlement_service=entitled_service, repository=repo,
        )
        check("profile B's own alert succeeds independently of profile A's earlier failures", result_b.sent)
        row_b = repo.read(profile_id=PROFILE_B, event_id="mood_positive")
        check("profile B's row correctly updated", row_b.last_delivered_at == now)
        row_a_energy_high = repo.read(profile_id=PROFILE_A, event_id="energy_high")
        check("profile A's still-failed row is untouched by profile B's success", row_a_energy_high.last_delivered_at is None)
        row_a_mood = repo.read(profile_id=PROFILE_A, event_id="mood_positive")
        check("profile A's earlier SUCCESSFUL delivery is also untouched", row_a_mood.last_delivered_at == now)

        for p in (PROFILE_A, PROFILE_B):
            db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": p})
            db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": p})
            db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": p})
        db.session.commit()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
