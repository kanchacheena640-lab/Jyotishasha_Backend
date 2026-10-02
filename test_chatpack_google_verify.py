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
  K. Ask Now P0 HTTP contract on /api/chatpack/verify: 401 without JWT,
     body user_id mismatch credited to the JWT user only (warning logged),
     non-2xx for every rejection, 200 only for a grant or idempotent
     replay, generic 500, authoritative balance

NO REAL GOOGLE PLAY API CALL IS EVER MADE -- GooglePlayProvider is
monkeypatched at the module level used by chatpack_google_verify.py.
Uses the LOCAL scratch Postgres DB ONLY.
"""

import contextlib
import logging
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
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
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


USER_IDS = list(range(984001, 984040))


def cleanup():
    ChatPack.query.filter(ChatPack.user_id.in_(USER_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


def _auth_headers(user_id: int) -> dict:
    """
    Trust Foundation Phase 0: /api/chatpack/verify and
    /api/chat/pack/google/verify now require a verified JWT -- user_id
    is resolved from get_jwt_identity(), never trusted from the request
    body. Mints a real backend session for the given account, same
    pattern test_google_subscription_confirm_contract.py already
    established.
    """
    if User.query.get(user_id) is None:
        db.session.add(User(id=user_id, email=f"chatpack-verify-{user_id}@example.com", provider="password"))
        db.session.commit()
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


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


class RaisingGooglePlayProvider:
    def verify_product_purchase(self, *, purchase_token, product_id, package_name=None):
        raise RuntimeError("simulated crash SECRET-PROVIDER-DETAIL")


def _packs(user_id):
    return ChatPack.query.filter_by(user_id=user_id).all()


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextlib.contextmanager
def _capture_logger(name):
    logger = logging.getLogger(name)
    handler = _ListHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _run_http_contract_section(client):
    """K -- Ask Now P0 HTTP contract on /api/chatpack/verify (the route the
    app calls): every rejection is non-2xx, only grant/replay is 2xx +
    success=true, identity is the JWT's, and no entitlement on failure."""
    alias = "/api/chatpack/verify"
    real_provider = verify_module.GooglePlayProvider
    verify_module.GooglePlayProvider = FakeGooglePlayProvider
    try:
        print("\n=== K1: valid JWT + valid asknow10q -> 200, persisted, authoritative balance ===")
        FakeGooglePlayProvider.results["tok-k1"] = verified("asknow10q", "tok-k1")
        r = client.post(alias, json={"user_id": 984020, "product_id": "asknow10q", "purchase_token": "tok-k1"},
                        headers=_auth_headers(984020))
        body = r.get_json() or {}
        check("K1: 200", r.status_code == 200)
        check("K1: success True", body.get("success") is True)
        check("K1: exactly one ChatPack persisted (10 q, Rs 100)",
              [(p.questions_total, p.amount) for p in _packs(984020)] == [(10, 100)])
        check("K1: remaining_tokens == 10", body.get("remaining_tokens") == 10)
        status = client.get("/api/chat/status", headers=_auth_headers(984020)).get_json() or {}
        check("K1: verify balance == /api/chat/status balance",
              status.get("remaining_tokens") == body.get("remaining_tokens"))

        print("\n=== K2: missing JWT -> 401, no entitlement, Google never called ===")
        FakeGooglePlayProvider.results["tok-k2"] = verified("asknow10q", "tok-k2")
        calls_before = len(FakeGooglePlayProvider.calls)
        r = client.post(alias, json={"user_id": 984021, "product_id": "asknow10q", "purchase_token": "tok-k2"})
        check("K2: 401", r.status_code == 401)
        check("K2: no ChatPack", _packs(984021) == [])
        check("K2: Google never called", len(FakeGooglePlayProvider.calls) == calls_before)

        print("\n=== K3: JWT user != body user_id -> verified, credited ONLY to JWT user, warning logged ===")
        FakeGooglePlayProvider.results["tok-k3"] = verified("asknow10q", "tok-k3")
        with _capture_logger("chatpack_verify") as k3_logs:
            r = client.post(alias, json={"user_id": 984023, "product_id": "asknow10q", "purchase_token": "tok-k3"},
                            headers=_auth_headers(984022))
        body = r.get_json() or {}
        check("K3: 200", r.status_code == 200)
        check("K3: success True", body.get("success") is True)
        check("K3: exactly one ChatPack credited to JWT user (10 q)",
              [p.questions_total for p in _packs(984022)] == [10])
        check("K3: zero ChatPacks for claimed/mismatching user", _packs(984023) == [])
        check("K3: balance is the JWT user's (10)", body.get("remaining_tokens") == 10)
        warnings = [m for m in k3_logs if "differs from JWT identity" in m]
        check("K3: mismatch warning logged once", len(warnings) == 1)
        check("K3: warning names both ids", warnings and "jwt_user_id=984022" in warnings[0] and "body_user_id=984023" in warnings[0])
        check("K3: purchase token never logged", all("tok-k3" not in m for m in k3_logs))
        r_again = client.post(alias, json={"user_id": 984023, "product_id": "asknow10q", "purchase_token": "tok-k3"},
                              headers=_auth_headers(984022))
        check("K3: replay 200 already_processed", r_again.status_code == 200 and (r_again.get_json() or {}).get("already_processed") is True)
        check("K3: no double credit (still one ChatPack for JWT user)", len(_packs(984022)) == 1)
        check("K3: still zero ChatPacks for claimed user", _packs(984023) == [])

        print("\n=== K4: Play verification rejected -> non-2xx, no entitlement ===")
        cases = [
            ("tok-k4-notfound", not_verified(GooglePlayVerificationStatus.NOT_FOUND, "tok-k4-notfound",
                                             error_message="SECRET-GOOGLE-TEXT"), 422, 984024),
            ("tok-k4-invalid", not_verified(GooglePlayVerificationStatus.INVALID_TOKEN, "tok-k4-invalid"), 422, 984025),
            ("tok-k4-network", not_verified(GooglePlayVerificationStatus.NETWORK_ERROR, "tok-k4-network"), 502, 984026),
            ("tok-k4-auth", not_verified(GooglePlayVerificationStatus.AUTH_ERROR, "tok-k4-auth"), 502, 984027),
            ("tok-k4-pending", verified("asknow10q", "tok-k4-pending", purchase_state=2), 409, 984028),
            ("tok-k4-cancel", verified("asknow10q", "tok-k4-cancel", purchase_state=1), 409, 984029),
        ]
        for tok, fake, expected, uid in cases:
            FakeGooglePlayProvider.results[tok] = fake
            r = client.post(alias, json={"product_id": "asknow10q", "purchase_token": tok}, headers=_auth_headers(uid))
            b = r.get_json() or {}
            check(f"K4 {tok}: HTTP {expected}", r.status_code == expected)
            check(f"K4 {tok}: success False", b.get("success") is False)
            check(f"K4 {tok}: no ChatPack", _packs(uid) == [])
            check(f"K4 {tok}: no provider text/token in body",
                  "SECRET-GOOGLE-TEXT" not in r.get_data(as_text=True) and tok not in r.get_data(as_text=True))

        print("\n=== K5: duplicate/replayed token -> 200 success, no double credit ===")
        r2 = client.post(alias, json={"product_id": "asknow10q", "purchase_token": "tok-k1"}, headers=_auth_headers(984020))
        b2 = r2.get_json() or {}
        check("K5: 200", r2.status_code == 200)
        check("K5: success True + already_processed", b2.get("success") is True and b2.get("already_processed") is True)
        check("K5: still exactly one ChatPack", len(_packs(984020)) == 1)
        check("K5: balance unchanged (10)", b2.get("remaining_tokens") == 10)

        print("\n=== K6: unknown product / missing fields / malformed JSON -> 400 ===")
        r = client.post(alias, json={"product_id": "asknow_bogus", "purchase_token": "tok-k6"}, headers=_auth_headers(984030))
        check("K6: unknown product 400", r.status_code == 400 and (r.get_json() or {}).get("error") == "unknown_product")
        r = client.post(alias, json={"product_id": "asknow10q"}, headers=_auth_headers(984030))
        check("K6: missing token 400", r.status_code == 400 and (r.get_json() or {}).get("error") == "missing_fields")
        r = client.post(alias, data="{not json", headers=_auth_headers(984030))
        check("K6: malformed JSON 400", r.status_code == 400)
        check("K6: no ChatPack", _packs(984030) == [])

        print("\n=== K7: unexpected server exception -> generic 500, no leak, no entitlement ===")
        verify_module.GooglePlayProvider = RaisingGooglePlayProvider
        r = client.post(alias, json={"product_id": "asknow10q", "purchase_token": "tok-k7"}, headers=_auth_headers(984031))
        check("K7: 500", r.status_code == 500)
        check("K7: error == internal_error", (r.get_json() or {}).get("error") == "internal_error")
        check("K7: exception text not leaked", "SECRET-PROVIDER-DETAIL" not in r.get_data(as_text=True))
        check("K7: no ChatPack", _packs(984031) == [])

        print("\n=== K8: matching body user_id is accepted (current app payload shape) ===")
        verify_module.GooglePlayProvider = FakeGooglePlayProvider
        FakeGooglePlayProvider.results["tok-k8"] = verified("asknow10q", "tok-k8")
        r = client.post(alias, json={"user_id": "984032", "product_id": "asknow10q", "purchase_token": "tok-k8"},
                        headers=_auth_headers(984032))
        check("K8: 200 with string-typed matching user_id", r.status_code == 200)
        check("K8: one ChatPack", len(_packs(984032)) == 1)
    finally:
        verify_module.GooglePlayProvider = real_provider


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
                json={"product_id": "asknow10q", "purchase_token": "tok-i-alias"},
                headers=_auth_headers(984010),
            )
            resp_direct = client.post(
                "/api/chat/pack/google/verify",
                json={"product_id": "asknow10q", "purchase_token": "tok-i-direct"},
                headers=_auth_headers(984011),
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
                json={"product_id": "not_a_real_product", "purchase_token": "tok-i-bad-alias"},
                headers=_auth_headers(984012),
            )
            resp_direct_bad = client.post(
                "/api/chat/pack/google/verify",
                json={"product_id": "not_a_real_product", "purchase_token": "tok-i-bad-direct"},
                headers=_auth_headers(984013),
            )
            check("I: unknown product rejected equivalently on alias route", resp_alias_bad.get_json().get("error") == "unknown_product")
            check("I: unknown product rejected equivalently on direct route", resp_direct_bad.get_json().get("error") == "unknown_product")
        finally:
            verify_module.GooglePlayProvider = real_provider

        _run_http_contract_section(app.test_client())

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
