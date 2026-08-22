"""
test_subscription_state_sync_google_revocation.py
-----------------------------------------------------
Regression tests for the Google Play refund/revocation reconciliation
fix in modules/subscription/subscription_state_sync_service.py.

Root cause (prior read-only audit, confirmed against production data
for profile_id=1093): SubscriptionStateSyncService is purely time-based
-- it compares the stored CurrentEntitlement.subscription_expires_at
against datetime.utcnow() and never re-checks Google Play. When a
Google Play Console refund ("Remove entitlement") is performed and its
RTDN SUBSCRIPTION_REVOKED notification is missed, the subscription
stays ACTIVE (or, once its stale stored expiry passes, is mechanically
moved into GRACE) forever -- with no code path ever correcting it,
since GRACE is one of the two statuses this service otherwise treats
as "still legitimately entitled".

The fix adds SubscriptionStateSyncService._check_google_revocation(),
called at the top of BOTH the ACTIVE and GRACE branches of
sync_profile() (so an entitlement already incorrectly sitting in GRACE
self-heals on the very next sweep, without waiting for the grace
window to lapse). It resolves the profile's current Google Play
purchase via the EXISTING SubscriptionPurchaseMapping table (never
fabricated) and performs a live re-check via the EXISTING
GooglePlayProvider.verify_subscription_purchase(). Only two Google
states are treated as definitive:
  - verification_status == NOT_FOUND      -> SubscriptionService.record_refund()
  - VERIFIED + purchase_state == "SUBSCRIPTION_STATE_EXPIRED"
                                            -> SubscriptionService.expire_subscription()
Both dispatch through the exact same SubscriptionService methods the
RTDN pipeline already uses for the equivalent notification types --
nothing new is invented. Every other outcome (still-ACTIVE, CANCELED,
IN_GRACE_PERIOD, ON_HOLD, PAUSED, PENDING, a verification
exception/error, or no resolvable mapping) is inconclusive and falls
back to the existing, unmodified, purely time-based behavior.

Test strategy: SubscriptionStateSyncService's three collaborators
(EntitlementService, SubscriptionService, GooglePlayProvider) are all
constructor-injectable -- faked here with plain Python objects, no real
DB needed for the entitlement-decision logic itself. The one place a
real row is needed is SubscriptionPurchaseMapping (the fix's own
`.query` lookup) -- backed by the LOCAL scratch Postgres DB only, same
convention as test_alert_persistence_ai_fields.py.

LOCAL ONLY. No production DB, no real Google Play network call, no
OpenAI call, no real payment.
"""

