# test_attention_policy.py

"""
Local-only entry point for N4 (Global User Attention Policy).

Follows the same convention as every other test_*.py script in this repo
(see test_notification_lifecycle.py's own docstring): connects ONLY to the
local scratch Postgres DB (jyotishasha_local), asserts that database
identity before touching anything, and cleans up its own rows at the end.
No production access, no real FCM call.

Proves, in order:
1. services/attention_policy.py's pure selection/tier functions --
   deterministic, no DB needed (N4 test requirements 1-7, 12-14).
2. That the shared, persisted daily-push counter (count_pushes_sent_today())
   correctly reflects real UserNotification rows written by BOTH
   services/event_scheduler.py's pipeline and (conceptually) Alerts'
   delivery path, across reruns, delayed runs, and the IST calendar-day
   boundary (N4 test requirements 8-11, 13, 15).
3. That N3 (personalized transit) and Dasha/Dasha-pre content/priority
   remain intact under the new tiering (N4 test requirements 16-17).
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
from sqlalchemy import text  # noqa: E402

from notifications.notification_models import UserNotification, NotificationLog  # noqa: E402
from services.attention_policy import (  # noqa: E402
    DAILY_PUSH_CAP,
    TIER_HIGHEST,
    TIER_CONTEXTUAL,
    TIER_ROUTINE,
    AttentionCandidate,
    BELL_ONLY_ELIGIBLE_TIERS,
    count_pushes_sent_today,
    select_for_push,
    start_of_today_ist,
    tier_for_alert_severity,
    tier_for_event_scheduler_type,
)

PROFILE = 9801

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
    db.session.execute(text("DELETE FROM notification_logs WHERE user_id = :p"), {"p": PROFILE})
    db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": PROFILE})
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        # ==============================================================
        print("=== N4 Test 16/17: priority model matches real signals (no fabricated distinctions) ===")
        # ==============================================================
        check("Dasha -> Tier 1 (Highest)", tier_for_event_scheduler_type("dasha") == TIER_HIGHEST)
        check("Dasha-pre -> Tier 1 (Highest)", tier_for_event_scheduler_type("dasha_pre") == TIER_HIGHEST)
        check("Transit (N3) -> Tier 1 (Highest) -- content/routing/house calc untouched", tier_for_event_scheduler_type("transit") == TIER_HIGHEST)
        check("Event (festival/vrat) -> Tier 2 (Contextual)", tier_for_event_scheduler_type("event") == TIER_CONTEXTUAL)
        check("Panchak -> Tier 2 (Contextual)", tier_for_event_scheduler_type("panchak") == TIER_CONTEXTUAL)
        check("Panchang -> Tier 3 (Routine)", tier_for_event_scheduler_type("panchang") == TIER_ROUTINE)
        check("Unknown future type defaults to Tier 2, never silently Tier 1 or dropped as Tier 3", tier_for_event_scheduler_type("some_future_type") == TIER_CONTEXTUAL)
        check("HIGH-severity Alert -> Tier 1", tier_for_alert_severity("HIGH") == TIER_HIGHEST)
        check("CRITICAL-severity Alert -> Tier 1", tier_for_alert_severity("CRITICAL") == TIER_HIGHEST)
        check("MEDIUM-severity Alert -> Tier 2", tier_for_alert_severity("MEDIUM") == TIER_CONTEXTUAL)
        check("LOW-severity Alert -> Tier 2", tier_for_alert_severity("LOW") == TIER_CONTEXTUAL)
        check("None/missing severity -> Tier 2 (safe default, never silently Tier 1)", tier_for_alert_severity(None) == TIER_CONTEXTUAL)

        # ==============================================================
        print("\n=== N4 Test 1: one strong candidate -> exactly 1 push ===")
        # ==============================================================
        result = select_for_push(
            [AttentionCandidate(key="dasha_1", tier=TIER_HIGHEST, label="dasha")],
            already_sent_today=0,
        )
        check("1 candidate, 0 already sent -> 1 approved, 0 bell_only, 0 dropped",
              result.approved == ["dasha_1"] and not result.bell_only and not result.dropped)

        # ==============================================================
        print("\n=== N4 Test 2: two strong distinct candidates -> both pushed (2 pushes) ===")
        # ==============================================================
        result = select_for_push(
            [
                AttentionCandidate(key="transit_moon", tier=TIER_HIGHEST, label="transit"),
                AttentionCandidate(key="dasha_1", tier=TIER_HIGHEST, label="dasha"),
            ],
            already_sent_today=0,
        )
        check("2 Tier-1 candidates, 0 already sent -> both approved",
              result.approved == ["transit_moon", "dasha_1"])

        # ==============================================================
        print("\n=== N4 Test 3: ten candidates -> never routine-spam the user (cap always holds) ===")
        # ==============================================================
        ten = [AttentionCandidate(key=f"c{i}", tier=TIER_ROUTINE, label="panchang") for i in range(10)]
        result = select_for_push(ten, already_sent_today=0)
        check("10 candidates, cap=2 -> exactly 2 approved, never more",
              len(result.approved) == DAILY_PUSH_CAP == 2)
        check("...remaining 8 are Tier-3/routine -> dropped, not bell_only clutter",
              len(result.dropped) == 8 and not result.bell_only)

        # ==============================================================
        print("\n=== N4 Test 4: Major Dasha competes with Panchang -> Dasha wins the push, Panchang loses cleanly ===")
        # ==============================================================
        result = select_for_push(
            [
                AttentionCandidate(key="panchang", tier=TIER_ROUTINE, label="panchang"),
                AttentionCandidate(key="dasha", tier=TIER_HIGHEST, label="dasha"),
            ],
            already_sent_today=1,  # only 1 slot left today
        )
        check("Dasha (Tier 1) approved over Panchang (Tier 3) despite arriving second in the list",
              result.approved == ["dasha"])
        check("Panchang is dropped (Tier 3, not Bell-only-eligible), not bell_only clutter",
              result.dropped == ["panchang"] and not result.bell_only)

        # ==============================================================
        print("\n=== N4 Test 5: Personalized Transit competes with routine Panchang -> Transit wins ===")
        # ==============================================================
        result = select_for_push(
            [
                AttentionCandidate(key="panchang", tier=TIER_ROUTINE, label="panchang"),
                AttentionCandidate(key="transit", tier=TIER_HIGHEST, label="transit"),
            ],
            already_sent_today=1,
        )
        check("Transit approved, Panchang dropped", result.approved == ["transit"] and result.dropped == ["panchang"])

        # ==============================================================
        print("\n=== N4 Test 6/7: High-value Alert vs routine Event/Panchang; two Alerts cannot blindly consume both slots ===")
        # ==============================================================
        # Simulates: event_scheduler's morning run already used 1 slot on
        # a routine Event. Alerts (a separate process) then has 2 alerts
        # selected by ITS OWN engine (unmodified) -- only HIGH-severity
        # should get the remaining 1 global slot; MEDIUM must not.
        result = select_for_push(
            [
                AttentionCandidate(key="alert_high", tier=tier_for_alert_severity("HIGH"), label="alert"),
                AttentionCandidate(key="alert_medium", tier=tier_for_alert_severity("MEDIUM"), label="alert"),
            ],
            already_sent_today=1,  # 1 slot already spent this morning (routine Event)
        )
        check("N4 Test 6: HIGH-severity Alert wins the one remaining global slot over routine Event's prior claim",
              result.approved == ["alert_high"])
        check("N4 Test 7: the second (MEDIUM) Alert does NOT automatically consume the global quota just because "
              "Alerts' own local selection chose it -- it is Bell-only, not silently dropped either",
              result.bell_only == ["alert_medium"])

        # ==============================================================
        print("\n=== N4 Test 12: distinct high-value categories are never suppressed merely for differing type ===")
        # ==============================================================
        result = select_for_push(
            [
                AttentionCandidate(key="transit_jupiter", tier=TIER_HIGHEST, label="transit"),
                AttentionCandidate(key="dasha_change", tier=TIER_HIGHEST, label="dasha"),
            ],
            already_sent_today=0,
        )
        check("A Transit and a Dasha candidate on the same day are BOTH approved -- genuinely distinct "
              "high-value information is not merged/suppressed just because the technical type differs",
              set(result.approved) == {"transit_jupiter", "dasha_change"})

        # ==============================================================
        print("\n=== N4 Test 13/14: Bell-only policy -- Tier 1/2 suppressed-by-cap gets Bell-only, Tier 3 gets nothing ===")
        # ==============================================================
        result = select_for_push(
            [
                AttentionCandidate(key="event_tomorrow", tier=TIER_CONTEXTUAL, label="event"),
                AttentionCandidate(key="panchang", tier=TIER_ROUTINE, label="panchang"),
            ],
            already_sent_today=2,  # cap already fully spent
        )
        check("N4 Test 13: nothing is approved once the cap is fully spent (never accidentally marked delivered)",
              not result.approved)
        check("N4 Test 14: Tier-2 Event suppressed-by-cap -> Bell-only (still useful, just not pushed)",
              result.bell_only == ["event_tomorrow"])
        check("N4 Test 14: Tier-3 Panchang suppressed-by-cap -> fully dropped, never Bell clutter",
              result.dropped == ["panchang"])
        check("Bell-only tier set is exactly {Highest, Contextual}, excluding Routine",
              BELL_ONLY_ELIGIBLE_TIERS == {TIER_HIGHEST, TIER_CONTEXTUAL})

        # ==============================================================
        print("\n=== N4 Test 8/9/10/11: shared persisted counter -- real DB integration ===")
        # ==============================================================
        now_ist_noon = datetime(2026, 8, 15, 6, 30, 0)  # 2026-08-15 12:00 IST, naive UTC

        check("N4 Test 8 (baseline): 0 pushes today before any write", count_pushes_sent_today(PROFILE, now=now_ist_noon) == 0)

        # Morning run "sends" 1 qualifying notification (e.g. a Dasha push).
        # created_at is set EXPLICITLY (naive UTC), rather than relying on
        # the column's db.func.current_timestamp() default -- this local
        # dev DB's own session timezone (Asia/Kolkata, documented in
        # modules/alerts/user_alert_selection_service.py's own
        # resolve_daily_cap_window_start() docstring) would otherwise make
        # CURRENT_TIMESTAMP write IST wall-clock digits into this naive
        # column, not UTC, which is a local-dev-connection quirk, not
        # production's actual behavior -- setting it explicitly keeps this
        # test deterministic regardless of session timezone.
        db.session.add(UserNotification(
            user_id=PROFILE, title="Dasha push", body="...",
            data={"type": "dasha"}, is_read=False,
            created_at=now_ist_noon,
        ))
        db.session.commit()
        check("N4 Test 8: morning sends 1 -> count is now 1 (evening sees already_sent_today = 1)",
              count_pushes_sent_today(PROFILE, now=now_ist_noon) == 1)

        # Evening run: only 1 normal slot remains.
        remaining = max(0, DAILY_PUSH_CAP - count_pushes_sent_today(PROFILE, now=now_ist_noon))
        check("N4 Test 8: exactly 1 slot remains for the evening run", remaining == 1)

        # Now simulate morning having ALREADY delivered 2 (e.g. Dasha + Transit).
        db.session.add(UserNotification(
            user_id=PROFILE, title="Transit push", body="...",
            data={"type": "transit"}, is_read=False,
            created_at=now_ist_noon,
        ))
        db.session.commit()
        check("N4 Test 9: morning delivered 2 -> count is now 2",
              count_pushes_sent_today(PROFILE, now=now_ist_noon) == 2)
        evening_candidates = [AttentionCandidate(key="panchang_evening", tier=TIER_ROUTINE, label="panchang")]
        evening_result = select_for_push(
            evening_candidates,
            already_sent_today=count_pushes_sent_today(PROFILE, now=now_ist_noon),
        )
        check("N4 Test 9: evening's routine push is suppressed (dropped, Tier 3) -- never becomes a 3rd push",
              not evening_result.approved and evening_result.dropped == ["panchang_evening"])

        # N4 Test 10: rerun cannot bypass the cap -- re-querying (no new
        # writes) must return the identical count, not reset to 0.
        check("N4 Test 10: a scheduler rerun re-reads the SAME persisted count (2), never resets it",
              count_pushes_sent_today(PROFILE, now=now_ist_noon) == 2)

        # N4 Test 11: a delayed run (much later the SAME IST day) still
        # sees the same count -- date semantics are calendar-day, not
        # clock-time-window based.
        later_same_day = datetime(2026, 8, 15, 15, 0, 0)  # 2026-08-15 20:30 IST, still same IST day
        check("N4 Test 11: a delayed same-IST-day run still sees count = 2, cannot bypass via lateness",
              count_pushes_sent_today(PROFILE, now=later_same_day) == 2)

        # And the IST-day boundary itself is real: a query anchored to
        # the PREVIOUS IST day must not see today's rows, and vice versa.
        next_ist_day = datetime(2026, 8, 15, 19, 0, 0)  # 2026-08-16 00:30 IST -- next day
        check("N4 Test 11: crossing the real IST midnight boundary resets the count to 0 for the new day "
              "(delayed scheduler cannot resurrect yesterday's spent budget as unspent, nor bleed it forward)",
              count_pushes_sent_today(PROFILE, now=next_ist_day) == 0)

        # ==============================================================
        print("\n=== N4 Test 13 (continued)/15: Bell-only row is never counted as a push, and N2 expiry still governs it ===")
        # ==============================================================
        cleanup()
        from services.notification_lifecycle import expiry_for_astro_event_notification

        bell_only_row = UserNotification(
            user_id=PROFILE, title="Amavasya Tomorrow", body="...",
            data={"type": "event", "event_id": "1", "delivery_channel": "bell_only"},
            is_read=False,
            created_at=now_ist_noon,
            expires_at=expiry_for_astro_event_notification(event_date=date(2026, 8, 16), is_forward_looking=True),
        )
        db.session.add(bell_only_row)
        db.session.commit()
        check("N4 Test 13: a Bell-only row (delivery_channel=bell_only) does NOT count toward pushes sent today",
              count_pushes_sent_today(PROFILE, now=now_ist_noon) == 0)

        def bell_visible_ids(user_id, now):
            from sqlalchemy import or_
            rows = (
                UserNotification.query
                .filter(UserNotification.user_id == user_id)
                .filter(or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > now))
                .all()
            )
            return {r.id for r in rows}

        before_midnight = datetime(2026, 8, 15, 12, 0, 0)
        after_midnight = datetime(2026, 8, 15, 19, 0, 0)
        check("N4 Test 15: Bell-only row IS visible before its N2-computed expiry boundary",
              bell_only_row.id in bell_visible_ids(PROFILE, before_midnight))
        check("N4 Test 15: SAME Bell-only row is EXCLUDED once its N2 expiry boundary passes -- "
              "N2 lifecycle remains the sole, unmodified authority for Bell-only rows too",
              bell_only_row.id not in bell_visible_ids(PROFILE, after_midnight))

        cleanup()

        # ==============================================================
        print("\n=== N4 real-execution smoke test: run_daily_event_job() itself, not just the pure policy ===")
        # ==============================================================
        # Every check above proves the POLICY (attention_policy.py) is
        # correct in isolation. This block proves the WIRING inside
        # services/event_scheduler.py's own STEP 5B (the actual dict
        # keys constructed there -- "n"/"data"/"ntype"/"event_id"/
        # "expires_at"/"android_tag" -- feeding into AttentionCandidate/
        # select_for_push) does not crash and behaves consistently when
        # the REAL function actually runs, not just when its source is
        # inspected. Uses the local DB's own real (small) user set;
        # send_push_notification is monkey-patched to avoid a real FCM
        # call, matching this repo's established test convention of
        # never sending real pushes from a test script.
        import services.event_scheduler as scheduler_module

        sent_calls = []

        def _fake_send_push_notification(*, token, title, body, data, android_tag=None):
            sent_calls.append({"token": token, "title": title, "data": data})
            return True

        original_send = scheduler_module.send_push_notification
        scheduler_module.send_push_notification = _fake_send_push_notification

        smoke_user_id = None
        try:
            db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": PROFILE})
            db.session.commit()
            with db.engine.connect() as conn:
                conn.execute(text(
                    "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token, lagna) "
                    "VALUES (:id, '+05:30', 'free', 0, :token, 'aries')"
                ), {"id": PROFILE, "token": "fake-fcm-attention-policy-smoke"})
                conn.commit()
            smoke_user_id = PROFILE

            os.environ["NOTIFICATION_SLOT"] = "morning"
            try:
                scheduler_module.run_daily_event_job()
            finally:
                os.environ.pop("NOTIFICATION_SLOT", None)

            push_rows = UserNotification.query.filter_by(user_id=PROFILE).filter(
                db.or_(
                    UserNotification.data["delivery_channel"].astext.is_(None),
                    UserNotification.data["delivery_channel"].astext != "bell_only",
                )
            ).all()
            all_rows = UserNotification.query.filter_by(user_id=PROFILE).all()

            check(
                "N4 real execution: run_daily_event_job() completes without raising",
                True,  # reaching this line at all is the assertion
            )
            check(
                f"N4 real execution: at most {DAILY_PUSH_CAP} pushed rows were created for one user in one "
                f"real run, regardless of how many candidates were actually eligible today "
                f"(found {len(push_rows)} pushed, {len(all_rows)} total incl. any bell-only)",
                len(push_rows) <= DAILY_PUSH_CAP,
            )
            check(
                "N4 real execution: send_push_notification was called at most once per pushed row "
                f"(sent_calls={len(sent_calls)}, pushed rows={len(push_rows)})",
                len(sent_calls) == len(push_rows),
            )
        finally:
            scheduler_module.send_push_notification = original_send
            if smoke_user_id is not None:
                db.session.execute(text("DELETE FROM notification_logs WHERE user_id = :p"), {"p": smoke_user_id})
                db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": smoke_user_id})
                db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": smoke_user_id})
                db.session.commit()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
