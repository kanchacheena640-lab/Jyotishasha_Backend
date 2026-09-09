"""Local-only, one-time application of migration c4d8f21a9e05 (N6 Bell
items table + user_notifications.dismissed_at) against jyotishasha_local.
Same safety posture as scripts/n5_apply_scheduling_migration.py."""
import ipaddress
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
PRIOR_REVISION = "8c2f7b91d4e6"
TARGET_REVISION = "c4d8f21a9e05"


def verify_loopback():
    target = urlparse(LOCAL_DB_URL)
    assert target.hostname in ("localhost", "127.0.0.1", "::1") and target.path == "/jyotishasha_local"
    import psycopg2
    with psycopg2.connect(LOCAL_DB_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), inet_server_addr()::text")
            name, addr = cursor.fetchone()
            assert name == "jyotishasha_local" and ipaddress.ip_interface(addr).ip.is_loopback
            print(f"LOCAL VERIFIED: database={name}; server={addr}", flush=True)


def prepare():
    verify_loopback()
    os.environ["DATABASE_URL"] = LOCAL_DB_URL
    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
    os.environ["OPENAI_API_KEY"] = "sk-local-test-unused"
    os.environ["RAZORPAY_KEY_ID"] = "local-test-unused"
    os.environ["RAZORPAY_KEY_SECRET"] = "local-test-unused"
    os.environ["FCM_SERVICE_ACCOUNT_JSON"] = '{"project_id":"local-test-unused"}'
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False
    import firebase_admin
    from firebase_admin import messaging, auth

    def forbidden(*args, **kwargs):
        raise AssertionError("N6 migration runner forbids Firebase initialization/sending")

    firebase_admin.initialize_app = forbidden
    auth.verify_id_token = forbidden
    messaging.send = forbidden
    import extensions
    extensions.init_firebase = lambda: None

    def network_guard(event, args):
        if event == "socket.connect":
            assert args[1][0] in ("localhost", "127.0.0.1", "::1"), "N6 migration runner blocks external network"
        if event == "socket.getaddrinfo":
            assert args[0] in ("localhost", "127.0.0.1", "::1", None), "N6 migration runner blocks external DNS"

    sys.addaudithook(network_guard)


def main():
    prepare()
    from app import app
    from flask_migrate import upgrade, downgrade, current

    with app.app_context():
        before = current()
        print(f"Revision before upgrade: {before}")
        upgrade(revision=TARGET_REVISION)
        after_upgrade = current()
        print(f"Revision after upgrade: {after_upgrade}")

        print("Verifying downgrade path...")
        downgrade(revision=PRIOR_REVISION)
        after_downgrade = current()
        print(f"Revision after downgrade: {after_downgrade}")

        print("Re-applying upgrade (leaving DB at the new head)...")
        upgrade(revision=TARGET_REVISION)
        final = current()
        print(f"Final revision: {final}")

    verify_loopback()
    import psycopg2
    with psycopg2.connect(LOCAL_DB_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select column_name from information_schema.columns "
                "where table_name='user_notifications' and column_name='dismissed_at'")
            assert cursor.fetchone() is not None, "user_notifications.dismissed_at missing"
            print("user_notifications.dismissed_at: OK")

            cursor.execute(
                "select table_name from information_schema.tables "
                "where table_name='notification_campaign_bell_items'")
            assert cursor.fetchone() is not None, "notification_campaign_bell_items missing"
            print("notification_campaign_bell_items: OK")

            cursor.execute(
                "select indexname from pg_indexes where tablename='notification_campaign_bell_items' "
                "and indexname='ix_notification_campaign_bell_items_user'")
            assert cursor.fetchone() is not None, "bell items user index missing"
            print("ix_notification_campaign_bell_items_user: OK")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
