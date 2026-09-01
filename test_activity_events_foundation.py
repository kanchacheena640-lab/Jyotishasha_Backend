"""
test_activity_events_foundation.py
-------------------------------------------------
Focused tests for Phase 2 Step 2's activity_events foundation:
modules/models_activity_events.py, modules/activity_events/
event_schemas.py, modules/activity_events/service.py. NOT wired into
any producer yet -- these tests exercise the foundation in isolation.

Two sections, both run by this file's __main__:

SECTION A: validation/static/foundation checks that do NOT require the
activity_events table to actually exist in Postgres -- model
construction, the validator (pure Python, no DB at all), and the write
helper's failure-swallowing behavior (proved against a deliberately
unreachable database, not the real one -- see
test_record_event_swallows_db_failure(), which needs no live table and
touches no real data).

Each scenario that needs to observe import-time/module-level state (the
DB-failure-swallowing test, and the "no User/AppUser coupling" test)
runs in its OWN fresh subprocess, mirroring this repo's own convention
in test_subscription_state_sync_appuser_mapper.py -- import order can
only be tested honestly in a clean process.

SECTION B: local PostgreSQL-backed persistence/integration checks
against the real activity_events table (duplicate/null dedupe_key
handling enforced by the actual partial unique index, true NULL-column
persistence, JSONB round-tripping, and the record_event() smoke test).
Connects ONLY to jyotishasha_local, following this repo's usual
convention (see test_app_version_policy.py) -- refuses to run against
anything else, and cleans up every row it creates.

LOCAL ONLY. No production DB touched by any part of this file --
Section A never connects to any database at all; Section B connects
only to jyotishasha_local, verified by its own safety check before it
writes anything.
"""

import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

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


