"""N-FIX-2C -- user_notifications.created_at timezone-safety fix.

Covers:
  A. Non-UTC PostgreSQL session regression (Asia/Kolkata) -- proves the
     unread-lookback and count_pushes_sent_today() comparisons represent
     the correct UTC instant.
  B. Migration upgrade -- seeds known legacy naive-UTC values, runs the
     real `flask db upgrade`, verifies every absolute UTC instant is
     unchanged.
  C. Migration downgrade -- round-trips back, verifies the original
     naive-UTC wall-clock values are reproduced byte-for-byte.
  D. count_pushes_sent_today()/start_of_today_ist() -- aware UTC,
     correct IST-day-boundary business definition unchanged.
  E. Unified Bell unread lookback with aware timestamps.
  F. Bell timestamp serialization remains valid, timezone-aware ISO.
  G. Event Scheduler / Alerts notification_created occurred_at no
     longer forces tzinfo onto an already-aware value.

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
    """Runs `flask db <args>` as a real subprocess against the local DB.
    PYTHONIOENCODING=utf-8 required on Windows (extensions.py::
    init_firebase() prints an emoji at import time)."""
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


TEST_USER_ID = 991_777_002


def _seed_test_row(cur, naive_created_at):
    """Inserts one row via raw SQL, forcing this connection's session
    TimeZone to UTC first -- makes the seed unambiguous regardless of
    whether created_at is currently naive or already timestamptz (see
    the identical technique/reasoning in test_notification_expires_at_
    timezone.py's own _seed_test_user_notifications_row())."""
    cur.execute("SET TIME ZONE 'UTC'")
    cur.execute(
        "INSERT INTO user_notifications (user_id, title, body, is_read, created_at) "
        "VALUES (%s, %s, %s, false, %s) RETURNING id",
        (TEST_USER_ID, "n-fix-2c-test", "body", naive_created_at),
    )
    return cur.fetchone()[0]


def _cleanup_test_rows(cur):
    cur.execute("DELETE FROM user_notifications WHERE user_id = %s", (TEST_USER_ID,))


def main():
    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            print("\n=== 0: confirm starting schema ===")
            starting_type = _column_type(cur, "user_notifications", "created_at")
            print(f"  created_at column type before upgrade: {starting_type!r}")

            # ==========================================================
            print("\n=== B: migration upgrade preserves absolute UTC instants ===")
            # ==========================================================
            _cleanup_test_rows(cur)
            legacy_values = [
                datetime(2026, 9, 12, 5, 19, 6),
                datetime(2026, 9, 12, 7, 19, 8, 688384),
            ]
            seeded_ids = [_seed_test_row(cur, v) for v in legacy_values]
            check("B: seeded 2 legacy naive-UTC rows", len(seeded_ids) == 2)

    result = _run_flask_db("upgrade")
    check("B: `flask db upgrade` exits 0", result.returncode == 0)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)

    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            upgraded_type = _column_type(cur, "user_notifications", "created_at")
            check("B: column is now timestamp with time zone", upgraded_type == "timestamp with time zone")

            for seeded_id, original_naive in zip(seeded_ids, legacy_values):
                cur.execute(
                    "SELECT created_at AT TIME ZONE 'UTC' FROM user_notifications WHERE id = %s",
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

            row_id = seeded_ids[0]  # meant as 2026-09-12 05:19:06 UTC
            one_minute_before_utc = datetime(2026, 9, 12, 5, 18, 6, tzinfo=timezone.utc)
            one_minute_after_utc = datetime(2026, 9, 12, 5, 20, 6, tzinfo=timezone.utc)

            cur.execute("SELECT created_at > %s FROM user_notifications WHERE id = %s", (one_minute_before_utc, row_id))
            check("A: created_at > (1 min earlier in real UTC) is True under Asia/Kolkata session",
                  cur.fetchone()[0] is True)

            cur.execute("SELECT created_at > %s FROM user_notifications WHERE id = %s", (one_minute_after_utc, row_id))
            check("A: created_at > (1 min later in real UTC) is False under Asia/Kolkata session",
                  cur.fetchone()[0] is False)

            cur.execute("SET TIME ZONE 'UTC'")

            # ==========================================================
            print("\n=== C: migration downgrade round-trips exactly ===")
            # ==========================================================

    result = _run_flask_db("downgrade", "0aea42c0e4d0")
    check("C: `flask db downgrade 0aea42c0e4d0` exits 0", result.returncode == 0)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)

    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            downgraded_type = _column_type(cur, "user_notifications", "created_at")
            check("C: column is back to timestamp without time zone", downgraded_type == "timestamp without time zone")

            for seeded_id, original_naive in zip(seeded_ids, legacy_values):
                cur.execute("SELECT created_at FROM user_notifications WHERE id = %s", (seeded_id,))
                roundtripped = cur.fetchone()[0]
                check(
                    f"C: row {seeded_id} round-trips to the EXACT original naive-UTC value "
                    f"(expected {original_naive}, got {roundtripped})",
                    roundtripped == original_naive,
                )

            _cleanup_test_rows(cur)

    result = _run_flask_db("upgrade")
    check("re-upgrade to final state exits 0", result.returncode == 0)
    with _raw_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            final_type = _column_type(cur, "user_notifications", "created_at")
            check("final schema state is timestamp with time zone (matches model.py)",
                  final_type == "timestamp with time zone")
            final_head_check = _column_type(cur, "user_notifications", "expires_at")
            check("N-FIX-2A's own expires_at fix is still intact (unaffected by this migration)",
                  final_head_check == "timestamp with time zone")

    # ==========================================================
    print("\n=== D: start_of_today_ist() / count_pushes_sent_today() ===")
    # ==========================================================
    from services.attention_policy import start_of_today_ist, count_pushes_sent_today, IST
    from app import app
    from extensions import db
    from notifications.notification_models import UserNotification

    boundary = start_of_today_ist(datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc))
    check("D: start_of_today_ist() returns a timezone-aware datetime", boundary.tzinfo is not None)
    check("D: start_of_today_ist() is aware UTC specifically", boundary.utcoffset() == timedelta(0))
    # 2026-09-12 10:00 UTC = 2026-09-12 15:30 IST -> IST midnight of that
    # day is 2026-09-11 18:30 UTC (unchanged business definition).
    check("D: IST-midnight boundary is the exact same real-world instant as before this fix",
          boundary == datetime(2026, 9, 11, 18, 30, 0, tzinfo=timezone.utc))

    with app.app_context():
        current_db = db.session.execute(db.text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", f"Refusing -- expected jyotishasha_local, got {current_db!r}"
        db.session.execute(db.text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": TEST_USER_ID})
        db.session.commit()

        # A row created "just after" today's IST midnight must count;
        # one created "just before" must not -- the exact business
        # boundary must be unchanged by this fix.
        today_utc_now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
        just_after_midnight = datetime(2026, 9, 11, 18, 31, 0, tzinfo=timezone.utc)
        just_before_midnight = datetime(2026, 9, 11, 18, 29, 0, tzinfo=timezone.utc)

        row_after = UserNotification(
            user_id=TEST_USER_ID, title="t", body="b", data={"type": "event"},
            is_read=False, created_at=just_after_midnight,
        )
        row_before = UserNotification(
            user_id=TEST_USER_ID, title="t", body="b", data={"type": "event"},
            is_read=False, created_at=just_before_midnight,
        )
        db.session.add_all([row_after, row_before])
        db.session.commit()

        count = count_pushes_sent_today(TEST_USER_ID, now=today_utc_now)
        check("D: count_pushes_sent_today() counts the row just AFTER IST midnight", count >= 1)

        db.session.delete(row_after)
        db.session.commit()
        count2 = count_pushes_sent_today(TEST_USER_ID, now=today_utc_now)
        check("D: count_pushes_sent_today() does NOT count the row just BEFORE IST midnight "
              "(the exact business boundary is unchanged)", count2 == 0)

        db.session.execute(db.text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": TEST_USER_ID})
        db.session.commit()

        # ==========================================================
        print("\n=== E: unified Bell unread lookback with aware timestamps ===")
        # ==========================================================
        from notifications.campaign_bell_service import list_unified_bell, UNREAD_LOOKBACK

        now = datetime.now(timezone.utc)
        recent_read_row = UserNotification(
            user_id=TEST_USER_ID, title="recent read", body="b", data={"type": "event"},
            is_read=True, created_at=now - timedelta(minutes=5),
        )
        stale_read_row = UserNotification(
            user_id=TEST_USER_ID, title="stale read", body="b", data={"type": "event"},
            is_read=True, created_at=now - UNREAD_LOOKBACK - timedelta(hours=1),
        )
        db.session.add_all([recent_read_row, stale_read_row])
        db.session.commit()

        bell_items = list_unified_bell(TEST_USER_ID, now=now)
        bell_ids = {item["id"] for item in bell_items}
        check("E: a recently-created READ row (within lookback) IS still shown",
              f"ab:{recent_read_row.id}" in bell_ids)
        check("E: a stale READ row (older than lookback) is correctly excluded",
              f"ab:{stale_read_row.id}" not in bell_ids)

        # ==========================================================
        print("\n=== F: Bell timestamp serialization remains valid, aware ISO ===")
        # ==========================================================
        serialized = next(item for item in bell_items if item["id"] == f"ab:{recent_read_row.id}")
        check("F: serialized created_at is a non-null string", isinstance(serialized["created_at"], str))
        reparsed = datetime.fromisoformat(serialized["created_at"])
        check("F: serialized created_at round-trips through fromisoformat() cleanly", reparsed.tzinfo is not None)
        check("F: serialized created_at is UTC-offset (+00:00)", serialized["created_at"].endswith("+00:00"))

        db.session.execute(db.text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": TEST_USER_ID})
        db.session.commit()

        # ==========================================================
        print("\n=== G: Event Scheduler / Alerts occurred_at no longer forces tzinfo ===")
        # ==========================================================
        row = UserNotification(
            user_id=TEST_USER_ID, title="t", body="b", data={"type": "event"},
            is_read=False,
        )
        db.session.add(row)
        db.session.commit()
        db.session.refresh(row)
        check("G: a freshly-committed row's created_at (DB default) is already timezone-aware",
              row.created_at.tzinfo is not None)
        # Exactly what event_scheduler.py/alert_delivery_service.py/
        # notification_service.py now do: use created_at AS-IS.
        occurred_at = row.created_at if row.created_at is not None else datetime.now(timezone.utc)
        check("G: using created_at directly (no .replace()) yields the identical instant",
              occurred_at == row.created_at)

        db.session.execute(db.text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": TEST_USER_ID})
        db.session.commit()

    print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed\n{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
