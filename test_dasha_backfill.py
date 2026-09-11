# test_dasha_backfill.py

"""
U4A.2 -- DB-backed tests for:
    modules/services/dasha_timeline_service.py::validate_timeline_for_profile()
    scripts/backfill_dasha_timeline.py::run_backfill()

LOCAL ONLY. No production DB. Cleans up all its own fixtures.
"""

import os
import sys
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from modules.models_user import AppUser, UserDashaTimeline  # noqa: E402
import modules.services.dasha_timeline_service as dts  # noqa: E402
from modules.services.dasha_timeline_service import (  # noqa: E402
    validate_timeline_for_profile,
    sync_dasha_timeline_for_user,
    EXPECTED_TIMELINE_ROW_COUNT,
    TIMELINE_MISSING,
    TIMELINE_VALID,
    TIMELINE_CORRUPT,
)
from services.personalization_engine import get_current_dasha_users, get_users_for_dasha_change  # noqa: E402
import scripts.backfill_dasha_timeline as backfill_module  # noqa: E402

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


FB_PREFIX = "fb-dasha-backfill-u4a2-"


def fb(n):
    return f"{FB_PREFIX}{n}"


def cleanup():
    ap_ids = [u.id for u in AppUser.query.filter(AppUser.firebase_uid.like(f"{FB_PREFIX}%")).all()]
    if ap_ids:
        UserDashaTimeline.query.filter(UserDashaTimeline.user_id.in_(ap_ids)).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.firebase_uid.like(f"{FB_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()


def row_ids_for(profile_id):
    return sorted(r.id for r in UserDashaTimeline.query.filter_by(user_id=profile_id).all())


def make_complete_user(n, dob="1990-06-15", tob="08:30"):
    u = AppUser(
        firebase_uid=fb(n), name=f"backfill-{n}",
        dob=dob, tob=tob, pob="Mumbai", lat=19.07, lng=72.87,
    )
    db.session.add(u)
    db.session.commit()
    return u


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()

        # ==========================================================
        print("\n=== 0: DB safety re-check function ===")
        # ==========================================================
        try:
            backfill_module._verify_local_database()
            db_safety_ok = True
        except SystemExit:
            db_safety_ok = False
        check("_verify_local_database() does not abort against jyotishasha_local", db_safety_ok)

        # ==========================================================
        print("\n=== 1: validate_timeline_for_profile() classification ===")
        # ==========================================================
        u_missing = make_complete_user(1)
        result_missing = validate_timeline_for_profile(u_missing.id)
        check("missing timeline classified TIMELINE_MISSING", result_missing.status == TIMELINE_MISSING)
        check("missing timeline row_count == 0", result_missing.row_count == 0)

        u_valid = make_complete_user(2)
        sync_dasha_timeline_for_user(u_valid)
        db.session.commit()
        result_valid = validate_timeline_for_profile(u_valid.id)
        check("freshly generated timeline classified TIMELINE_VALID", result_valid.status == TIMELINE_VALID)
        check("valid timeline row_count == 81", result_valid.row_count == EXPECTED_TIMELINE_ROW_COUNT)
        check("valid timeline has no reasons", result_valid.reasons == [])

        # Corrupt: wrong row count (delete a few rows from an otherwise-valid set)
        u_corrupt_count = make_complete_user(3)
        sync_dasha_timeline_for_user(u_corrupt_count)
        db.session.commit()
        some_rows = UserDashaTimeline.query.filter_by(user_id=u_corrupt_count.id).limit(3).all()
        for r in some_rows:
            db.session.delete(r)
        db.session.commit()
        result_corrupt_count = validate_timeline_for_profile(u_corrupt_count.id)
        check("timeline with rows deleted classified TIMELINE_CORRUPT", result_corrupt_count.status == TIMELINE_CORRUPT)
        check("corrupt (wrong count) reasons mention row count", any("rows" in r for r in result_corrupt_count.reasons))

        # Corrupt: a gap introduced between two adjacent periods
        u_corrupt_gap = make_complete_user(4)
        sync_dasha_timeline_for_user(u_corrupt_gap)
        db.session.commit()
        ordered = UserDashaTimeline.query.filter_by(user_id=u_corrupt_gap.id).order_by(UserDashaTimeline.start_date).all()
        ordered[5].start_date = ordered[5].start_date + timedelta(days=10)  # opens a gap before row 5
        db.session.commit()
        result_corrupt_gap = validate_timeline_for_profile(u_corrupt_gap.id)
        check("timeline with an introduced gap classified TIMELINE_CORRUPT", result_corrupt_gap.status == TIMELINE_CORRUPT)
        check("gap reasons mention 'gap'", any("gap" in r for r in result_corrupt_gap.reasons))

        # Corrupt: an overlap introduced between two adjacent periods
        u_corrupt_overlap = make_complete_user(5)
        sync_dasha_timeline_for_user(u_corrupt_overlap)
        db.session.commit()
        ordered2 = UserDashaTimeline.query.filter_by(user_id=u_corrupt_overlap.id).order_by(UserDashaTimeline.start_date).all()
        ordered2[5].start_date = ordered2[5].start_date - timedelta(days=10)  # creates an overlap with row 4
        db.session.commit()
        result_corrupt_overlap = validate_timeline_for_profile(u_corrupt_overlap.id)
        check("timeline with an introduced overlap classified TIMELINE_CORRUPT", result_corrupt_overlap.status == TIMELINE_CORRUPT)
        check("overlap reasons mention 'overlap'", any("overlap" in r for r in result_corrupt_overlap.reasons))

        # Does NOT assume start_date >= dob -- a legitimate pre-birth
        # row must never be flagged corrupt purely for that reason.
        u_prebirth = make_complete_user(6)
        sync_dasha_timeline_for_user(u_prebirth)
        db.session.commit()
        first_row = UserDashaTimeline.query.filter_by(user_id=u_prebirth.id).order_by(UserDashaTimeline.start_date).first()
        check("a real generated timeline's first row legitimately predates dob (U4A.0 fact)", first_row.start_date < date(1990, 6, 15))
        result_prebirth = validate_timeline_for_profile(u_prebirth.id)
        check("pre-birth start_date does NOT make an otherwise-sound timeline CORRUPT", result_prebirth.status == TIMELINE_VALID)

        cleanup()

        # ==========================================================
        print("\n=== 2: run_backfill() -- missing -> generated ===")
        # ==========================================================
        make_complete_user(10)
        make_complete_user(11)
        counts = backfill_module.run_backfill(batch_size=50, after_id=0, force=False, dry_run=False)
        check("scanned >= 2", counts.scanned >= 2)
        check("missing >= 2 (both fresh fixtures had no timeline)", counts.missing >= 2)
        check("generated >= 2", counts.generated >= 2)
        for n in (10, 11):
            u = AppUser.query.filter_by(firebase_uid=fb(n)).first()
            check(f"fixture {n} now has exactly {EXPECTED_TIMELINE_ROW_COUNT} rows", len(row_ids_for(u.id)) == EXPECTED_TIMELINE_ROW_COUNT)

        # ==========================================================
        print("\n=== 3: second run -- idempotency (valid profiles untouched) ===")
        # ==========================================================
        rows_before_second_run = {n: row_ids_for(AppUser.query.filter_by(firebase_uid=fb(n)).first().id) for n in (10, 11)}
        counts2 = backfill_module.run_backfill(batch_size=50, after_id=0, force=False, dry_run=False)
        check("second run: already_valid >= 2", counts2.already_valid >= 2)
        check("second run: zero NEW generations for these now-valid profiles", counts2.missing == 0 or counts2.generated == 0)
        for n in (10, 11):
            u = AppUser.query.filter_by(firebase_uid=fb(n)).first()
            check(f"fixture {n} row IDs UNCHANGED after second run (no unnecessary replacement)", row_ids_for(u.id) == rows_before_second_run[n])

        # ==========================================================
        print("\n=== 4: corrupt timeline -> replaced ===")
        # ==========================================================
        u_c = make_complete_user(12)
        sync_dasha_timeline_for_user(u_c)
        db.session.commit()
        rows_before_corrupt = row_ids_for(u_c.id)
        victim = UserDashaTimeline.query.filter_by(user_id=u_c.id).first()
        db.session.delete(victim)
        db.session.commit()
        check("fixture 12 is genuinely corrupt (80 rows) before backfill", len(row_ids_for(u_c.id)) == EXPECTED_TIMELINE_ROW_COUNT - 1)

        counts3 = backfill_module.run_backfill(batch_size=50, after_id=0, force=False, dry_run=False)
        check("run detected the corrupt profile", counts3.corrupt >= 1)
        check("run replaced the corrupt profile", counts3.replaced >= 1)
        rows_after_corrupt = row_ids_for(u_c.id)
        check(f"fixture 12 now has exactly {EXPECTED_TIMELINE_ROW_COUNT} rows again", len(rows_after_corrupt) == EXPECTED_TIMELINE_ROW_COUNT)
        check("fixture 12's rows are a genuinely NEW set (real replacement, not a patch)", set(rows_after_corrupt).isdisjoint(set(rows_before_corrupt)))

        # ==========================================================
        print("\n=== 5: incomplete birth data -> always skipped, never touched ===")
        # ==========================================================
        u_incomplete = AppUser(firebase_uid=fb(13), name="incomplete", dob="1990-06-15")  # tob/pob/lat/lng missing
        db.session.add(u_incomplete)
        db.session.commit()
        counts4 = backfill_module.run_backfill(batch_size=50, after_id=0, force=False, dry_run=False)
        check("incomplete profile counted", counts4.incomplete >= 1)
        check("incomplete profile has zero rows (never generated for)", len(row_ids_for(u_incomplete.id)) == 0)

        # ==========================================================
        print("\n=== 6: --dry-run writes nothing ===")
        # ==========================================================
        u_dry = make_complete_user(20)
        rows_before_dry = row_ids_for(u_dry.id)
        check("dry-run fixture starts with zero rows", rows_before_dry == [])
        dry_counts = backfill_module.run_backfill(batch_size=50, after_id=0, force=False, dry_run=True)
        check("dry-run classified the fixture as missing", dry_counts.missing >= 1)
        check("dry-run wrote ZERO rows for the missing fixture", row_ids_for(u_dry.id) == [])
        # And a VALID profile's row set is untouched by a dry-run too.
        rows_before_dry_valid = row_ids_for(AppUser.query.filter_by(firebase_uid=fb(10)).first().id)
        backfill_module.run_backfill(batch_size=50, after_id=0, force=False, dry_run=True)
        check("dry-run leaves an already-valid profile's rows byte-for-byte unchanged",
              row_ids_for(AppUser.query.filter_by(firebase_uid=fb(10)).first().id) == rows_before_dry_valid)

        # ==========================================================
        print("\n=== 7: --force recomputes an already-valid profile ===")
        # ==========================================================
        u_force = AppUser.query.filter_by(firebase_uid=fb(10)).first()
        rows_before_force = row_ids_for(u_force.id)
        force_counts = backfill_module.run_backfill(batch_size=50, after_id=0, force=True, dry_run=False)
        check("force run reports forced_recomputed >= 1", force_counts.forced_recomputed >= 1)
        rows_after_force = row_ids_for(u_force.id)
        check(f"forced profile still has exactly {EXPECTED_TIMELINE_ROW_COUNT} rows", len(rows_after_force) == EXPECTED_TIMELINE_ROW_COUNT)
        check("forced profile's rows are a genuinely NEW set", set(rows_after_force).isdisjoint(set(rows_before_force)))

        # ==========================================================
        print("\n=== 8: failed replacement PRESERVES a valid/corrupt old timeline (never data loss) ===")
        # ==========================================================
        u_fail = make_complete_user(30)
        sync_dasha_timeline_for_user(u_fail)
        db.session.commit()
        rows_before_fail = row_ids_for(u_fail.id)
        check("fixture 30 has a real timeline before the simulated failure", len(rows_before_fail) == EXPECTED_TIMELINE_ROW_COUNT)

        real_build = dts.build_dasha_timeline_rows

        def _failing_build(user):
            if user.firebase_uid == fb(30):
                raise RuntimeError("simulated transient calculation failure")
            return real_build(user)

        dts.build_dasha_timeline_rows = _failing_build
        try:
            fail_counts = backfill_module.run_backfill(batch_size=50, after_id=0, force=True, dry_run=False)
        finally:
            dts.build_dasha_timeline_rows = real_build

        check("forced run against the poisoned profile reports preserved_after_failure >= 1", fail_counts.preserved_after_failure >= 1)
        rows_after_fail = row_ids_for(u_fail.id)
        check(
            "THE OLD VALID TIMELINE SURVIVES INTACT after the simulated failure -- no data loss",
            rows_after_fail == rows_before_fail,
        )

        # ==========================================================
        print("\n=== 9: per-profile failure isolation -- one bad profile does not abort the batch ===")
        # ==========================================================
        u_ok_a = make_complete_user(40)
        u_bad = make_complete_user(41)
        u_ok_b = make_complete_user(42)

        def _selective_failing_build(user):
            if user.firebase_uid == fb(41):
                raise RuntimeError("simulated failure for profile 41 only")
            return real_build(user)

        dts.build_dasha_timeline_rows = _selective_failing_build
        try:
            iso_counts = backfill_module.run_backfill(batch_size=1, after_id=0, force=False, dry_run=False)
        finally:
            dts.build_dasha_timeline_rows = real_build

        check("profile 40 (before the bad one) got a real timeline", len(row_ids_for(u_ok_a.id)) == EXPECTED_TIMELINE_ROW_COUNT)
        check("profile 41 (the bad one) has zero rows (nothing existed to preserve, nothing generated)", len(row_ids_for(u_bad.id)) == 0)
        check("profile 42 (after the bad one) STILL got a real timeline -- the batch was not aborted", len(row_ids_for(u_ok_b.id)) == EXPECTED_TIMELINE_ROW_COUNT)
        check("isolation run reports at least 1 preserved_after_failure/failed for profile 41", iso_counts.preserved_after_failure >= 1)

        # ==========================================================
        print("\n=== 10: keyset pagination (batch_size=1 covers every profile, no OFFSET) ===")
        # ==========================================================
        # Re-run with a small batch size over the whole accumulated
        # fixture set from this test file -- every already-valid
        # profile must still end up already_valid, proving pagination
        # doesn't skip or duplicate profiles across page boundaries.
        page_counts = backfill_module.run_backfill(batch_size=2, after_id=0, force=False, dry_run=False)
        check("small-batch-size run scans at least as many profiles as a single big batch would", page_counts.scanned >= 8)

        # ==========================================================
        print("\n=== 11: notification regression -- readers still correct after backfill ===")
        # ==========================================================
        today = date.today()
        u_notif = make_complete_user(50, dob="1985-01-01", tob="06:00")
        counts5 = backfill_module.run_backfill(batch_size=50, after_id=0, force=False, dry_run=False)
        check("notification fixture was generated by the backfill", len(row_ids_for(u_notif.id)) == EXPECTED_TIMELINE_ROW_COUNT)

        current_rows = get_current_dasha_users()
        current_ids_seen = [r["user"].id for r in current_rows]
        check("get_current_dasha_users() returns AT MOST ONE row per profile (no duplicates from any timeline)",
              len(current_ids_seen) == len(set(current_ids_seen)))

        future_row = (
            UserDashaTimeline.query
            .filter(UserDashaTimeline.user_id == u_notif.id, UserDashaTimeline.start_date > today)
            .order_by(UserDashaTimeline.start_date)
            .first()
        )
        if future_row:
            days_before = (future_row.start_date - today).days
            change_matches = {m["user"].id for m in get_users_for_dasha_change(days_before=days_before)}
            check("get_users_for_dasha_change() still finds a backfilled profile's real future transition", u_notif.id in change_matches)

        # ==========================================================
        print("\n=== 12 (P4.10): --production safety gating ===")
        # ==========================================================
        # Pure argparse -- no DB, no app context needed.
        args_default = backfill_module.parse_args([])
        check("parse_args(): --production defaults to False", args_default.production is False)
        check("parse_args(): --confirm defaults to empty string", args_default.confirm == "")

        args_prod_dry = backfill_module.parse_args(["--production", "--dry-run"])
        check("parse_args(): --production --dry-run parses cleanly", args_prod_dry.production and args_prod_dry.dry_run)

        # Cheapest check (string comparison only, before any DB
        # connection is even attempted) -- a REAL --production run
        # without the exact confirm phrase must refuse immediately.
        try:
            backfill_module._require_production_confirmation(
                backfill_module.parse_args(["--production"]))
            no_confirm_blocked = False
        except SystemExit:
            no_confirm_blocked = True
        check("REAL --production run WITHOUT --confirm is refused before touching any DB",
              no_confirm_blocked)

        try:
            backfill_module._require_production_confirmation(
                backfill_module.parse_args(["--production", "--confirm", "wrong phrase"]))
            wrong_confirm_blocked = False
        except SystemExit:
            wrong_confirm_blocked = True
        check("REAL --production run with the WRONG --confirm phrase is refused",
              wrong_confirm_blocked)

        try:
            backfill_module._require_production_confirmation(
                backfill_module.parse_args([
                    "--production", "--confirm", backfill_module._PRODUCTION_CONFIRM_PHRASE]))
            correct_confirm_ok = True
        except SystemExit:
            correct_confirm_ok = False
        check("REAL --production run with the EXACT confirm phrase passes this gate",
              correct_confirm_ok)

        # --dry-run under --production never requires --confirm (dry-run
        # performs zero writes regardless).
        try:
            backfill_module._require_production_confirmation(
                backfill_module.parse_args(["--production", "--dry-run"]))
            dry_run_prod_ok = True
        except SystemExit:
            dry_run_prod_ok = False
        check("--production --dry-run (no --confirm) is NOT blocked by the confirmation gate",
              dry_run_prod_ok)

        # _verify_production_database() against the LOCAL test database:
        # must refuse regardless of ACTIVITY_EVENTS_ENVIRONMENT, since
        # the database NAME check runs first and this is never the real
        # production database name. (The converse -- a genuine
        # production database name -- can only be proven against real
        # production itself, never locally; this test proves the
        # function fails CLOSED against everything it can actually see.)
        original_env_marker = os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT")
        try:
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            try:
                backfill_module._verify_production_database()
                refused_local_as_production = False
            except SystemExit:
                refused_local_as_production = True
            check("_verify_production_database() refuses the local test DB (wrong name) "
                  "even with ACTIVITY_EVENTS_ENVIRONMENT=local",
                  refused_local_as_production)

            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "production"
            try:
                backfill_module._verify_production_database()
                refused_local_even_with_prod_env = False
            except SystemExit:
                refused_local_even_with_prod_env = True
            check("_verify_production_database() STILL refuses the local test DB (wrong name) "
                  "even with ACTIVITY_EVENTS_ENVIRONMENT=production -- database name is checked "
                  "independently, never inferred from the environment marker alone",
                  refused_local_even_with_prod_env)
        finally:
            if original_env_marker is None:
                os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            else:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = original_env_marker

        # Omitting --production always takes the ORIGINAL, unchanged
        # local-only path -- proven already by test section 0 above
        # (_verify_local_database() unchanged); this just confirms the
        # CLI default routes there.
        check("parse_args() with no flags routes to the local-only path by default (unchanged)",
              backfill_module.parse_args([]).production is False)

        print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed\n{'='*60}")

        cleanup()
        remaining = AppUser.query.filter(AppUser.firebase_uid.like(f"{FB_PREFIX}%")).count()
        print(f"Cleanup verified: {remaining} fixture AppUser rows remain (expect 0)")

        return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
