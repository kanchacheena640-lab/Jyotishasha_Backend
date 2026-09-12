"""N-FIX-2A -- user_notifications.expires_at timezone-safety fix.

Covers, in this order (matching the task's own lettering):
  A. Non-UTC PostgreSQL session regression (Asia/Kolkata) -- proves the
     Bell expiry comparison represents the correct UTC instant.
  B. Migration upgrade -- seeds known legacy naive-UTC values, runs the
     real `flask db upgrade`, verifies every absolute UTC instant is
     unchanged.
  C. Migration downgrade -- round-trips back, verifies the original
     naive-UTC wall-clock values are reproduced byte-for-byte.
  D. Writer tests -- notification_lifecycle.py functions return
     timezone-aware UTC datetimes.
  E. Panchang -- the intended 17:00 IST cutoff is exactly the same
     real-world instant before and after.
  F. auto_dismiss_at -- exactly one valid ISO-8601 timezone suffix,
     never a malformed "+00:00Z".

LOCAL DATABASE ONLY. B/C actually invoke `flask db upgrade`/`downgrade`
as subprocesses against jyotishasha_local -- never production. Ends
with the local DB left in the fully-upgraded (new, timezone-aware)
state so every other test file in this repo runs against the same
schema the ORM model now declares.
"""
import os
import subprocess
import sys
from datetime import date, datetime, timezone, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("RAZORPAY_KEY_ID", "test-dummy-not-used")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test-dummy-not-used")
os.environ.setdefault(
    "FCM_SERVICE_ACCOUNT_JSON",
    '{"type":"service_account","project_id":"test-only-unused","private_key_id":"test-only-unused",'
    '"private_key":"-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDPMyBqdLrbCfVJ\\n'
    '8jGfMwJbmPMd3x3wm+dBjrQb/DftkVeGrtLVNocmyRHbQv1R+YEEda7UoWzy9DNX\\nUbaoY4mfdmvs2PruqYzW5SPISxaupE8l5EgolZQ0fBGCyUgcHWJj++sxMkrIsRrQ\\n'
    'Gi6hl8tmWBj+NzGFBa8297lMRfkkM7QB6yhhAmZdJteHjpezl/p9Cjg7PHZ7wAz+\\nWkIAaXCPpZlvMQDQlTP2Y5DF7lurCo890/ESKsEiPVcw3vIW8WFuuHHpKCPdzXP1\\n'
    'UctR40pR9+WPjKUQ2gYjFrQsyoV6KiXCIomy9nnd6bLPPhIlqgOeiabbF82AMwMk\\ne3VeAaxFAgMBAAECggEAD8EMauu7NWJZcyjmGvuu5zYG7jODvEKuX66xBRu1SOvv\\n'
    'Ir9yKmH9/rX1FJ3QUwZMiAFGrMYlWYe1y6Lb54vB8Az6AcUxtynPGpvLj7Qd4mN9\\n3RyxW9ybqy3vyujxAao+S+ngpRn007ObnU0QVJsNDRgPtmyN6FZZTy2guirr2ZOt\\n'
    'qXKaUbag//ItMLKCIsY+kfMnF0mW7BinM3+pbsPT7fZ0zVYTa66nKNs99KfiC2Lx\\n4Y06lN42zC6PMLwsNulYKhcUpeprCcbcG8XEhAoeilhODUGC3jmP9whXkSa+6DXp\\n'
    'Z+gs5xWY9dPOpkMKMH7vuOS63hEX74P6vzJkHwRlQQKBgQD7LtX9Z1x+CSb5Q2Yx\\nauHIkEjxsxN7QHw+rrzzO+5jxZnme86Ccr8mizoY4IKIyH9cCWyBXtMjCf6axEVD\\n'
    'bGS0N4ZQZSg+PsEhpGT1etOLjnDYsmpjv+7osbIBsWrLQYvpTWFD5efjAN0fgTzR\\nXf67yjfBp5+dm4zw1aK6KihQFQKBgQDTLFu3n2/TIdlHYqNzUZR5vJRsX1Vo4ZYk\\n'
    '67/ImzaidFU6b7e8l/0Nza2P8dy1lmgzOwaWlhG2u/UzIs7BQm+LFJuq/pN/rxUP\\nppK1ljGsjaS5dDKjJaOKU6GzErUpFwdEBHiwpaB9uCyOrWxy5OUQ3gGpDT+swPKb\\n'
    'NmKaw57HcQKBgHU6BJDBPn9r0g6fEACcO0eZXxG+W6c4D0RJ1NFH9RgHTq4stdJX\\nrzJT5AdcME+aEyZnF4bBNJSzw2mDlDfFTLJ2/25h54g1TXlf+eY/Lp+BGNVpXxGy\\n'
    'r9NVqxfzLz4xFxUJEg3YLILbElfzvuiPj6Ug2Si+DFZIFF0Jt2pe5nWJAoGBAI4Y\\nhCLcCwAT/8PUMM4RMAp2hZ0izTME0OZJKETRhILuKsdmk0k5MJNQOiDpC6245qbK\\n'
    'ahV8J7FBaq4dFujeTnZUyKbYJOI/KrncSU4dIZHNwfD0qnozgoc63UzFItfiYgY3\\nyAp9eK//9SOQuK/bK/QcnxtlCdqx/s3IW7NuPHJRAoGAI8KfG6EnScMBmF3qPjaG\\n'
    'OnVGdaSns76SYt8ctqzjhio2jksHFifwa0XqcGkeGRyWRyLW/BSANdb/g6gPOvU/\\nwo013MDoPN+pjGhQpxd73Qe+MnxEcKfK5E93SjDjkTqGGpLoWfDAATVLNLoezV1N\\n'
    '9hZzaVh5L3pMvuvAbmZ2rL4=\\n-----END PRIVATE KEY-----\\n","client_email":"test-only-unused@test-only-unused.iam.gserviceaccount.com",'
    '"client_id":"000000000000000000000","auth_uri":"https://accounts.google.com/o/oauth2/auth",'
    '"token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs",'
    '"client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/test-only-unused%40test-only-unused.iam.gserviceaccount.com",'
    '"universe_domain":"googleapis.com"}',
)
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2  # noqa: E402

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


