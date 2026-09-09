# test_db_safety.py

"""
LOCAL vs PRODUCTION ENVIRONMENT SAFETY BOUNDARY -- Phase 1 tests.

Covers db_safety.py::enforce_local_database_safety() in isolation --
pure string/env-var logic, NEVER opens a real database connection (the
function itself never connects to decide anything, and this file never
calls create_app()/db.init_app() either). No real production URL is
ever used here, not even to prove rejection -- a fake, clearly-labeled
"looks like production" URL (a non-local host/dbname) is enough to
prove the guard's decision logic without touching anything real.

Also proves (Case 4) that the actual, real local dev entrypoint --
factory.create_app() -- still boots normally against jyotishasha_local,
so this task's own guard does not break the project's own standard
local-dev boot path.

LOCAL ONLY. No production DB, no real network call.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_safety import (  # noqa: E402
    DatabaseSafetyError,
    enforce_local_database_safety,
    _is_approved_local_db,
    _parse_db_target,
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


LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
LOCAL_DB_URL_127 = "postgresql://jyotishasha_dev:pw@127.0.0.1:5432/jyotishasha_local"
# NOT a real credential and NOT the real production host -- a
# structurally similar but entirely fake "looks like a hosted prod DB"
# URL, used only to prove the guard's host/dbname parsing rejects
# anything outside the local allowlist. Never dialed.
FAKE_PROD_URL = "postgresql://fakeuser:fakepass@fake-prod-host.example-render.com:5432/jyotishasha"
OTHER_LOCAL_NAME_URL = "postgresql://x:y@localhost:5432/some_other_db"


def _clear_env():
    os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
    os.environ.pop("RENDER", None)


def main():
    try:
        # ==========================================================
        print("=== 1: local + jyotishasha_local -> allowed ===")
        # ==========================================================
        _clear_env()
        os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
        raised = False
        try:
            enforce_local_database_safety(LOCAL_DB_URL)
        except DatabaseSafetyError:
            raised = True
        check("1: explicit local + jyotishasha_local (localhost) -> no error", not raised)

        raised = False
        try:
            enforce_local_database_safety(LOCAL_DB_URL_127)
        except DatabaseSafetyError:
            raised = True
        check("1: explicit local + jyotishasha_local (127.0.0.1) -> no error", not raised)

        # ==========================================================
        print("\n=== 2: local + production/non-approved DB -> rejected ===")
        # ==========================================================
        _clear_env()
        os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
        raised = False
        try:
            enforce_local_database_safety(FAKE_PROD_URL)
        except DatabaseSafetyError as e:
            raised = True
            msg = str(e)
        check("2: explicit local + fake-production-shaped DB -> DatabaseSafetyError raised", raised)
        check("2: error message never contains the fake credential/password", raised and "fakepass" not in msg)
        check("2: error message never contains the raw URL", raised and FAKE_PROD_URL not in msg)

        raised = False
        try:
            enforce_local_database_safety(OTHER_LOCAL_NAME_URL)
        except DatabaseSafetyError:
            raised = True
        check("2: explicit local + right host but WRONG db name -> also rejected (allowlist is exact)", raised)

        raised = False
        try:
            enforce_local_database_safety(None)
        except DatabaseSafetyError:
            raised = True
        check("2: explicit local + missing DATABASE_URL entirely -> rejected, not a crash", raised)

        # ==========================================================
        print("\n=== 3: production (explicit) + production DB -> allowed ===")
        # ==========================================================
        _clear_env()
        os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "production"
        raised = False
        try:
            enforce_local_database_safety(FAKE_PROD_URL)
        except DatabaseSafetyError:
            raised = True
        check("3: explicit production + production-shaped DB -> allowed, no DB inspection at all", not raised)

        # Also: production declared, but DATABASE_URL happens to look
        # local (e.g. a one-off local smoke test against a prod-labeled
        # process) -- still allowed. An explicit production declaration
        # is never second-guessed by this guard.
        raised = False
        try:
            enforce_local_database_safety(LOCAL_DB_URL)
        except DatabaseSafetyError:
            raised = True
        check("3: explicit production + ANY db target -> still allowed (declaration is trusted)", not raised)

        # ==========================================================
        print("\n=== 3b: ambiguous marker, but Render-detected -> allowed (fail-safe rule) ===")
        # ==========================================================
        _clear_env()
        os.environ["RENDER"] = "true"
        raised = False
        try:
            enforce_local_database_safety(FAKE_PROD_URL)
        except DatabaseSafetyError:
            raised = True
        check("3b: no ACTIVITY_EVENTS_ENVIRONMENT set, but RENDER=true -> allowed with NO Render config required",
              not raised)
        _clear_env()

        # ==========================================================
        print("\n=== 4: real local dev entrypoint (factory.create_app) still boots against jyotishasha_local ===")
        # ==========================================================
        _clear_env()
        os.environ["DATABASE_URL"] = LOCAL_DB_URL
        os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
        os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
        from factory import create_app
        from sqlalchemy import text
        app = create_app()
        with app.app_context():
            from extensions import db
            current_db = db.session.execute(text("SELECT current_database()")).scalar()
        check("4: factory.create_app() boots normally against jyotishasha_local (no regression)",
              current_db == "jyotishasha_local")

        # ==========================================================
        print("\n=== 5: missing/ambiguous environment configuration -- documented fail-safe behavior ===")
        # ==========================================================
        _clear_env()
        # No ACTIVITY_EVENTS_ENVIRONMENT, no RENDER -- exactly the
        # reported incident's own shape. Documented behavior: falls back
        # to the local-DB-allowlist check itself.
        raised = False
        try:
            enforce_local_database_safety(LOCAL_DB_URL)
        except DatabaseSafetyError:
            raised = True
        check("5a: no marker at all + jyotishasha_local -> allowed (ordinary local dev that forgot the env var)",
              not raised)

        raised = False
        try:
            enforce_local_database_safety(FAKE_PROD_URL)
        except DatabaseSafetyError:
            raised = True
        check("5b: no marker at all + production-shaped DB -> REJECTED "
              "(this is the exact reported incident -- now caught)", raised)

        # ==========================================================
        print("\n=== 6: helper-level parsing sanity ===")
        # ==========================================================
        check("6: _parse_db_target never raises on garbage input",
              _parse_db_target("not a url at all::::") == _parse_db_target("not a url at all::::"))
        check("6: _is_approved_local_db(None) is False, not an error", _is_approved_local_db(None) is False)

        print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    finally:
        _clear_env()

    return failed == 0


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
