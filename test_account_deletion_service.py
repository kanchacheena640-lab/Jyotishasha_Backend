"""
test_account_deletion_service.py
----------------------------------
Local-only entry point for D1 (Backend Deletion Service) --
modules/auth/account_deletion_service.py.

Uses the LOCAL scratch Postgres DB ONLY, exactly like every other
test_*.py script in this repo. No production access. No Firebase/
Firestore call of any kind -- this file tests the DB layer only.
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

from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser, UserDashaTimeline  # noqa: E402
from modules.models_premium_subscription import CurrentEntitlement, SubscriptionEvent  # noqa: E402
from modules.models_subscription_purchase_mapping import SubscriptionPurchaseMapping  # noqa: E402
from modules.subscription.models import Subscription  # noqa: E402
from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.models_asknow import AskNowOrder  # noqa: E402
from modules.models_subscription import SubscriptionOrder  # noqa: E402
from modules.models_ai_reports import AIReport  # noqa: E402
from modules.alerts.persistence_models import AlertMicroEvent  # noqa: E402
from modules.models_daily_cache import DailyPersonalizedCache  # noqa: E402
from modules.models_free_daily import FreeDailyQuestion  # noqa: E402
from notifications.notification_models import NotificationLog, UserNotification  # noqa: E402

import modules.auth.account_deletion_service as svc  # noqa: E402
from modules.auth.account_deletion_service import (  # noqa: E402
    AccountDeletionError,
    delete_account_data,
    resolve_firebase_identity,
)

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


# ---------------------------------------------------------------------------
# Dedicated, clearly-out-of-range id space so this suite can never collide
# with any other test_*.py file's fixtures in the same local DB.
# ---------------------------------------------------------------------------
USER_IDS = list(range(981001, 981011))
PROFILE_IDS = [
    981101, 981102, 981103, 981104,  # scenario 1 (no financial), 2 (financial), 3a (multi), 3b (multi)
    981105,                          # scenario 6 (legacy System-A subscription)
    981106,                          # scenario 8 (rollback)
    981109,                          # scenario 9 (unrelated/control)
    981110, 981111,                  # scenario 10 (mixed, same firebase_uid)
]

FB1 = "test-fb-d1-no-financial"
FB2 = "test-fb-d1-with-financial"
FB3 = "test-fb-d1-multi-profile"
FB_ROLLBACK = "test-fb-d1-rollback"
FB_UNRELATED = "test-fb-d1-unrelated"
FB_MIXED = "test-fb-d1-mixed"


def cleanup():
    for model, col in [
        (UserDashaTimeline, "user_id"), (AlertMicroEvent, "profile_id"),
        (AIReport, "profile_id"), (UserNotification, "user_id"),
        (NotificationLog, "user_id"), (DailyPersonalizedCache, "profile_id"),
        (FreeDailyQuestion, "user_id"), (CurrentEntitlement, "profile_id"),
        (SubscriptionEvent, "profile_id"), (SubscriptionPurchaseMapping, "profile_id"),
        (ChatPack, "user_id"), (AskNowOrder, "user_id"), (SubscriptionOrder, "user_id"),
    ]:
        model.query.filter(getattr(model, col).in_(PROFILE_IDS)).delete(synchronize_session=False)
    Subscription.query.filter(Subscription.user_id.in_(USER_IDS)).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


def seed_personal_children(profile_id: int):
    """One row in EVERY personal-data child table, for completeness
    checking (Gate 4 test #4)."""
    db.session.add(UserDashaTimeline(
        user_id=profile_id, mahadasha="Jupiter", antardasha="Saturn",
        start_date=date(2026, 1, 1), end_date=date(2027, 1, 1),
    ))
    db.session.add(AlertMicroEvent(
        profile_id=profile_id, event_id="mood_positive", category="emotional",
        state="ACTIVE", priority="high", confidence=0.7,
        active_from=date.today(), active_until=date.today(),
    ))
    db.session.add(AIReport(profile_id=profile_id, segment="LOVE", report_type="DNA"))
    db.session.add(UserNotification(user_id=profile_id, title="Test", body="Test body"))
    db.session.add(NotificationLog(user_id=profile_id, event_id="evt-1", slot="morning"))
    db.session.add(DailyPersonalizedCache(
        user_id=profile_id, profile_id=profile_id, date=date.today(), planet="Moon",
        aspect_line_en="en", aspect_line_hi="hi", remedy_en="en", remedy_hi="hi",
    ))
    db.session.add(FreeDailyQuestion(user_id=profile_id, last_used_date=None))


def count_personal_children(profile_id: int) -> dict:
    return {
        "UserDashaTimeline": UserDashaTimeline.query.filter_by(user_id=profile_id).count(),
        "AlertMicroEvent": AlertMicroEvent.query.filter_by(profile_id=profile_id).count(),
        "AIReport": AIReport.query.filter_by(profile_id=profile_id).count(),
        "UserNotification": UserNotification.query.filter_by(user_id=profile_id).count(),
        "NotificationLog": NotificationLog.query.filter_by(user_id=profile_id).count(),
        "DailyPersonalizedCache": DailyPersonalizedCache.query.filter_by(profile_id=profile_id).count(),
        "FreeDailyQuestion": FreeDailyQuestion.query.filter_by(user_id=profile_id).count(),
    }


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        # ==============================================================
        print("=== Test 1: account with NO financial history -> personal data removed + safe hard deletion ===")
        # ==============================================================
        db.session.add(User(id=981001, email="d1-test1@example.com", firebase_uid=FB1))
        db.session.add(AppUser(id=981101, firebase_uid=FB1, name="Test One", email="a@a.com", dob="1990-01-01"))
        db.session.flush()
        seed_personal_children(981101)
        db.session.commit()

        identity1 = resolve_firebase_identity(FB1)
        check("Test 1: identity resolved (found=True)", identity1.found)
        check("Test 1: exactly one profile_id resolved", identity1.profile_ids == [981101])
        check("Test 1: user resolved", identity1.user is not None and identity1.user.id == 981001)

        result1 = delete_account_data(identity1)
        check("Test 1: profile hard-deleted (not anonymized)", result1.hard_deleted_profile_ids == [981101])
        check("Test 1: nothing anonymized", result1.anonymized_profile_ids == [])
        check("Test 1: user_deleted True", result1.user_deleted is True)
        check("Test 1: AppUser row is actually gone", AppUser.query.get(981101) is None)
        check("Test 1: User row is actually gone", User.query.get(981001) is None)

        children1 = count_personal_children(981101)
        check(f"Test 1 (Gate 4 #4): every personal-data child table empty -- {children1}", all(v == 0 for v in children1.values()))

        # ==============================================================
        print("\n=== Test 2: account WITH retained financial history -> parent anonymized, evidence retained ===")
        # ==============================================================
        db.session.add(User(id=981002, email="d1-test2@example.com", firebase_uid=FB2))
        db.session.add(AppUser(id=981102, firebase_uid=FB2, name="Test Two", email="b@b.com", dob="1991-02-02", fcm_token="tok-2"))
        db.session.flush()
        seed_personal_children(981102)
        db.session.add(CurrentEntitlement(profile_id=981102, status="ACTIVE", plan="PRIME_MONTHLY"))
        db.session.add(SubscriptionEvent(profile_id=981102, event_type="SUBSCRIPTION_STARTED", status="ACTIVE"))
        db.session.add(SubscriptionPurchaseMapping(
            purchase_token="tok-d1-test2", profile_id=981102, user_id=981002, provider="GOOGLE_PLAY",
        ))
        db.session.commit()

        identity2 = resolve_firebase_identity(FB2)
        result2 = delete_account_data(identity2)

        check("Test 2: profile ANONYMIZED, not hard-deleted", result2.anonymized_profile_ids == [981102])
        check("Test 2: nothing hard-deleted", result2.hard_deleted_profile_ids == [])
        check("Test 2: reported as retained-financial", result2.retained_financial_profile_ids == [981102])
        check("Test 2: user_deleted True (independent of profile outcome)", result2.user_deleted is True)

        app_user2 = AppUser.query.get(981102)
        check("Test 2: AppUser row still EXISTS (anonymized, not deleted)", app_user2 is not None)
        check("Test 2: name nulled", app_user2.name is None)
        check("Test 2: email nulled", app_user2.email is None)
        check("Test 2: dob nulled", app_user2.dob is None)
        check("Test 2: fcm_token nulled", app_user2.fcm_token is None)
        check("Test 2: subscription reset to 'free'", app_user2.subscription == "free")
        check("Test 2: asknow_tokens reset to 0", app_user2.asknow_tokens == 0)
        check("Test 2: firebase_uid KEPT (pending-cleanup marker per D0.1)", app_user2.firebase_uid == FB2)
        check("Test 2: User row IS gone", User.query.get(981002) is None)

        children2 = count_personal_children(981102)
        check(f"Test 2: every personal-data child table empty -- {children2}", all(v == 0 for v in children2.values()))

        ce2 = CurrentEntitlement.query.filter_by(profile_id=981102).first()
        se2 = SubscriptionEvent.query.filter_by(profile_id=981102).first()
        check("Test 2: CurrentEntitlement RETAINED, untouched", ce2 is not None and ce2.status == "ACTIVE" and ce2.plan == "PRIME_MONTHLY")
        check("Test 2: SubscriptionEvent RETAINED, untouched", se2 is not None and se2.event_type == "SUBSCRIPTION_STARTED")

        # ==============================================================
        print("\n=== Test 5: subscription_purchase_mappings -- user_id -> NULL, profile_id preserved ===")
        # ==============================================================
        spm2 = SubscriptionPurchaseMapping.query.filter_by(purchase_token="tok-d1-test2").first()
        check("Test 5: SubscriptionPurchaseMapping row RETAINED", spm2 is not None)
        check("Test 5: user_id is now NULL", spm2 is not None and spm2.user_id is None)
        check("Test 5: profile_id PRESERVED exactly", spm2 is not None and spm2.profile_id == 981102)

        # ==============================================================
        print("\n=== Test 3: multiple AppUser rows sharing ONE firebase_uid ===")
        # ==============================================================
        db.session.add(User(id=981003, email="d1-test3@example.com", firebase_uid=FB3))
        db.session.add(AppUser(id=981103, firebase_uid=FB3, name="Multi A"))
        db.session.add(AppUser(id=981104, firebase_uid=FB3, name="Multi B"))
        db.session.flush()
        seed_personal_children(981103)
        seed_personal_children(981104)
        db.session.commit()

        identity3 = resolve_firebase_identity(FB3)
        check("Test 3: BOTH profile_ids resolved (never assumes exactly one)", sorted(identity3.profile_ids) == [981103, 981104])

        result3 = delete_account_data(identity3)
        check("Test 3: both profiles hard-deleted (neither has financial history)", sorted(result3.hard_deleted_profile_ids) == [981103, 981104])
        check("Test 3: both AppUser rows gone", AppUser.query.get(981103) is None and AppUser.query.get(981104) is None)
        check("Test 3: User row gone", User.query.get(981003) is None)

        # ==============================================================
        print("\n=== Test 6: legacy System-A Subscription rows removed ===")
        # ==============================================================
        db.session.add(User(id=981005, email="d1-test6@example.com", firebase_uid="test-fb-d1-legacy-sub"))
        db.session.add(AppUser(id=981105, firebase_uid="test-fb-d1-legacy-sub"))
        db.session.flush()
        db.session.add(Subscription(user_id=981005, plan="monthly", status="active"))
        db.session.commit()

        check("Test 6 setup: Subscription row exists before deletion", Subscription.query.filter_by(user_id=981005).count() == 1)
        identity6 = resolve_firebase_identity("test-fb-d1-legacy-sub")
        delete_account_data(identity6)
        check("Test 6: legacy Subscription row is GONE after deletion (not retained)", Subscription.query.filter_by(user_id=981005).count() == 0)
        check("Test 6: users row is gone too", User.query.get(981005) is None)

        # ==============================================================
        print("\n=== Test 7: second execution is idempotent ===")
        # ==============================================================
        # 7a: an already fully-hard-deleted identity (Test 1's FB1).
        identity1_again = resolve_firebase_identity(FB1)
        check("Test 7a: re-resolving a fully-gone identity -> found=False", identity1_again.found is False)
        result1_again = delete_account_data(identity1_again)
        check("Test 7a: second call is a safe no-op (already_absent=True)", result1_again.already_absent is True)
        check("Test 7a: no exception raised", True)  # implicit -- reaching this line means no crash

        # 7b: an anonymized-with-financial-history identity (Test 2's FB2).
        identity2_again = resolve_firebase_identity(FB2)
        check("Test 7b: re-resolving still finds the anonymized profile (firebase_uid kept)", identity2_again.profile_ids == [981102])
        check("Test 7b: user is now None (already deleted first time)", identity2_again.user is None)

        result2_again = delete_account_data(identity2_again)
        check("Test 7b: second call re-reports the same profile as anonymized, no crash", result2_again.anonymized_profile_ids == [981102])
        check("Test 7b: user_deleted False this time (nothing left to delete)", result2_again.user_deleted is False)

        ce2_again = CurrentEntitlement.query.filter_by(profile_id=981102).first()
        check("Test 7b: retained financial evidence STILL intact and unchanged after re-run", ce2_again is not None and ce2_again.status == "ACTIVE")
        spm2_again = SubscriptionPurchaseMapping.query.filter_by(purchase_token="tok-d1-test2").first()
        check("Test 7b: SubscriptionPurchaseMapping still retained, profile_id still correct", spm2_again is not None and spm2_again.profile_id == 981102)

        # ==============================================================
        print("\n=== Test 9: unrelated user's records remain completely unaffected ===")
        # ==============================================================
        db.session.add(User(id=981009, email="d1-test9@example.com", firebase_uid=FB_UNRELATED))
        db.session.add(AppUser(id=981109, firebase_uid=FB_UNRELATED, name="Unrelated Person", email="unrelated@x.com"))
        db.session.flush()
        seed_personal_children(981109)
        db.session.commit()

        # Delete a DIFFERENT identity (re-run test 3's already-gone FB3, and
        # a fresh one) and confirm the unrelated profile/user are untouched.
        resolve_and_delete_noop = delete_account_data(resolve_firebase_identity(FB3))
        check("Test 9 setup: unrelated deletion call did not error", resolve_and_delete_noop.already_absent is True)

        unrelated_user = User.query.get(981009)
        unrelated_profile = AppUser.query.get(981109)
        check("Test 9: unrelated User row untouched", unrelated_user is not None and unrelated_user.email == "d1-test9@example.com")
        check("Test 9: unrelated AppUser row untouched", unrelated_profile is not None and unrelated_profile.name == "Unrelated Person")
        children9 = count_personal_children(981109)
        check(f"Test 9: unrelated personal-data children all still present -- {children9}", all(v == 1 for v in children9.values()))

        # ==============================================================
        print("\n=== Test 10: mixed hard-delete + anonymization under the SAME firebase identity ===")
        # ==============================================================
        db.session.add(User(id=981010, email="d1-test10@example.com", firebase_uid=FB_MIXED))
        db.session.add(AppUser(id=981110, firebase_uid=FB_MIXED, name="Mixed No-Financial"))
        db.session.add(AppUser(id=981111, firebase_uid=FB_MIXED, name="Mixed With-Financial"))
        db.session.flush()
        seed_personal_children(981110)
        seed_personal_children(981111)
        db.session.add(ChatPack(user_id=981111, razorpay_order_id="order-mixed-1", status="success"))
        db.session.commit()

        identity10 = resolve_firebase_identity(FB_MIXED)
        check("Test 10: both profiles resolved under one firebase_uid", sorted(identity10.profile_ids) == [981110, 981111])

        result10 = delete_account_data(identity10)
        check("Test 10: no-financial profile HARD-DELETED", result10.hard_deleted_profile_ids == [981110])
        check("Test 10: with-financial profile ANONYMIZED", result10.anonymized_profile_ids == [981111])
        check("Test 10: AppUser 981110 is gone", AppUser.query.get(981110) is None)
        app_user_981111 = AppUser.query.get(981111)
        check("Test 10: AppUser 981111 still exists, anonymized", app_user_981111 is not None and app_user_981111.name is None)
        chat_pack10 = ChatPack.query.filter_by(user_id=981111).first()
        check("Test 10: ChatPack financial evidence retained, untouched", chat_pack10 is not None and chat_pack10.razorpay_order_id == "order-mixed-1")

        # ==============================================================
        print("\n=== Test 8: injected mid-deletion failure -> COMPLETE transaction rollback ===")
        # ==============================================================
        db.session.add(User(id=981006, email="d1-test8@example.com", firebase_uid=FB_ROLLBACK))
        db.session.add(AppUser(id=981106, firebase_uid=FB_ROLLBACK, name="Rollback Test", email="rb@rb.com"))
        db.session.flush()
        seed_personal_children(981106)
        db.session.add(CurrentEntitlement(profile_id=981106, status="TRIAL"))
        db.session.commit()

        identity8 = resolve_firebase_identity(FB_ROLLBACK)

        real_commit = db.session.commit

        def _boom():
            raise RuntimeError("injected failure -- simulated commit-time crash")

        db.session.commit = _boom
        raised = False
        try:
            delete_account_data(identity8)
        except AccountDeletionError:
            raised = True
        finally:
            db.session.commit = real_commit

        check("Test 8: AccountDeletionError raised (not swallowed)", raised)

        db.session.rollback()  # defensive -- ensure a clean session before re-querying
        app_user8 = AppUser.query.get(981106)
        check("Test 8: AppUser row completely UNCHANGED (not anonymized, not deleted)", app_user8 is not None and app_user8.name == "Rollback Test" and app_user8.email == "rb@rb.com")
        check("Test 8: User row STILL EXISTS (not deleted)", User.query.get(981006) is not None)
        children8 = count_personal_children(981106)
        check(f"Test 8: personal-data children NOT deleted -- full rollback -- {children8}", all(v == 1 for v in children8.values()))
        ce8 = CurrentEntitlement.query.filter_by(profile_id=981106).first()
        check("Test 8: financial row untouched throughout", ce8 is not None and ce8.status == "TRIAL")

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