def run_subprocess(label, code):
    """Runs `code` in a brand-new Python process (no ambient app/DB
    imports leak in), mirroring test_subscription_state_sync_
    appuser_mapper.py's own precedent for import-order-sensitive
    checks. Returns (passed, stdout+stderr)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    ok = result.returncode == 0
    if not ok:
        print(f"  --- {label} subprocess output ---")
        print(result.stdout)
        print(result.stderr)
    return ok


# =====================================================================
# 1 (construction half) / 3 / 4 -- valid event constructs; optional
# session_id / profile_id are genuinely nullable, never fabricated.
# =====================================================================
def test_model_construction_and_optional_nulls():
    from modules.models_activity_events import ActivityEvent
    import datetime

    event = ActivityEvent(
        event_name="login_completed",
        event_version=1,
        occurred_at=datetime.datetime.now(datetime.timezone.utc),
        platform="app_android",
        environment="production",
        properties={"method": "google"},
        # firebase_uid / profile_id / anonymous_id / session_id /
        # correlation_id / entity_type / entity_id / dedupe_key all
        # deliberately omitted.
    )
    check("ActivityEvent constructs with required fields only", event.event_name == "login_completed")
    check("session_id is None when not supplied (never fabricated)", event.session_id is None)
    check("profile_id is None when not supplied (never fabricated)", event.profile_id is None)
    check("firebase_uid is None when not supplied", event.firebase_uid is None)
    check("anonymous_id is None when not supplied", event.anonymous_id is None)
    check("dedupe_key is None when not supplied", event.dedupe_key is None)
    check("properties round-trips as given", event.properties == {"method": "google"})


# =====================================================================
# 2 -- recorded_at cannot be caller-controlled through the helper.
# =====================================================================
def test_recorded_at_not_caller_controllable():
    import inspect
    from modules.activity_events.service import record_event

    sig = inspect.signature(record_event)
    check("record_event() has no recorded_at parameter", "recorded_at" not in sig.parameters)

    raised = False
    try:
        record_event(
            event_name="login_completed",
            occurred_at="2026-01-01T00:00:00Z",
            platform="app_android",
            recorded_at="2020-01-01T00:00:00Z",  # not a real parameter
        )
    except TypeError:
        raised = True
    check("passing recorded_at= raises TypeError (unexpected keyword)", raised)


# =====================================================================
# 7 -- unknown event_name is rejected by the helper (raises, not silent).
# =====================================================================
def test_unknown_event_name_rejected():
    import datetime
    from modules.activity_events.service import record_event

    raised = False
    try:
        record_event(
            event_name="this_event_does_not_exist_in_the_frozen_registry",
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
            platform="app_android",
        )
    except ValueError:
        raised = True
    check("unknown event_name raises ValueError before any DB attempt", raised)


# =====================================================================
# 8 -- unknown property key is dropped, not stored.
# =====================================================================
def test_unknown_property_key_dropped():
    from modules.activity_events.event_schemas import sanitize_properties

    clean, dropped = sanitize_properties(
        "login_completed", 1, {"method": "google", "totally_made_up_key": "x"}
    )
    check("known key kept", clean.get("method") == "google")
    check("unknown key dropped from the stored dict", "totally_made_up_key" not in clean)
    check("unknown key reported in dropped list", "totally_made_up_key" in dropped)


# =====================================================================
# 9 -- forbidden Ask Now question/answer text cannot be persisted, even
# alongside a legitimately allowed key on the same event.
# =====================================================================
def test_asknow_question_answer_text_forbidden():
    from modules.activity_events.event_schemas import sanitize_properties

    clean, dropped = sanitize_properties(
        "asknow_question_submitted",
        1,
        {"source": "free", "question": "what does my chart say about marriage"},
    )
    check("legitimate source key kept", clean.get("source") == "free")
    check("raw question text never kept", "question" not in clean)
    check("question key reported as dropped", "question" in dropped)

    clean2, dropped2 = sanitize_properties(
        "asknow_answer_delivered", 1, {"source": "pack", "answer": "your chart shows..."}
    )
    check("raw answer text never kept", "answer" not in clean2)
    check("answer key reported as dropped", "answer" in dropped2)


# =====================================================================
# 10 -- forbidden PII/token-like fields cannot be persisted, whether by
# key name (even if the key were otherwise allowlisted) or by value
# shape (an email/phone-looking string in an allowed key).
# =====================================================================
def test_forbidden_pii_and_tokens_dropped():
    from modules.activity_events.event_schemas import sanitize_properties

    clean, dropped = sanitize_properties(
        "login_completed",
        1,
        {"method": "google", "email": "user@example.com", "auth_token": "abc.def.ghi"},
    )
    check("email key dropped by name", "email" not in clean and "email" in dropped)
    check("auth_token key dropped by name", "auth_token" not in clean and "auth_token" in dropped)

    # Value-shape backstop: an allowlisted key holding a PII-shaped value.
    clean2, dropped2 = sanitize_properties(
        "cta_click", 1, {"cta_id": "user@example.com", "screen_name": "home"}
    )
    check("allowlisted key dropped when its VALUE looks like an email", "cta_id" not in clean2)
    # Regression: an early denylist used a bare "name" substring, which
    # also matched legitimate keys like screen_name/feature_name --
    # narrowed to actual person-name shapes. See _FORBIDDEN_NAME_KEY_
    # SUBSTRINGS in event_schemas.py.
    check("legitimate *_name key (screen_name) is NOT treated as a forbidden person-name field", clean2.get("screen_name") == "home")
    clean3, _ = sanitize_properties("feature_used", 1, {"feature_name": "panchang"})
    check("legitimate *_name key (feature_name) is NOT treated as a forbidden person-name field", clean3.get("feature_name") == "panchang")


# =====================================================================
# 11 / 12 -- campaign_context / notification_context keep only their
# frozen, contract-wide allowed keys.
# =====================================================================
def test_campaign_and_notification_context_allowlists():
    from modules.activity_events.event_schemas import (
        sanitize_campaign_context,
        sanitize_notification_context,
    )

    clean, dropped = sanitize_campaign_context(
        {"utm_source": "google", "utm_medium": "cpc", "visitor_email": "x@y.com"}
    )
    check("utm_source kept", clean.get("utm_source") == "google")
    check("utm_medium kept", clean.get("utm_medium") == "cpc")
    check("unknown/forbidden key dropped from campaign_context", "visitor_email" not in clean and "visitor_email" in dropped)

    clean2, dropped2 = sanitize_notification_context(
        {"notification_id": "n-123", "slot": "morning", "user_phone": "+911234567890"}
    )
    check("notification_id kept", clean2.get("notification_id") == "n-123")
    check("slot kept", clean2.get("slot") == "morning")
    check("unknown/forbidden key dropped from notification_context", "user_phone" not in clean2 and "user_phone" in dropped2)


# =====================================================================
# Phase 3 Step 6 -- sanitize_*'s phone value-shape check must drop
# genuine phone-shaped values but NOT a bare short numeric identifier
# (the demonstrated "20260901" false positive) or an ordinary UUID.
# Tests the actual sanitizer OUTPUT (sanitize_properties/campaign/
# notification), not the regex directly -- proving the fix as end
# users of this module actually observe it.
# =====================================================================
def test_phone_value_shape_detection_after_step6_fix():
    from modules.activity_events.event_schemas import sanitize_properties, sanitize_campaign_context, sanitize_notification_context

    genuine_phones = [
        "9876543210",
        "+919876543210",
        "+91 9876543210",
        "98765 43210",
        "98765-43210",
    ]
    for phone in genuine_phones:
        clean, dropped = sanitize_properties("cta_click", 1, {"cta_id": phone, "screen_name": "home"})
        check(f"genuine phone {phone!r} dropped by sanitize_properties", "cta_id" not in clean and "cta_id" in dropped)
        check(f"unrelated key unaffected while dropping {phone!r}", clean.get("screen_name") == "home")

    # The demonstrated false positive -- must now survive.
    clean, dropped = sanitize_properties("cta_click", 1, {"cta_id": "20260901", "screen_name": "home"})
    check("bare 8-digit date-like value ('20260901') is NOT dropped as phone-like", clean.get("cta_id") == "20260901")
    check("'20260901' not reported as dropped", "cta_id" not in dropped)

    # Ordinary UUID preserved (was already safe before this fix -- confirms no regression).
    uuid_value = "550e8400-e29b-41d4-a716-446655440000"
    clean, _ = sanitize_properties("cta_click", 1, {"cta_id": uuid_value, "screen_name": "home"})
    check("ordinary UUID value preserved", clean.get("cta_id") == uuid_value)

    # Ordinary analytics strings preserved.
    clean, _ = sanitize_properties("feature_used", 1, {"feature_name": "panchang"})
    check("ordinary analytics string ('panchang') preserved", clean.get("feature_name") == "panchang")

    # Embedded email still filtered -- unrelated to this fix, must be unchanged.
    clean, dropped = sanitize_properties("login_completed", 1, {"method": "user@example.com"})
    check("embedded email value still dropped (unaffected by the phone-only fix)", "method" not in clean)

    # Forbidden sensitive KEYS still filtered -- unrelated to this fix, must be unchanged.
    clean, dropped = sanitize_properties("login_completed", 1, {"method": "google", "auth_token": "abc.def.ghi"})
    check("forbidden key name (auth_token) still dropped (unaffected by the phone-only fix)", "auth_token" not in clean and "auth_token" in dropped)
    check("legitimate key (method) unaffected", clean.get("method") == "google")

    # Same fix applies uniformly to campaign_context and notification_context
    # (all three share the one _value_looks_like_pii() helper).
    clean_cc, dropped_cc = sanitize_campaign_context({"utm_source": "9876543210"})
    check("genuine phone dropped from campaign_context too", "utm_source" not in clean_cc)
    clean_cc2, _ = sanitize_campaign_context({"utm_campaign": "20260901"})
    check("'20260901' preserved in campaign_context too", clean_cc2.get("utm_campaign") == "20260901")

    clean_nc, dropped_nc = sanitize_notification_context({"notification_id": "9876543210"})
    check("genuine phone dropped from notification_context too", "notification_id" not in clean_nc)
    clean_nc2, _ = sanitize_notification_context({"notification_id": uuid_value})
    check("UUID notification_id preserved in notification_context", clean_nc2.get("notification_id") == uuid_value)


# =====================================================================
# 13 -- a ledger DB failure never propagates as a business exception.
# Runs against a DELIBERATELY UNREACHABLE database -- never touches
# jyotishasha_local or any real data. Isolated subprocess: builds its
# own tiny Flask+SQLAlchemy app bound to a bad URL, never imports
# app.py, so this can never trip factory.py's db.create_all().
# =====================================================================
_DB_FAILURE_SWALLOW_CODE = """
import datetime
from flask import Flask
from extensions import db
from modules.activity_events.service import record_event