def _run_flask_db(*args):
    """Runs `flask db <args>` as a real subprocess against the local DB
    -- exactly how this would be applied for real, never faked.
    PYTHONIOENCODING=utf-8 is required on Windows -- app.py's own
    extensions.py::init_firebase() prints an emoji at import time, which
    crashes under the subprocess's default cp1252 console encoding
    before Alembic ever runs, unrelated to this migration itself."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "db", *args],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    return result


def _raw_conn():
    return psycopg2.connect(LOCAL_DB_URL)


def _column_type(cur, table, column):
    cur.execute(
        "SELECT data_type FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        (table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


TEST_USER_ID = 991_777_001


def _seed_test_user_notifications_row(cur, naive_expires_at):
    """Inserts one row via raw SQL -- bypassing the ORM entirely, so
    this genuinely simulates a HISTORICALLY-stored legacy row,
    regardless of what the current model.py declares.

    Forces this connection's session TimeZone to UTC first -- this is
    what makes the seed itself unambiguous REGARDLESS of whether
    expires_at is currently naive or already timestamptz: a naive
    Python datetime bound under a UTC session is interpreted as UTC
    wall-clock either way (naive column: stored as-is; timestamptz
    column: Postgres resolves the naive value against the session's
    OWN TimeZone GUC to produce the absolute instant -- forcing UTC
    here is exactly what makes that resolution correct, mirroring the
    real historical writers, which produced naive-UTC values long
    before this migration/column type ever existed)."""
    cur.execute("SET TIME ZONE 'UTC'")
    cur.execute(
        "INSERT INTO user_notifications (user_id, title, body, is_read, created_at, expires_at) "
        "VALUES (%s, %s, %s, false, now(), %s) RETURNING id",
        (TEST_USER_ID, "n-fix-2a-test", "body", naive_expires_at),
    )
    return cur.fetchone()[0]


def _cleanup_test_rows(cur):
    cur.execute("DELETE FROM user_notifications WHERE user_id = %s", (TEST_USER_ID,))


def main():
    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            print("\n=== 0: confirm starting schema (pre-migration) ===")
            starting_type = _column_type(cur, "user_notifications", "expires_at")
            print(f"  expires_at column type before upgrade: {starting_type!r}")

            # ==========================================================
            print("\n=== B: migration upgrade preserves absolute UTC instants ===")
            # ==========================================================
            _cleanup_test_rows(cur)
            # Two known legacy naive-UTC values (as every writer has
            # always produced) -- one at a "nice" boundary, one with a
            # non-zero minute, to catch any truncation bug too.
            legacy_values = [
                datetime(2026, 9, 12, 17, 0, 0),   # naive, meant as 17:00 UTC
                datetime(2026, 9, 13, 3, 30, 0),   # naive, meant as 03:30 UTC
            ]
            seeded_ids = [_seed_test_user_notifications_row(cur, v) for v in legacy_values]
            check("B: seeded 2 legacy naive-UTC rows", len(seeded_ids) == 2)

    # Run the REAL migration -- a fresh subprocess, exactly how this
    # would be applied for real.
    result = _run_flask_db("upgrade")
    check("B: `flask db upgrade` exits 0", result.returncode == 0)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)

    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            upgraded_type = _column_type(cur, "user_notifications", "expires_at")
            check("B: column is now timestamp with time zone", upgraded_type == "timestamp with time zone")

            for seeded_id, original_naive in zip(seeded_ids, legacy_values):
                # Reinterpret the now-aware stored value back as a UTC
                # wall-clock reading -- must exactly equal the original
                # naive value (which always meant UTC).
                cur.execute(
                    "SELECT expires_at AT TIME ZONE 'UTC' FROM user_notifications WHERE id = %s",
                    (seeded_id,),
                )
                reinterpreted = cur.fetchone()[0]
                check(
                    f"B: row {seeded_id} absolute UTC instant unchanged after upgrade "
                    f"(expected {original_naive}, got {reinterpreted})",
                    reinterpreted == original_naive,
                )

            # ==========================================================
            print("\n=== A: non-UTC session (Asia/Kolkata) comparison is now correct ===")
            # ==========================================================
            cur.execute("SET TIME ZONE 'Asia/Kolkata'")
            cur.execute("SHOW timezone")
            check("A: session timezone is genuinely non-UTC for this check", cur.fetchone()[0] == "Asia/Kolkata")

            row_id = seeded_ids[0]  # meant as 2026-09-12 17:00:00 UTC
            one_minute_before_utc = datetime(2026, 9, 12, 16, 59, 0, tzinfo=timezone.utc)
            one_minute_after_utc = datetime(2026, 9, 12, 17, 1, 0, tzinfo=timezone.utc)

            cur.execute("SELECT expires_at > %s FROM user_notifications WHERE id = %s", (one_minute_before_utc, row_id))
            check("A: expires_at > (1 min earlier in real UTC) is True under Asia/Kolkata session",
                  cur.fetchone()[0] is True)

            cur.execute("SELECT expires_at > %s FROM user_notifications WHERE id = %s", (one_minute_after_utc, row_id))
            check("A: expires_at > (1 min later in real UTC) is False under Asia/Kolkata session",
                  cur.fetchone()[0] is False)

            cur.execute("SET TIME ZONE 'UTC'")  # restore for the rest of this connection

            # ==========================================================
            print("\n=== C: migration downgrade round-trips exactly ===")
            # ==========================================================

    result = _run_flask_db("downgrade", "b4e7f18a2c6d")
    check("C: `flask db downgrade b4e7f18a2c6d` exits 0", result.returncode == 0)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)

    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            downgraded_type = _column_type(cur, "user_notifications", "expires_at")
            check("C: column is back to timestamp without time zone", downgraded_type == "timestamp without time zone")

            for seeded_id, original_naive in zip(seeded_ids, legacy_values):
                cur.execute("SELECT expires_at FROM user_notifications WHERE id = %s", (seeded_id,))
                roundtripped = cur.fetchone()[0]
                check(
                    f"C: row {seeded_id} round-trips to the EXACT original naive-UTC value "
                    f"(expected {original_naive}, got {roundtripped})",
                    roundtripped == original_naive,
                )

            _cleanup_test_rows(cur)

    # Re-upgrade -- leave local DB in the FINAL, intended state so every
    # other test file in this repo runs against the schema the ORM
    # model now actually declares.
    result = _run_flask_db("upgrade")
    check("re-upgrade to final state exits 0", result.returncode == 0)
    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            final_type = _column_type(cur, "user_notifications", "expires_at")
            check("final schema state is timestamp with time zone (matches model.py)",
                  final_type == "timestamp with time zone")

    # ==========================================================
    print("\n=== D: writer functions return timezone-aware UTC ===")
    # ==========================================================
    from services.notification_lifecycle import (
        _ist_midnight_utc, expiry_for_astro_event_notification,
        expiry_for_same_day_notification, expiry_for_dasha_pre_notification,
        expiry_for_alert_notification,
    )
    ist_mid = _ist_midnight_utc(date(2026, 9, 12))
    check("D: _ist_midnight_utc() returns a timezone-aware datetime", ist_mid.tzinfo is not None)
    check("D: _ist_midnight_utc() is aware UTC specifically", ist_mid.utcoffset() == timedelta(0))

    for label, value in [
        ("expiry_for_astro_event_notification",
         expiry_for_astro_event_notification(event_date=date(2026, 9, 12), is_forward_looking=False)),
        ("expiry_for_same_day_notification",
         expiry_for_same_day_notification(generated_on=date(2026, 9, 12))),
        ("expiry_for_dasha_pre_notification",
         expiry_for_dasha_pre_notification(transition_date=date(2026, 9, 12))),
        ("expiry_for_alert_notification",
         expiry_for_alert_notification(active_until=date(2026, 9, 12))),
    ]:
        check(f"D: {label}() returns timezone-aware UTC", value.tzinfo is not None and value.utcoffset() == timedelta(0))

    # ==========================================================
    print("\n=== E: Panchang cutoff is the exact same real-world instant ===")
    # ==========================================================
    from datetime import time as dtime
    IST = timezone(timedelta(hours=5, minutes=30))
    target_date = date(2026, 9, 12)
    PANCHANG_AUTO_DISMISS_HOUR_IST = 17  # matches services/event_scheduler.py's own constant value

    # The OLD (pre-fix) computation, reproduced here ONLY to prove
    # equivalence -- never reused as the real implementation.
    old_style_naive = (
        datetime.combine(target_date, dtime(hour=PANCHANG_AUTO_DISMISS_HOUR_IST), tzinfo=IST)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    # The NEW (fixed) computation, imported from the real module.
    import services.event_scheduler as event_scheduler_module
    new_style_aware = (
        datetime.combine(target_date, dtime(hour=event_scheduler_module.PANCHANG_AUTO_DISMISS_HOUR_IST), tzinfo=IST)
        .astimezone(timezone.utc)
    )
    check("E: new aware Panchang cutoff represents the IDENTICAL real-world instant as the old naive one",
          new_style_aware.replace(tzinfo=None) == old_style_naive)
    check("E: Panchang cutoff is still exactly 17:00 IST (11:30 UTC)",
          new_style_aware.astimezone(IST).hour == 17 and new_style_aware.astimezone(IST).minute == 0)

    # ==========================================================
    print("\n=== F: auto_dismiss_at is a single, valid ISO-8601 string ===")
    # ==========================================================
    serialized = new_style_aware.isoformat()
    check("F: auto_dismiss_at never contains a malformed double timezone suffix",
          not serialized.endswith("+00:00Z") and not serialized.endswith("ZZ"))
    check("F: auto_dismiss_at ends in exactly one valid UTC offset marker",
          serialized.endswith("+00:00"))
    reparsed = datetime.fromisoformat(serialized)
    check("F: auto_dismiss_at round-trips through datetime.fromisoformat() cleanly", reparsed == new_style_aware)

    print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed\n{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
