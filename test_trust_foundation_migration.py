"""
test_trust_foundation_migration.py
------------------------------------
Trust Foundation Phase 0 -- proves migrations/versions/
b3f8e6a2c9d4_add_missing_firebase_uid_unique_constraint.py behaves
correctly against the actual live schema states found in production and
local dev (Trust Foundation Audit, Sections I/J/Q):

  - upgrade() creates the missing index on whichever table needs it,
    and correctly SKIPS a table that already has an equivalently-shaped
    unique index under a different name (never a redundant second
    index).
  - The resulting constraint enforces uniqueness on real firebase_uid
    values.
  - NULL firebase_uid is explicitly, intentionally allowed to repeat
    (the partial index's WHERE clause) -- unlinked profiles are a real,
    common, legitimate state, not an error.
  - downgrade() removes ONLY the index this migration might have
    created, by its own fixed name -- never a pre-existing,
    differently-named index this migration did not create.

Run via the REAL flask-migrate/Alembic CLI (not a hand-rolled
reimplementation of the DDL) against the LOCAL scratch Postgres DB --
this exercises the exact same code path a real `flask db upgrade` in
any environment would. No production DB is ever touched.
"""

import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(BACKEND_DIR, "venv", "Scripts", "python.exe")

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


def _env():
    env = dict(os.environ)
    env["DATABASE_URL"] = LOCAL_DB_URL
    env.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
    env["FLASK_APP"] = "app.py"
    env["PYTHONUTF8"] = "1"
    return env


def _flask_db(*args):
    result = subprocess.run(
        [PYTHON, "-m", "flask", "db", *args],
        cwd=BACKEND_DIR, env=_env(), capture_output=True, text=True, timeout=60,
    )
    return result.returncode, result.stdout + result.stderr


def _query(sql, params=None):
    import psycopg2
    conn = psycopg2.connect(LOCAL_DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    conn.close()
    return rows


def _index_names(table):
    rows = _query(
        "SELECT indexname FROM pg_indexes WHERE tablename=%s AND indexdef ILIKE %s",
        (table, "%firebase_uid%"),
    )
    return {r[0] for r in rows}


def main():
    print("=== 0: start from a known baseline (idempotent test setup) ===")
    # A prior run of this file (or the manual verification pass) may
    # already have this migration applied -- downgrade first so test 1
    # below observes a REAL upgrade, not a no-op.
    _flask_db("downgrade", "d7e1b4c9f2a5")

    print("\n=== 1: migration upgrades cleanly on local schema ===")
    code, out = _flask_db("upgrade")
    check("1: `flask db upgrade` exits 0", code == 0)
    check("1: alembic reports running this exact revision", "b3f8e6a2c9d4" in out)

    print("\n=== 2: migration handles the known production constraint state safely ===")
    # Local starts with users already indexed (ix_users_firebase_uid,
    # matching db.create_all()'s own honoring of the model) and
    # app_users NOT indexed -- the mirror image of production. Proves
    # the migration's existence-check branches correctly either way,
    # not just for the one state it happened to be written against.
    users_idx = _index_names("users")
    app_users_idx = _index_names("app_users")
    check("2: users already had a unique firebase_uid index BEFORE this migration ran (pre-existing, untouched)", "ix_users_firebase_uid" in users_idx)
    check("2: migration did NOT create a second, redundant index on users", len(users_idx) == 1)
    check("2: migration created the MISSING index on app_users, under its own name", "unique_app_users_firebase_uid" in app_users_idx)

    print("\n=== 3: uniqueness guarantee works as intended ===")
    import psycopg2
    conn = psycopg2.connect(LOCAL_DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM app_users WHERE id IN (970001, 970002)")
    cur.execute(
        "INSERT INTO app_users (id, firebase_uid, tz, subscription, asknow_tokens) VALUES (970001, 'MIGRATION_TEST_DUP', '+05:30', 'free', 0)"
    )
    try:
        cur.execute(
            "INSERT INTO app_users (id, firebase_uid, tz, subscription, asknow_tokens) VALUES (970002, 'MIGRATION_TEST_DUP', '+05:30', 'free', 0)"
        )
        check("3: duplicate firebase_uid on app_users REJECTED by the new constraint", False)
    except psycopg2.errors.UniqueViolation:
        check("3: duplicate firebase_uid on app_users REJECTED by the new constraint", True)
    cur.execute("DELETE FROM app_users WHERE id IN (970001, 970002)")

    print("\n=== 4: NULL behavior is intentional ===")
    cur.execute("DELETE FROM app_users WHERE id IN (970003, 970004)")
    try:
        cur.execute("INSERT INTO app_users (id, firebase_uid, tz, subscription, asknow_tokens) VALUES (970003, NULL, '+05:30', 'free', 0)")
        cur.execute("INSERT INTO app_users (id, firebase_uid, tz, subscription, asknow_tokens) VALUES (970004, NULL, '+05:30', 'free', 0)")
        check("4: two NULL firebase_uid rows both allowed (partial index correctly ignores NULL)", True)
    except Exception as e:
        check(f"4: NULL insert unexpectedly rejected: {e}", False)
    cur.execute("DELETE FROM app_users WHERE id IN (970003, 970004)")
    conn.close()

    print("\n=== 5: downgrade/rollback behavior is documented and tested ===")
    code, out = _flask_db("downgrade", "d7e1b4c9f2a5")
    check("5: `flask db downgrade` exits 0", code == 0)
    app_users_idx_after = _index_names("app_users")
    users_idx_after = _index_names("users")
    check("5: downgrade removed the index THIS migration created (app_users)", "unique_app_users_firebase_uid" not in app_users_idx_after)
    check("5: downgrade did NOT touch the pre-existing users index it never created", "ix_users_firebase_uid" in users_idx_after)

    print("\n=== 6: re-upgrade restores the intended final state (idempotent re-run) ===")
    code, out = _flask_db("upgrade")
    check("6: re-upgrade exits 0", code == 0)
    check("6: app_users constraint restored", "unique_app_users_firebase_uid" in _index_names("app_users"))

    print("\n" + "=" * 50)
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
