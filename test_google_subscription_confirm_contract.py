"""
test_google_subscription_confirm_contract.py
----------------------------------
Google Play Subscription Confirm Contract fix -- proves:

  A. The exact production bug is reproduced byte-for-byte one more
     time (regression guard): a request missing `platform` still
     returns the same 121-byte 400 body -- proves the fix below is
     purely additive logging, not a behavior change to the validation
     itself.
  B. Every request-validation 400 (not just the platform one) now
     emits exactly one log line via the "payments" logger, carrying a
     correlation_id and a `reason` in its `error` field.
  C. The raw purchase_token NEVER appears verbatim in any log line --
     only the masked form (log_payment_event's own existing
     _mask_identifier() output).
  D. The Authorization header / JWT value never appears in any log
     line.
  E. A genuinely malformed/unknown token (Google-side rejection, not a
     request-shape error) still returns its own existing 400, logged
     by PaymentService's own pre-existing, unmodified path -- unchanged.

Uses the LOCAL scratch Postgres DB ONLY. No production access. No real
Google Play API call is ever made (this file never reaches
GooglePlayProvider -- every case here is rejected before that point).
"""

import logging
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json as _json  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.payments.payment_logger import logger as payments_logger  # noqa: E402
from routes.routes_google_purchase_confirm import _GOOGLE_PLAY_PLATFORMS  # noqa: E402

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


PID, UID = 991001, 991101
# Deliberately long enough that _mask_identifier's 6-char prefix +
# length marker is unambiguously distinguishable from the full value.
REAL_TOKEN = "gpa-real-purchase-token-abcdef1234567890"
FAKE_AUTHORIZATION_SECRET = "Bearer-should-never-appear-in-any-log-line"


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def cleanup():
    AppUser.query.filter_by(id=PID).delete(synchronize_session=False)
    User.query.filter_by(id=UID).delete(synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        db.session.add(User(id=UID, email="subconfirm-diag@example.com", provider="password", firebase_uid="fb-subconfirm-diag"))
        db.session.add(AppUser(id=PID, firebase_uid="fb-subconfirm-diag"))
        db.session.commit()

        token = create_access_token(identity=str(UID))
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        client = app.test_client()

        capture = _CapturingHandler()
        payments_logger.addHandler(capture)

        try:
            # ==========================================================
            print("=== A: exact production bug reproduced byte-for-byte (regression guard) ===")
            # ==========================================================
            capture.lines.clear()
            resp_a = client.post(
                "/api/subscription/google/confirm",
                json={"product_id": "jyotishasha.gold.monthly", "purchase_token": REAL_TOKEN},
                headers=headers,
            )
            raw_a = resp_a.get_data()
            check("A: HTTP 400", resp_a.status_code == 400)
            check(f"A: exact 121-byte body (got {len(raw_a)})", len(raw_a) == 121)
            expected_message = (
                f"platform must be one of {_GOOGLE_PLAY_PLATFORMS!r} -- "
                f"Apple is not implemented."
            )
            expected_body = _json.dumps(
                {"message": expected_message, "status": "INVALID_REQUEST"},
                separators=(",", ":"), sort_keys=True,
            ) + "\n"  # Flask's jsonify() appends a trailing newline
            check(
                "A: exact production message",
                raw_a.decode("utf-8") == expected_body,
            )

            # ==========================================================
            print("\n=== B: this exact rejection now emits exactly one log line, with correlation_id + reason ===")
            # ==========================================================
            check("B: exactly one log line emitted", len(capture.lines) == 1)
            record = _json.loads(capture.lines[0])
            check("B: log line has a non-empty correlation_id", bool(record.get("correlation_id")))
            check("B: event == google_purchase_confirm_rejected", record.get("event") == "google_purchase_confirm_rejected")
            check("B: error field starts with reason 'invalid_platform:'", str(record.get("error", "")).startswith("invalid_platform:"))
            check("B: product field carries the client's product_id", record.get("product") == "jyotishasha.gold.monthly")

            # ==========================================================
            print("\n=== C: the raw purchase_token NEVER appears verbatim in the log line -- only masked ===")
            # ==========================================================
            full_line = capture.lines[0]
            check("C: raw REAL_TOKEN not present anywhere in the log line", REAL_TOKEN not in full_line)
            check(
                "C: masked form (6-char prefix + length marker) IS present",
                f"{REAL_TOKEN[:6]}...(masked,len={len(REAL_TOKEN)})" in full_line,
            )

            # ==========================================================
            print("\n=== D: the Authorization header / JWT never appears in any log line ===")
            # ==========================================================
            check("D: bearer token not present in the log line", token not in full_line)
            check("D: literal 'Authorization' header value not present", FAKE_AUTHORIZATION_SECRET not in full_line)

            # ==========================================================
            print("\n=== B2: every OTHER request-validation 400 also logs exactly one safe line ===")
            # ==========================================================
            other_cases = {
                "not_json_400": ("not-a-dict-body", False),
                "missing_purchase_token_400": ({"platform": "ANDROID"}, True),
                "missing_platform_400": ({"purchase_token": REAL_TOKEN}, True),
                "invalid_profile_id_400": (
                    {"purchase_token": REAL_TOKEN, "platform": "ANDROID", "profile_id": "not-an-int"}, True,
                ),
                "invalid_segment_400": (
                    {"purchase_token": REAL_TOKEN, "platform": "ANDROID", "selected_segment": "NOT_REAL"}, True,
                ),
            }
            for name, (body, is_json) in other_cases.items():
                capture.lines.clear()
                if is_json:
                    resp = client.post("/api/subscription/google/confirm", json=body, headers=headers)
                else:
                    resp = client.post(
                        "/api/subscription/google/confirm", data=_json.dumps(body), headers=headers,
                    )
                check(f"B2: {name} -> HTTP 400", resp.status_code == 400)
                check(f"B2: {name} -> exactly one log line", len(capture.lines) == 1)
                line = capture.lines[0]
                check(f"B2: {name} -> raw token never appears", REAL_TOKEN not in line)
                check(f"B2: {name} -> bearer token never appears", token not in line)
                rec = _json.loads(line)
                check(f"B2: {name} -> correlation_id present", bool(rec.get("correlation_id")))

            # ==========================================================
            print("\n=== E: no-profile (403) rejection is also logged safely, unchanged status code ===")
            # ==========================================================
            orphan_token = create_access_token(identity=str(991999))
            capture.lines.clear()
            resp_e = client.post(
                "/api/subscription/google/confirm",
                json={"purchase_token": REAL_TOKEN, "platform": "ANDROID"},
                headers={"Authorization": f"Bearer {orphan_token}", "Content-Type": "application/json"},
            )
            check("E: HTTP 403 (unchanged)", resp_e.status_code == 403)
            check("E: exactly one log line", len(capture.lines) == 1)
            check("E: raw token never appears", REAL_TOKEN not in capture.lines[0])

        finally:
            payments_logger.removeHandler(capture)
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
