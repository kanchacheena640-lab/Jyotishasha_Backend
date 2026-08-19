"""
test_chatpack_google_verify.py
----------------------------------
Ask Now ChatPack Google Play hardening -- asknow8q (legacy) +
asknow10q (new), real Google Play verification, and idempotency.

Covers scenarios A-J from the task:
  A. asknow8q -> 8 questions / Rs 51
  B. asknow10q -> 10 questions / Rs 100
  C. unknown product ID rejected
  D. invalid Google purchase rejected
  E. cancelled/non-completed purchase rejected
  F. valid Google purchase accepted (order_id passthrough)
  G. same purchase token submitted twice does NOT create/grant twice
  H. retry of already-successful token returns a recovery-safe result
  I. both verification routes (/api/chatpack/verify and
     /api/chat/pack/google/verify) produce equivalent behavior
  J. Google verification failure creates no ChatPack entitlement

NO REAL GOOGLE PLAY API CALL IS EVER MADE -- GooglePlayProvider is
monkeypatched at the module level used by chatpack_google_verify.py.
Uses the LOCAL scratch Postgres DB ONLY.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.payments.google_play_models import (  # noqa: E402
    GooglePlayProductVerification,
    GooglePlayVerificationStatus,
)

import modules.services.chatpack_google_verify as verify_module  # noqa: E402
from modules.services.chatpack_google_verify import verify_google_chatpack  # noqa: E402

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


USER_IDS = list(range(984001, 984020))


def cleanup():
    ChatPack.query.filter(ChatPack.user_id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


# =============================================================================
# Fake GooglePlayProvider -- no real network/Google call ever made. Test
# configures per-token results before invoking verify_google_chatpack().
# =============================================================================

class FakeGooglePlayProvider:
    results = {}   # purchase_token -> GooglePlayProductVerification
    calls = []     # [(purchase_token, product_id, package_name), ...]

    def verify_product_purchase(self, *, purchase_token, product_id, package_name=None):
        FakeGooglePlayProvider.calls.append((purchase_token, product_id, package_name))
        result = FakeGooglePlayProvider.results.get(purchase_token)
        if result is None:
            raise AssertionError(f"test bug: no fake result configured for token {purchase_token!r}")
        return result


def verified(product_id, purchase_token, purchase_state=0, order_id=None):
    return GooglePlayProductVerification(
        verification_status=GooglePlayVerificationStatus.VERIFIED,
        purchase_token=purchase_token,
        product_id=product_id,
        purchase_state=purchase_state,
        consumption_state=0,
        order_id=order_id or f"GPA.ORDER.{purchase_token}",
    )


def not_verified(status, purchase_token, product_id=None, error_message="simulated failure"):
    return GooglePlayProductVerification(
        verification_status=status,
        purchase_token=purchase_token,
        product_id=product_id,
        error_message=error_message,
    )


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        real_provider = verify_module.GooglePlayProvider
        verify_module.GooglePlayProvider = FakeGooglePlayProvider

        try:
            # ==========================================================
            print("=== A: asknow8q -> 8 questions / Rs 51 ===")
            # ==========================================================
            FakeGooglePlayProvider.results["tok-a"] = verified("asknow8q", "tok-a")
            resultA = verify_google_chatpack(984001, "asknow8q", "tok-a")
            check("A: success True", resultA["success"] is True)
            check("A: remaining_tokens == 8", resultA["remaining_tokens"] == 8)
            packA = ChatPack.query.filter_by(user_id=984001, razorpay_payment_id="tok-a").first()
            check("A: ChatPack row created", packA is not None)
            check("A: amount == 51", packA is not None and packA.amount == 51)
            check("A: questions_total == 8", packA is not None and packA.questions_total == 8)

            # ==========================================================
            print("\n=== B: asknow10q -> 10 questions / Rs 100 ===")
            # ==========================================================
            FakeGooglePlayProvider.results["tok-b"] = verified("asknow10q", "tok-b")
            resultB = verify_google_chatpack(984002, "asknow10q", "tok-b")
            check("B: success True", resultB["success"] is True)
            check("B: remaining_tokens == 10", resultB["remaining_tokens"] == 10)
            packB = ChatPack.query.filter_by(user_id=984002, razorpay_payment_id="tok-b").first()
            check("B: amount == 100", packB is not None and packB.amount == 100)
            check("B: questions_total == 10", packB is not None and packB.questions_total == 10)

            # ==========================================================
            print("\n=== C: unknown product ID rejected -- no Google call, no ChatPack ===")
            # ==========================================================
            calls_before = len(FakeGooglePlayProvider.calls)
            resultC = verify_google_chatpack(984003, "asknow_bogus", "tok-c")
            check("C: success False", resultC["success"] is False)
            check("C: error == unknown_product", resultC.get("error") == "unknown_product")
            check("C: never asked Google (no API call attempted)", len(FakeGooglePlayProvider.calls) == calls_before)
            check("C: no ChatPack row created", ChatPack.query.filter_by(user_id=984003).first() is None)

            # ==========================================================
            print("\n=== D: invalid Google purchase (token not found) rejected ===")
            # ==========================================================
            FakeGooglePlayProvider.results["tok-d"] = not_verified(
                GooglePlayVerificationStatus.NOT_FOUND, "tok-d",
            )
            resultD = verify_google_chatpack(984004, "asknow8q", "tok-d")
            check("D: success False", resultD["success"] is False)
            check("D: error == verification_failed", resultD.get("error") == "verification_failed")
            check("D: no ChatPack row created", ChatPack.query.filter_by(user_id=984004).first() is None)

            # ==========================================================
            print("\n=== E: cancelled / pending purchase rejected ===")
            # ==========================================================
            FakeGooglePlayProvider.results["tok-e-cancel"] = verified("asknow8q", "tok-e-cancel", purchase_state=1)
            resultE1 = verify_google_chatpack(984005, "asknow8q", "tok-e-cancel")
            check("E: cancelled (purchaseState=1) -> success False", resultE1["success"] is False)
            check("E: error == purchase_not_completed", resultE1.get("error") == "purchase_not_completed")
            check("E: no ChatPack row for cancelled purchase", ChatPack.query.filter_by(user_id=984005).first() is None)

            FakeGooglePlayProvider.results["tok-e-pending"] = verified("asknow10q", "tok-e-pending", purchase_state=2)
            resultE2 = verify_google_chatpack(984006, "asknow10q", "tok-e-pending")
            check("E: pending (purchaseState=2) -> success False", resultE2["success"] is False)
            check("E: no ChatPack row for pending purchase", ChatPack.query.filter_by(user_id=984006).first() is None)

            # ==========================================================
            print("\n=== F: valid Google purchase accepted -- order_id passthrough ===")
            # ==========================================================
            FakeGooglePlayProvider.results["tok-f"] = verified("asknow10q", "tok-f", order_id="GPA.9988.7766")
            resultF = verify_google_chatpack(984007, "asknow10q", "tok-f")
            check("F: success True", resultF["success"] is True)
            packF = ChatPack.query.filter_by(user_id=984007, razorpay_payment_id="tok-f").first()
            check("F: Google's own order_id stored", packF is not None and packF.razorpay_order_id == "GPA.9988.7766")

            # ==========================================================
            print("\n=== G: same purchase token submitted twice does NOT grant twice ===")
            # ==========================================================
            FakeGooglePlayProvider.results["tok-g"] = verified("asknow8q", "tok-g")
            resultG1 = verify_google_chatpack(984008, "asknow8q", "tok-g")
            calls_after_first = len(FakeGooglePlayProvider.calls)
            resultG2 = verify_google_chatpack(984008, "asknow8q", "tok-g")
            calls_after_second = len(FakeGooglePlayProvider.calls)

            check("G: first call succeeds", resultG1["success"] is True)
            check("G: second call also reports success (recovery-safe)", resultG2["success"] is True)
            check("G: second call did NOT call Google again", calls_after_second == calls_after_first)
            packs_g = ChatPack.query.filter_by(user_id=984008, razorpay_payment_id="tok-g").all()
            check("G: exactly ONE ChatPack row exists for this token", len(packs_g) == 1)

            # ==========================================================
            print("\n=== H: retry of already-successful token is recovery-safe ===")
            # ==========================================================
            check("H: retry response has already_processed flag", resultG2.get("already_processed") is True)
            check("H: retry remaining_tokens matches original grant (8)", resultG2["remaining_tokens"] == 8)
            check("H: retry response is success-shaped (Flutter can safely consume() again)", "remaining_tokens" in resultG2 and resultG2["success"] is True)

            # ==========================================================
            print("\n=== J: Google verification failure creates no ChatPack entitlement (network/unknown error) ===")
            # ==========================================================
            FakeGooglePlayProvider.results["tok-j"] = not_verified(
                GooglePlayVerificationStatus.NETWORK_ERROR, "tok-j", error_message="simulated network failure",
            )
            resultJ = verify_google_chatpack(984009, "asknow8q", "tok-j")
            check("J: success False on network error", resultJ["success"] is False)
            check("J: no ChatPack row created on network error", ChatPack.query.filter_by(user_id=984009).first() is None)

        finally:
            verify_module.GooglePlayProvider = real_provider

        # ==========================================================
        print("\n=== I: both routes produce equivalent behavior ===")
        # ==========================================================
        verify_module.GooglePlayProvider = FakeGooglePlayProvider
        try:
            FakeGooglePlayProvider.results["tok-i-alias"] = verified("asknow10q", "tok-i-alias")
            FakeGooglePlayProvider.results["tok-i-direct"] = verified("asknow10q", "tok-i-direct")

            client = app.test_client()

            resp_alias = client.post(
                "/api/chatpack/verify",
                json={"user_id": 984010, "product_id": "asknow10q", "purchase_token": "tok-i-alias"},
            )
            resp_direct = client.post(
                "/api/chat/pack/google/verify",
                json={"user_id": 984011, "product_id": "asknow10q", "purchase_token": "tok-i-direct"},
            )

            body_alias = resp_alias.get_json()
            body_direct = resp_direct.get_json()

            check("I: /api/chatpack/verify -> 200", resp_alias.status_code == 200)
            check("I: /api/chat/pack/google/verify -> 200", resp_direct.status_code == 200)
            check("I: both report success True", body_alias.get("success") is True and body_direct.get("success") is True)
            check("I: both report remaining_tokens == 10", body_alias.get("remaining_tokens") == 10 and body_direct.get("remaining_tokens") == 10)

            # Unknown-product rejection must also be equivalent on both routes.
            resp_alias_bad = client.post(
                "/api/chatpack/verify",
                json={"user_id": 984012, "product_id": "not_a_real_product", "purchase_token": "tok-i-bad-alias"},
            )
            resp_direct_bad = client.post(
                "/api/chat/pack/google/verify",
                json={"user_id": 984013, "product_id": "not_a_real_product", "purchase_token": "tok-i-bad-direct"},
            )
            check("I: unknown product rejected equivalently on alias route", resp_alias_bad.get_json().get("error") == "unknown_product")
            check("I: unknown product rejected equivalently on direct route", resp_direct_bad.get_json().get("error") == "unknown_product")
        finally:
            verify_module.GooglePlayProvider = real_provider

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
