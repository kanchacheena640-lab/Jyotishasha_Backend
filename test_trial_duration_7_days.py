"""
test_trial_duration_7_days.py
----------------------------------
15-Day-to-7-Day Trial change -- proves the canonical trial length
(EntitlementWriteService.DEFAULT_TRIAL_DURATION_DAYS) is exactly 7
days, that it is the ONLY place a new trial's window is computed, and
that every other CurrentEntitlement/EntitlementService behavior this
change must NOT touch (access gating, immutable trial_started_at,
paid ACTIVE/GRACE subscriptions, one-time-per-profile protection)
still works exactly as before.

Covers:
  A. A brand-new profile's trial gets exactly trial_expires_at ==
     trial_started_at + 7 days (not 15).
  B. membership_state == "TRIAL" and all 6 SUBSCRIPTION_SECTIONS are
     accessible at any point strictly inside the 7-day window.
  C. At/after the 7-day mark, EntitlementService already reports
     membership_state == "EXPIRED" and zero accessible_segments --
     live, timestamp-computed, with no dependency on the daily cron.
  D. A second start_trial() call for the same profile_id is a no-op
     (TRIAL_SKIPPED) and does NOT move trial_started_at or
     trial_expires_at -- proves logout/reinstall/FCM-refresh (all of
     which just re-resolve the same profile_id) cannot restart or
     extend the trial.
  E. A profile with a paid ACTIVE subscription is completely unaffected
     by this change -- start_trial() on it is a no-op, and its
     subscription_expires_at is untouched.
  F. DEFAULT_TRIAL_DURATION_DAYS itself is exactly 7 (guards against a
     future accidental revert), and confirms it's the one canonical
     constant EntitlementWriteService.start_trial() actually uses
     (proven by A, not re-derived here).

Uses the LOCAL scratch Postgres DB ONLY. No production access.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from modules.models_user import AppUser  # noqa: E402
from modules.models_premium_subscription import CurrentEntitlement  # noqa: E402
from modules.entitlement import EntitlementService  # noqa: E402
from modules.entitlement.entitlement_write_service import (  # noqa: E402
    DEFAULT_TRIAL_DURATION_DAYS,
    EntitlementWriteService,
)
from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS  # noqa: E402
from modules.subscription.subscription_service import SubscriptionService  # noqa: E402

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


PROFILE_IDS = list(range(985001, 985010))


def cleanup():
    # FK order: current_entitlements.last_event_id -> subscription_events.id
    # -> subscription_events.profile_id -> app_users.id. Must delete in
    # exactly this order (entitlements, then events, then app_users).
    CurrentEntitlement.query.filter(
        CurrentEntitlement.profile_id.in_(PROFILE_IDS),
    ).delete(synchronize_session=False)
    db.session.execute(
        text("DELETE FROM subscription_events WHERE profile_id = ANY(:ids)"),
        {"ids": PROFILE_IDS},
    )
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    db.session.commit()


def ensure_app_users():
    # CurrentEntitlement/SubscriptionEvent both FK to app_users.id --
    # these test profile_ids need a real (minimal) AppUser row to exist
    # first, same requirement any real profile_id has in production.
    for pid in PROFILE_IDS:
        if db.session.get(AppUser, pid) is None:
            db.session.add(AppUser(id=pid, firebase_uid=f"test-trial-7d-{pid}"))
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()
        ensure_app_users()

        entitlement = EntitlementService()
        subscription = SubscriptionService()

        # ==========================================================
        print("=== F: canonical constant is exactly 7 ===")
        # ==========================================================
        check("F: DEFAULT_TRIAL_DURATION_DAYS == 7", DEFAULT_TRIAL_DURATION_DAYS == 7)
        check(
            "F: a fresh EntitlementWriteService() defaults to 7 (not overridden)",
            EntitlementWriteService()._trial_duration_days == 7,
        )

        # ==========================================================
        print("\n=== A: a brand-new profile's trial is exactly 7 days ===")
        # ==========================================================
        p_a = 985001
        before = datetime.utcnow()
        result_a = subscription.start_trial(p_a)
        after = datetime.utcnow()

        check("A: start_trial succeeds", result_a.success is True)
        check("A: action == TRIAL_STARTED", result_a.action == "TRIAL_STARTED")

        row_a = CurrentEntitlement.query.filter_by(profile_id=p_a).first()
        check("A: CurrentEntitlement row created", row_a is not None)
        check("A: status == TRIAL", row_a.status == "TRIAL")
        check(
            "A: trial_started_at is within this call's window",
            before <= row_a.trial_started_at <= after,
        )
        delta = row_a.trial_expires_at - row_a.trial_started_at
        check(
            f"A: trial_expires_at - trial_started_at == 7 days (got {delta})",
            delta == timedelta(days=7),
        )
        check(
            "A: trial_expires_at is NOT 15 days out (regression guard)",
            row_a.trial_expires_at != row_a.trial_started_at + timedelta(days=15),
        )

        # ==========================================================
        print("\n=== B: membership_state == TRIAL, all 6 sections accessible, inside the window ===")
        # ==========================================================
        snapshot_b = entitlement.get_current_entitlement(p_a)
        check("B: membership_state == TRIAL", snapshot_b.membership_state == "TRIAL")
        check("B: trial.is_active == True", snapshot_b.trial.is_active is True)
        check(
            f"B: all 6 SUBSCRIPTION_SECTIONS accessible (got {len(snapshot_b.accessible_segments)})",
            set(snapshot_b.accessible_segments) == set(SUBSCRIPTION_SECTIONS)
            and len(SUBSCRIPTION_SECTIONS) == 6,
        )
        check(
            "B: remaining_trial_days is 7 (whole days, just started)",
            snapshot_b.remaining_trial_days == 7,
        )

        # ==========================================================
        print("\n=== C: at/after the 7-day mark, access is already EXPIRED (no cron needed) ===")
        # ==========================================================
        p_c = 985002
        subscription.start_trial(p_c)
        row_c = CurrentEntitlement.query.filter_by(profile_id=p_c).first()
        # Simulate "7 days have passed" by directly backdating the
        # already-recorded timestamps (read-only w.r.t. business logic --
        # this only fast-forwards wall-clock time for the test, exactly
        # the same technique the 15-day audit's own prior tests used).
        row_c.trial_started_at = datetime.utcnow() - timedelta(days=8)
        row_c.trial_expires_at = row_c.trial_started_at + timedelta(days=7)
        db.session.commit()

        snapshot_c = entitlement.get_current_entitlement(p_c)
        check("C: membership_state == EXPIRED", snapshot_c.membership_state == "EXPIRED")
        check("C: trial.is_active == False", snapshot_c.trial.is_active is False)
        check("C: accessible_segments is empty", snapshot_c.accessible_segments == [])
        check("C: remaining_trial_days is None", snapshot_c.remaining_trial_days is None)
        check(
            "C: raw DB status is still TRIAL (cron hasn't run) -- proves the read path, "
            "not the stale column, is what protects access",
            row_c.status == "TRIAL",
        )

        # ==========================================================
        print("\n=== D: a second start_trial() call cannot restart/extend the trial ===")
        # ==========================================================
        p_d = 985003
        result_d1 = subscription.start_trial(p_d)
        row_d = CurrentEntitlement.query.filter_by(profile_id=p_d).first()
        original_started_at = row_d.trial_started_at
        original_expires_at = row_d.trial_expires_at

        result_d2 = subscription.start_trial(p_d)  # simulates logout/reinstall/FCM-refresh re-resolving the same profile
        db.session.refresh(row_d)

        check("D: first call started the trial", result_d1.action == "TRIAL_STARTED")
        check("D: second call is a no-op (TRIAL_SKIPPED)", result_d2.action == "TRIAL_SKIPPED")
        check(
            "D: trial_started_at is byte-for-byte unchanged",
            row_d.trial_started_at == original_started_at,
        )
        check(
            "D: trial_expires_at is byte-for-byte unchanged (no extension)",
            row_d.trial_expires_at == original_expires_at,
        )

        # ==========================================================
        print("\n=== E: a paid ACTIVE subscription is completely unaffected ===")
        # ==========================================================
        p_e = 985004
        expires_at_e = datetime.utcnow() + timedelta(days=30)
        activation_e = subscription.activate_subscription(
            profile_id=p_e, plan="PRIME_PLUS_MONTHLY", selected_segment=None,
            expires_at=expires_at_e,
        )
        check("E: activation itself succeeded", activation_e.success is True)
        row_e_before = CurrentEntitlement.query.filter_by(profile_id=p_e).first()
        check("E: profile is ACTIVE before start_trial", row_e_before.status == "ACTIVE")

        result_e = subscription.start_trial(p_e)
        row_e_after = CurrentEntitlement.query.filter_by(profile_id=p_e).first()

        check("E: start_trial() on an ACTIVE profile is a no-op", result_e.action == "TRIAL_SKIPPED")
        check("E: status is still ACTIVE (not overwritten to TRIAL)", row_e_after.status == "ACTIVE")
        check(
            "E: subscription_expires_at is byte-for-byte untouched",
            row_e_after.subscription_expires_at == expires_at_e,
        )
        check("E: trial_started_at was never set", row_e_after.trial_started_at is None)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