import os
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from modules.entitlement.entitlement_models import (  # noqa: E402
    EntitlementSnapshot, TrialStatus, SubscriptionStatus,
)
from modules.entitlement.entitlement_write_models import EntitlementWriteResult  # noqa: E402
from modules.payments.google_play_models import (  # noqa: E402
    GooglePlaySubscriptionVerification, GooglePlayVerificationStatus,
)
from modules.models_subscription_purchase_mapping import SubscriptionPurchaseMapping  # noqa: E402
from modules.subscription.subscription_state_sync_service import (  # noqa: E402
    SubscriptionStateSyncService,
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


TEST_PROFILE = 9301


def cleanup():
    db.session.execute(
        text("DELETE FROM subscription_purchase_mappings WHERE profile_id = :p"),
        {"p": TEST_PROFILE},
    )
    db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
    db.session.commit()


def make_user(conn, profile_id):
    conn.execute(text(
        "INSERT INTO app_users (id, tz, subscription, asknow_tokens, name, dob, tob, pob, lat, lng) "
        "VALUES (:id, 'IST', 'free', 0, 'Test', '1990-01-01', '10:00', 'Delhi', 28.6, 77.2)"
    ), {"id": profile_id})


def make_mapping(profile_id, purchase_token="test-token-123", order_id="GPA.TEST-0001", status="ACTIVE"):
    row = SubscriptionPurchaseMapping(
        purchase_token=purchase_token, profile_id=profile_id, provider="GOOGLE_PLAY",
        product_id="jyotishasha.gold.monthly", order_id=order_id, status=status,
    )
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------
# Fakes -- entitlement/subscription collaborators (pure Python, no DB).
# ---------------------------------------------------------------------
class _FakeEntitlementService:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.calls = 0

    def get_current_entitlement(self, profile_id):
        self.calls += 1
        return self._snapshot


class _FakeSubscriptionService:
    def __init__(self):
        self.calls = []

    def _record(self, method, profile_id, **kwargs):
        self.calls.append((method, profile_id, kwargs))
        return EntitlementWriteResult(
            success=True, action=method.upper(), profile_id=profile_id,
        )

    def expire_trial(self, profile_id):
        return self._record("expire_trial", profile_id)

    def enter_grace(self, profile_id):
        return self._record("enter_grace", profile_id)

    def exit_grace(self, profile_id):
        return self._record("exit_grace", profile_id)

    def expire_subscription(self, profile_id):
        return self._record("expire_subscription", profile_id)

    def record_refund(self, profile_id, transaction_reference=None):
        return self._record("record_refund", profile_id, transaction_reference=transaction_reference)


class _FakeGooglePlayProvider:
    def __init__(self, result=None, raise_exc=None):
        self._result = result
        self._raise_exc = raise_exc
        self.calls = []

    def verify_subscription_purchase(self, *, purchase_token):
        self.calls.append(purchase_token)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


def _active_snapshot(expires_at):
    return EntitlementSnapshot(
        profile_id=TEST_PROFILE, status="ACTIVE", plan="GOLD_MONTHLY", selected_segment=None,
        trial=TrialStatus(is_active=False),
        subscription=SubscriptionStatus(is_active=True, status="ACTIVE", plan="GOLD_MONTHLY", expires_at=expires_at),
        accessible_segments=[],
    )


def _grace_snapshot(expires_at):
    return EntitlementSnapshot(
        profile_id=TEST_PROFILE, status="GRACE", plan="GOLD_MONTHLY", selected_segment=None,
        trial=TrialStatus(is_active=False),
        subscription=SubscriptionStatus(is_active=True, status="GRACE", plan="GOLD_MONTHLY", expires_at=expires_at),
        accessible_segments=[],
    )


def build_service(snapshot, google_result=None, google_exc=None):
    return SubscriptionStateSyncService(
        subscription_service=_FakeSubscriptionService(),
        entitlement_service=_FakeEntitlementService(snapshot),
        google_play_provider=_FakeGooglePlayProvider(result=google_result, raise_exc=google_exc),
    )


NOW = datetime.utcnow()
FUTURE = NOW + timedelta(days=10)
PAST = NOW - timedelta(days=1)


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()

        # ==========================================================
        print("=== 1: ACTIVE + Google revoked (NOT_FOUND) -> REFUNDED, never GRACE ===")
        # ==========================================================
        make_mapping(TEST_PROFILE, purchase_token="tok-1")
        svc = build_service(
            _active_snapshot(FUTURE),
            google_result=GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.NOT_FOUND, purchase_token="tok-1",
            ),
        )
        result = svc.sync_profile(TEST_PROFILE)
        check("1: record_refund() called", svc._subscription_service.calls[0][0] == "record_refund")
        check("1: enter_grace() NEVER called", not any(c[0] == "enter_grace" for c in svc._subscription_service.calls))
        check("1: exactly one collaborator call made", len(svc._subscription_service.calls) == 1)
        check("1: transaction_reference carried through from the mapping's order_id",
              svc._subscription_service.calls[0][2]["transaction_reference"] == "GPA.TEST-0001")
        cleanup(); make_user_conn = None

        # ==========================================================
        print("\n=== 2: GRACE + Google revoked (NOT_FOUND) -> REFUNDED "
              "(profile_id=1093's exact real-world scenario) ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        make_mapping(TEST_PROFILE, purchase_token="tok-2")
        svc = build_service(
            _grace_snapshot(PAST),  # already past its grace deadline OR mid-window -- irrelevant, checked first
            google_result=GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.NOT_FOUND, purchase_token="tok-2",
            ),
        )
        result = svc.sync_profile(TEST_PROFILE)
        check("2: record_refund() called from the GRACE branch", svc._subscription_service.calls[0][0] == "record_refund")
        check("2: exit_grace() NEVER called", not any(c[0] == "exit_grace" for c in svc._subscription_service.calls))
        cleanup()

        # ==========================================================
        print("\n=== 2b: GRACE + Google revoked via VERIFIED/EXPIRED -> expire_subscription() ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        make_mapping(TEST_PROFILE, purchase_token="tok-2b")
        svc = build_service(
            _grace_snapshot(FUTURE),  # not yet at its own grace deadline -- must still self-heal NOW
            google_result=GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.VERIFIED, purchase_token="tok-2b",
                purchase_state="SUBSCRIPTION_STATE_EXPIRED",
            ),
        )
        result = svc.sync_profile(TEST_PROFILE)
        check("2b: expire_subscription() called even mid-grace-window (self-heals immediately)",
              svc._subscription_service.calls[0][0] == "expire_subscription")
        check("2b: exit_grace() NEVER called", not any(c[0] == "exit_grace" for c in svc._subscription_service.calls))
        cleanup()

        # ==========================================================
        print("\n=== 3: ACTIVE + legitimate normal expiry -> existing GRACE behavior preserved ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        make_mapping(TEST_PROFILE, purchase_token="tok-3")
        svc = build_service(
            _active_snapshot(PAST),  # locally expired
            google_result=GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.VERIFIED, purchase_token="tok-3",
                purchase_state="SUBSCRIPTION_STATE_ACTIVE",  # Google says still active -- inconclusive/no revoke
            ),
        )
        result = svc.sync_profile(TEST_PROFILE)
        check("3: enter_grace() still called (existing time-based behavior unchanged)",
              svc._subscription_service.calls[0][0] == "enter_grace")
        check("3: record_refund()/expire_subscription() NEVER called",
              not any(c[0] in ("record_refund", "expire_subscription") for c in svc._subscription_service.calls))
        cleanup()

        # ==========================================================
        print("\n=== 4: GRACE + legitimate grace state (still within window) -> remains GRACE ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        make_mapping(TEST_PROFILE, purchase_token="tok-4")
        svc = build_service(
            _grace_snapshot(NOW),  # grace deadline (NOW + 3 days) not yet reached
            google_result=GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.VERIFIED, purchase_token="tok-4",
                purchase_state="SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
            ),
        )
        result = svc.sync_profile(TEST_PROFILE)
        check("4: no transition at all (still legitimately in grace)", result is None)
        check("4: no destructive call made", len(svc._subscription_service.calls) == 0)
        cleanup()

        # ==========================================================
        print("\n=== 5: Google verification exception/unavailable -> existing fallback behavior preserved ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        make_mapping(TEST_PROFILE, purchase_token="tok-5")
        svc = build_service(_active_snapshot(PAST), google_exc=RuntimeError("network unreachable"))
        result = svc.sync_profile(TEST_PROFILE)
        check("5: enter_grace() still called despite the Google exception (fails open, not closed)",
              svc._subscription_service.calls[0][0] == "enter_grace")
        cleanup()

        # ==========================================================
        print("\n=== 6: missing purchase mapping -> existing fallback behavior preserved ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        # Deliberately NO make_mapping() call this time.
        svc = build_service(_active_snapshot(PAST))
        result = svc.sync_profile(TEST_PROFILE)
        check("6: enter_grace() still called with no mapping to check at all",
              svc._subscription_service.calls[0][0] == "enter_grace")
        check("6: Google Play provider was never even called (nothing to check)",
              len(svc._google_play_provider.calls) == 0)
        cleanup()

        # ==========================================================
        print("\n=== 7: expiration behavior unchanged where no revocation exists (ACTIVE, not yet expired) ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        make_mapping(TEST_PROFILE, purchase_token="tok-7")
        svc = build_service(
            _active_snapshot(FUTURE),  # not locally expired yet
            google_result=GooglePlaySubscriptionVerification(
                verification_status=GooglePlayVerificationStatus.VERIFIED, purchase_token="tok-7",
                purchase_state="SUBSCRIPTION_STATE_ACTIVE",
            ),
        )
        result = svc.sync_profile(TEST_PROFILE)
        check("7: no transition -- nothing due yet, nothing revoked", result is None)
        cleanup()

        # ==========================================================
        print("\n=== 8: recovery/renewal paths not broken (TRIAL branch untouched by this fix) ===")
        # ==========================================================
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()
        trial_snapshot = EntitlementSnapshot(
            profile_id=TEST_PROFILE, status="TRIAL", plan=None, selected_segment=None,
            trial=TrialStatus(is_active=True, expires_at=PAST),
            subscription=SubscriptionStatus(is_active=False, status="TRIAL"),
            accessible_segments=[],
        )
        svc = build_service(trial_snapshot)
        result = svc.sync_profile(TEST_PROFILE)
        check("8: expire_trial() still called for TRIAL, exactly as before this fix",
              svc._subscription_service.calls[0][0] == "expire_trial")
        check("8: Google Play provider never called for a TRIAL profile (no purchase to check)",
              len(svc._google_play_provider.calls) == 0)
        cleanup()

        # ==========================================================
        print("\n=== 9: Silver/Gold plan-access policy untouched (static check) ===")
        # ==========================================================
        import inspect
        sync_src = inspect.getsource(
            __import__(
                "modules.subscription.subscription_state_sync_service", fromlist=["x"],
            )
        )
        check("9: plan_access_policy is never imported/touched by this fix",
              "plan_access_policy" not in sync_src and "PLAN_SEGMENT_ACCESS" not in sync_src)
        check("9: ACCESS_SELECTED/ACCESS_ALL are never referenced by this fix",
              "ACCESS_SELECTED" not in sync_src and "ACCESS_ALL" not in sync_src)

        print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
        if failed:
            sys.exit(1)


if __name__ == "__main__":
    main()
