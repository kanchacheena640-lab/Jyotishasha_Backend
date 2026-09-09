"""Local-only, one-time application of migration 5a1e9d2f4c73
(N4 Send Now execution/delivery/attempt/idempotency schema) against
jyotishasha_local. Same safety posture as scripts/n3_apply_campaign_migration.py."""
import ipaddress
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
TARGET_REVISION = "5a1e9d2f4c73"


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
        raise AssertionError("N4 migration runner forbids Firebase initialization/sending")

    firebase_admin.initialize_app = forbidden
    auth.verify_id_token = forbidden
    messaging.send = forbidden
    import extensions
    extensions.init_firebase = lambda: None

    def network_guard(event, args):
        if event == "socket.connect":
            assert args[1][0] in ("localhost", "127.0.0.1", "::1"), "N4 migration runner blocks external network"
        if event == "socket.getaddrinfo":
            assert args[0] in ("localhost", "127.0.0.1", "::1", None), "N4 migration runner blocks external DNS"

    sys.addaudithook(network_guard)


def main():
    prepare()
    from app import app
    from flask_migrate import upgrade, current

    with app.app_context():
        before = current()
        print(f"Revision before upgrade: {before}")
        upgrade(revision=TARGET_REVISION)
        after = current()
        print(f"Revision after upgrade: {after}")

    verify_loopback()
    import psycopg2
    with psycopg2.connect(LOCAL_DB_URL) as connection:
        with connection.cursor() as cursor:
            for table in ("notification_campaign_executions", "notification_campaign_deliveries",
                          "notification_campaign_attempts", "notification_send_now_requests"):
                cursor.execute("select to_regclass(%s)", (f"public.{table}",))
                found = cursor.fetchone()[0]
                assert found == table, f"{table} was not created"
                print(f"{table}: OK")
            cursor.execute("select column_name from information_schema.columns where table_name='notification_campaigns' and column_name='hold_reason'")
            assert cursor.fetchone() is not None, "hold_reason column missing"
            print("notification_campaigns.hold_reason: OK")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