import os as _os
_os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"  # so this test exercises the DB-failure path specifically, not environment misconfiguration

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://baduser:badpass@localhost:59999/does_not_exist"
db.init_app(app)

with app.app_context():
    result = record_event(
        event_name="login_completed",
        occurred_at=datetime.datetime.now(datetime.timezone.utc),
        platform="app_android",
        properties={"method": "google"},
    )
    assert result.status == "write_failed", f"expected write_failed, got {result.status!r}"
    assert result.ok is False
print("SWALLOWED_OK")
"""


def test_record_event_swallows_db_failure():
    ok = run_subprocess("db-failure-swallow", _DB_FAILURE_SWALLOW_CODE)
    check("record_event() swallows a real DB connection failure and returns write_failed (never raises)", ok)


# =====================================================================
# 14 -- no coupling to User/AppUser: importing the ledger foundation
# never imports the account/profile models as a side effect.
# =====================================================================
_NO_PRODUCT_MODEL_COUPLING_CODE = """
import sys
import modules.activity_events.service  # noqa: F401
assert "modules.auth.models" not in sys.modules, "service.py must never import the User model"
assert "modules.models_user" not in sys.modules, "service.py must never import the AppUser model"
print("NO_COUPLING_OK")
"""


def test_no_user_or_appuser_import_coupling():
    ok = run_subprocess("no-product-model-coupling", _NO_PRODUCT_MODEL_COUPLING_CODE)
    check("importing the ledger foundation never imports User or AppUser", ok)


# =====================================================================
# SECTION B -- requires the real activity_events table. Only runs after
# the reviewed migration has actually been applied (Phase 2 Step 2B).
# Connects ONLY to jyotishasha_local, refuses to run against anything
# else -- same convention as test_app_version_policy.py.
# =====================================================================
LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"


def run_db_backed_persistence_tests():
    """Items 1 (persisted half) / 3 / 4 (persisted half) / 5 / 6 / 9
    (persisted half) / 10 (persisted half) / 14 (DB half). Every row
    this creates is deleted in a `finally` block, keyed by its own
    event_id -- never a broad DELETE, never touches unrelated data."""
    import datetime
    import uuid as uuid_mod

    os.environ["DATABASE_URL"] = LOCAL_DB_URL
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
    os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

    from app import app
    from extensions import db
    from sqlalchemy import text
    from modules.activity_events.service import record_event

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        users_before = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        app_users_before = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()

        marker = f"phase2-step2b-test-{uuid_mod.uuid4().hex[:8]}"
        created_ids = []

        def now():
            return datetime.datetime.now(datetime.timezone.utc)

        try:
            # -- 1/3/4/9/10 (persisted half): valid event persists;
            # optional session_id/profile_id read back as real SQL
            # NULL; JSONB round-trips; forbidden key never reaches the
            # row; legitimate key does.
            r1 = record_event(
                event_name="asknow_question_submitted",
                occurred_at=now(),
                platform="app_android",
                properties={"source": "free", "question": "raw question text must never reach the DB"},
            )
            check("record_event() returns status=written for a valid event", r1.status == "written")
            created_ids.append(r1.event.event_id)

            row = db.session.execute(
                text("SELECT * FROM activity_events WHERE event_id = :id"),
                {"id": str(r1.event.event_id)},
            ).fetchone()
            check("row actually exists in Postgres after record_event()", row is not None)
            check("optional session_id persists as real SQL NULL", row.session_id is None)
            check("optional profile_id persists as real SQL NULL", row.profile_id is None)
            check("legitimate properties key ('source') persisted via JSONB", row.properties.get("source") == "free")
            check("forbidden properties key ('question') never reached the row", "question" not in row.properties)
            check("recorded_at was populated by the server", row.recorded_at is not None)
            check("recorded_at differs from the caller-supplied occurred_at value (proves it's not caller-controlled)",
                  row.recorded_at.replace(tzinfo=datetime.timezone.utc) != r1.event.occurred_at)

            # -- 6: multiple NULL dedupe_key events all succeed as
            # distinct rows (the partial index must never block this).
            r2 = record_event(
                event_name="cta_click", occurred_at=now(), platform="app_android",
                properties={"cta_id": marker, "screen_name": "smoke_a"},
            )
            r3 = record_event(
                event_name="cta_click", occurred_at=now(), platform="app_android",
                properties={"cta_id": marker, "screen_name": "smoke_b"},
            )
            for r in (r2, r3):
                check("event with dedupe_key=None writes successfully", r.status == "written")
                created_ids.append(r.event.event_id)
            check("two dedupe_key=None events produced two distinct rows", r2.event.event_id != r3.event.event_id)

            # -- 5: duplicate non-null dedupe_key is safely handled --
            # first write succeeds, second is skipped (not written, not
            # raised), and only one row ever exists for that key.
            dk = f"{marker}-dedupe"
            r4 = record_event(
                event_name="cta_click", occurred_at=now(), platform="app_android",
                properties={"cta_id": marker, "screen_name": "dup1"}, dedupe_key=dk,
            )
            check("first write with a new dedupe_key succeeds", r4.status == "written")
            created_ids.append(r4.event.event_id)

            r5 = record_event(
                event_name="cta_click", occurred_at=now(), platform="app_android",
                properties={"cta_id": marker, "screen_name": "dup2"}, dedupe_key=dk,
            )
            check("second write with the SAME dedupe_key is skipped, not written", r5.status == "skipped_duplicate_dedupe_key")

            dup_count = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"), {"dk": dk}
            ).scalar()
            check("only ONE row exists in Postgres for that dedupe_key (partial unique index enforced it)", dup_count == 1)

            # -- 14 (DB half): no User/AppUser row was created or
            # modified as a side effect of any of the above.
            users_after = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            app_users_after = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()
            check("users row count unchanged by any activity_events write", users_after == users_before)
            check("app_users row count unchanged by any activity_events write", app_users_after == app_users_before)

        finally:
            # Deleted one at a time, by primary key, rather than an
            # ANY(ARRAY[...]) construct -- simpler and already proven to
            # work against the uuid column (the same plain `= :id`
            # comparison this function already uses successfully above).
            if created_ids:
                for eid in created_ids:
                    db.session.execute(
                        text("DELETE FROM activity_events WHERE event_id = :id"),
                        {"id": str(eid)},
                    )
                db.session.commit()
                remaining = 0
                for eid in created_ids:
                    remaining += db.session.execute(
                        text("SELECT COUNT(*) FROM activity_events WHERE event_id = :id"),
                        {"id": str(eid)},
                    ).scalar()
                check(f"all {len(created_ids)} test rows cleaned up (0 remain)", remaining == 0)


def run_environment_contract_tests():
    """Phase 4 prerequisite fix: proves ACTIVITY_EVENTS_ENVIRONMENT is
    never silently resolved to "production" -- missing or invalid
    values fail the analytics write safely (write_failed, no exception,
    no row persisted), explicit valid values persist exactly as given,
    and none of this disturbs existing dedupe or ordinary-write
    behavior. Saves and restores the env var exactly as found."""
    import datetime

    os.environ["DATABASE_URL"] = LOCAL_DB_URL
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")

    from app import app
    from extensions import db
    from sqlalchemy import text
    from modules.activity_events.service import (
        record_event,
        _resolve_environment,
        EnvironmentConfigurationError,
    )

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        original_env = os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT")
        created_ids = []

        def now():
            return datetime.datetime.now(datetime.timezone.utc)

        try:
            # A. Explicit local -> persisted exactly as given.
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            check("_resolve_environment() returns 'local' when explicitly set", _resolve_environment() == "local")
            r1 = record_event(event_name="login_completed", occurred_at=now(), platform="app_android", properties={"method": "google"})
            check("A: explicit local -> written", r1.status == "written")
            created_ids.append(r1.event.event_id)
            row1 = db.session.execute(text("SELECT environment FROM activity_events WHERE event_id = :id"), {"id": str(r1.event.event_id)}).fetchone()
            check("A: persisted environment == 'local'", row1.environment == "local")

            # B. Explicit production -> persisted exactly as given.
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "production"
            check("_resolve_environment() returns 'production' when explicitly set", _resolve_environment() == "production")
            r2 = record_event(event_name="login_completed", occurred_at=now(), platform="app_android", properties={"method": "google"})
            check("B: explicit production -> written", r2.status == "written")
            created_ids.append(r2.event.event_id)
            row2 = db.session.execute(text("SELECT environment FROM activity_events WHERE event_id = :id"), {"id": str(r2.event.event_id)}).fetchone()
            check("B: persisted environment == 'production'", row2.environment == "production")

            # C. Missing variable -> never production, controlled failure, no exception.
            os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            raised = False
            try:
                _resolve_environment()
            except EnvironmentConfigurationError:
                raised = True
            check("C: _resolve_environment() raises EnvironmentConfigurationError when unset", raised)

            count_before_c = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            no_exception = True
            r3 = None
            try:
                r3 = record_event(event_name="login_completed", occurred_at=now(), platform="app_android", properties={"method": "google"})
            except Exception:
                no_exception = False
            check("C: record_event() does not raise when the env var is missing", no_exception)
            check("C: record_event() reports write_failed when the env var is missing", r3 is not None and r3.status == "write_failed")
            count_after_c = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            check("C: no row persisted when the env var is missing (never silently 'production')", count_after_c == count_before_c)

            # D. Invalid value -> controlled failure, no row persisted.
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "staging"  # deliberately not in ALLOWED_ENVIRONMENTS
            raised_d = False
            try:
                _resolve_environment()
            except EnvironmentConfigurationError:
                raised_d = True
            check("D: _resolve_environment() raises for an invalid value ('staging')", raised_d)

            count_before_d = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            r4 = record_event(event_name="login_completed", occurred_at=now(), platform="app_android", properties={"method": "google"})
            check("D: record_event() reports write_failed for an invalid value", r4.status == "write_failed")
            count_after_d = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            check("D: no row persisted for an invalid value", count_after_d == count_before_d)

            # F. Existing dedupe behavior unaffected by this fix.
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            dk = f"env-contract-dedupe-{now().timestamp()}"
            r5 = record_event(event_name="cta_click", occurred_at=now(), platform="app_android", properties={"cta_id": "x", "screen_name": "home"}, dedupe_key=dk)
            check("F: first write with a dedupe_key still succeeds", r5.status == "written")
            created_ids.append(r5.event.event_id)
            r6 = record_event(event_name="cta_click", occurred_at=now(), platform="app_android", properties={"cta_id": "x", "screen_name": "home"}, dedupe_key=dk)
            check("F: duplicate dedupe_key still reported as skipped_duplicate_dedupe_key", r6.status == "skipped_duplicate_dedupe_key")

            # G. Existing valid event recording unaffected by this fix.
            r7 = record_event(event_name="session_start", occurred_at=now(), platform="app_android", properties={"entry_point": "home"})
            check("G: ordinary valid event recording still succeeds", r7.status == "written")
            created_ids.append(r7.event.event_id)

        finally:
            for eid in created_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": str(eid)})
            db.session.commit()
            remaining = 0
            for eid in created_ids:
                remaining += db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE event_id = :id"), {"id": str(eid)}).scalar()
            check(f"all {len(created_ids)} environment-contract test rows cleaned up (0 remain)", remaining == 0)

            # Restore exactly as found, per instruction.
            if original_env is None:
                os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            else:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = original_env


def run_smoke_test():
    """Step 2B item 6 -- one controlled, isolated smoke test through
    record_event() using session_start: Core/behavioral, client-owned,
    no business/financial meaning, cannot touch payments, subscriptions,
    Ask Now credits, report purchases, or notifications. Proves
    record_event() -> exactly one activity_events row, then cleans up
    that row itself (kept separate from run_db_backed_persistence_tests
    so this result is independently visible)."""
    import datetime

    os.environ["DATABASE_URL"] = LOCAL_DB_URL
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
    os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

    from app import app
    from extensions import db
    from sqlalchemy import text
    from modules.activity_events.service import record_event

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        users_before = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        app_users_before = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()
        count_before = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()

        result = record_event(
            event_name="session_start",
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
            platform="app_android",
            properties={"entry_point": "phase2-step2b-smoke-test"},
        )
        check("smoke test: record_event(session_start) returns status=written", result.status == "written")

        count_after = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
        check("smoke test: exactly one new activity_events row was created", count_after == count_before + 1)

        users_after = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        app_users_after = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()
        check("smoke test: no product/business table (users) changed", users_after == users_before)
        check("smoke test: no product/business table (app_users) changed", app_users_after == app_users_before)

        db.session.execute(
            text("DELETE FROM activity_events WHERE event_id = :id"),
            {"id": str(result.event.event_id)},
        )
        db.session.commit()
        remaining = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
        check("smoke test row cleaned up", remaining == count_before)


def main():
    print("Section A -- no DB required")
    test_model_construction_and_optional_nulls()
    test_recorded_at_not_caller_controllable()
    test_unknown_event_name_rejected()
    test_unknown_property_key_dropped()
    test_asknow_question_answer_text_forbidden()
    test_forbidden_pii_and_tokens_dropped()
    test_campaign_and_notification_context_allowlists()
    test_phone_value_shape_detection_after_step6_fix()
    test_record_event_swallows_db_failure()
    test_no_user_or_appuser_import_coupling()

    print("\nSection B -- real jyotishasha_local, activity_events table required")
    run_db_backed_persistence_tests()

    print("\nEnvironment contract (Phase 4 prerequisite fix)")
    run_environment_contract_tests()

    print("\nSmoke test -- one isolated record_event() call")
    run_smoke_test()

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
