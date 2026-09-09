"""Local-only, one-time application of migration c71a83b4e209
(notification_campaigns table) against jyotishasha_local. No Firebase
initialization, no dotenv credentials, no other DDL permitted beyond
this named revision. Mirrors scripts/l3_local_verify.py's safety
posture, adapted for a single reviewed migration instead of tests."""
import ipaddress
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
TARGET_REVISION = "c71a83b4e209"


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
        raise AssertionError("N3 migration runner forbids Firebase initialization/sending")

    firebase_admin.initialize_app = forbidden
    auth.verify_id_token = forbidden
    messaging.send = forbidden
    import extensions
    extensions.init_firebase = lambda: None

    def network_guard(event, args):
        if event == "socket.connect":
            assert args[1][0] in ("localhost", "127.0.0.1", "::1"), "N3 migration runner blocks external network"
        if event == "socket.getaddrinfo":
            assert args[0] in ("localhost", "127.0.0.1", "::1", None), "N3 migration runner blocks external DNS"

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
            cursor.execute("select to_regclass('public.notification_campaigns')")
            table = cursor.fetchone()[0]
            assert table == "notification_campaigns", "notification_campaigns table was not created"
            cursor.execute("select count(*) from notification_campaigns")
            count = cursor.fetchone()[0]
            print(f"notification_campaigns exists; row count={count}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
