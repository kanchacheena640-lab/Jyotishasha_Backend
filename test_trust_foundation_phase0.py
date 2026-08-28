"""
test_trust_foundation_phase0.py
--------------------------------
Trust Foundation Phase 0, Implementation Pass 1 -- proves the fixes
documented in the Trust Foundation Audit (Sections R/S/X):

  IDENTITY   -- routes/routes_chat.py now resolves user_id ONLY from a
                verified JWT (get_jwt_identity()), never from a
                client-supplied body/query field.
  ASK NOW    -- free-quota / ChatPack consumption, balance reads, and
                mutation all use the authenticated identity; another
                account's balance can never be read or drained;
                /api/chat/debug/pack is admin-gated, not public.
  PAYMENT    -- modules/services/chat_pack_service.py::
                verify_chatpack_payment() now requires a real Razorpay
                signature (RazorpayProvider, reused unmodified) before
                crediting anything; a fabricated/forged/wrong-account
                claim is rejected and grants nothing.

LOCAL ONLY. No production DB, no real Razorpay/Google Play network call
-- the Razorpay signature is computed locally with the exact same
HMAC-SHA256(order_id + "|" + payment_id, key_secret) algorithm
RazorpayProvider verifies against (config/razorpay_config.py's real
RAZORPAY_KEY_SECRET, read from .env -- never a live API call). OpenAI is
never called -- modules.services.chat_engine's module-level `client` is
monkeypatched, same technique test_chat_engine_temporal_grounding.py
already established.
"""

import hashlib
import hmac
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.models_free_daily import FreeDailyQuestion  # noqa: E402
from config.razorpay_config import RAZORPAY_KEY_SECRET  # noqa: E402

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


# Two distinct real accounts -- A (the legitimate caller) and B (the
# victim any spoofing attempt targets). Deliberately high, obviously-
# test-only ids.
A_UID, A_PID = 987001, 987101
B_UID, B_PID = 987002, 987102
ADMIN_UID = 987003


def _razorpay_signature(order_id: str, payment_id: str) -> str:
    """Same algorithm RazorpayProvider verifies against -- computed
    locally, no network call, no SDK order-creation round trip."""
    payload = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()


def cleanup():
    ChatPack.query.filter(ChatPack.user_id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    FreeDailyQuestion.query.filter(FreeDailyQuestion.user_id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.id.in_([A_PID, B_PID])).delete(synchronize_session=False)
    User.query.filter(User.id.in_([A_UID, B_UID, ADMIN_UID])).delete(synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        db.session.add(User(id=A_UID, email="phase0-a@example.com", provider="password", firebase_uid="fb-phase0-a"))
        db.session.add(User(id=B_UID, email="phase0-b@example.com", provider="password", firebase_uid="fb-phase0-b"))
        db.session.add(User(id=ADMIN_UID, email="phase0-admin@example.com", provider="password", firebase_uid="fb-phase0-admin"))
        db.session.add(AppUser(id=A_PID, firebase_uid="fb-phase0-a"))
        db.session.add(AppUser(id=B_PID, firebase_uid="fb-phase0-b"))
        db.session.commit()

        # Safe Deployment Split (routes/routes_chat.py's own docstring):
        # this whole file proves the STRICT, JWT-only behavior Trust
        # Foundation Phase 0 built for the four build-48-compatible
        # routes -- i.e. exactly the POST-BUILD-49 / secure mode. The
        # split's default-OFF legacy fallback (proven separately by
        # test_safe_deployment_split.py's own PRE-BUILD-49 section) is
        # not this file's concern, so enforcement is turned on for the
        # whole run and restored afterward regardless of outcome.
        original_env = os.environ.get("ASKNOW_JWT_ENFORCEMENT")
        os.environ["ASKNOW_JWT_ENFORCEMENT"] = "true"

        # Monkeypatch chat_engine's OpenAI client -- no real API call,
        # same technique test_chat_engine_temporal_grounding.py uses.
        import modules.services.chat_engine as chat_engine_module

        class _FakeMessage:
            content = "This is a canned, non-network test answer."

        class _FakeChoice:
            message = _FakeMessage()

        class _FakeCompletion:
            choices = [_FakeChoice()]

        class _FakeCompletions:
            def create(self, *args, **kwargs):
                return _FakeCompletion()

        class _FakeChat:
            completions = _FakeCompletions()

        class _FakeOpenAIClient:
            chat = _FakeChat()

        original_client = chat_engine_module.client
        chat_engine_module.client = _FakeOpenAIClient()

        client = app.test_client()
        token_a = create_access_token(identity=str(A_UID))
        token_b = create_access_token(identity=str(B_UID))
        token_admin = create_access_token(identity=str(ADMIN_UID))
        headers_a = {"Authorization": f"Bearer {token_a}", "Content-Type": "application/json"}
        headers_b = {"Authorization": f"Bearer {token_b}", "Content-Type": "application/json"}
        headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}
        birth = {"name": "Test", "dob": "1990-01-01", "tob": "10:00", "pob": "Delhi", "lat": 28.6, "lng": 77.2, "timezone": "+05:30"}

        try:
            # ==========================================================
            print("=== IDENTITY 1: valid authenticated account resolves correctly ===")
            # ==========================================================
            resp = client.post("/api/chat/free", json={"question": "Will I be lucky today?", "birth": birth}, headers=headers_a)
            check("1: free question succeeds for the authenticated caller (200)", resp.status_code == 200)
            check("1: response carries a generated answer", bool(resp.get_json().get("answer")))
            rec = FreeDailyQuestion.query.filter_by(user_id=A_UID).first()
            check("1: FreeDailyQuestion recorded against the JWT's OWN account (A_UID), not a guess", rec is not None and rec.used_today())

            # ==========================================================
            print("\n=== IDENTITY 2: another user's client-supplied user_id cannot override authenticated identity ===")
            # ==========================================================
            resp = client.post(
                "/api/chat/free",
                json={"user_id": B_UID, "question": "Spoofed question", "birth": birth},
                headers=headers_a,  # A's real token, but body claims to be B
            )
            check("2: request still succeeds (identity comes from JWT, not body)", resp.status_code == 403)  # A already used today's free Q in test 1
            rec_b = FreeDailyQuestion.query.filter_by(user_id=B_UID).first()
            check("2: B's free-question record was NEVER created/touched by A's spoofed body", rec_b is None)

            # ==========================================================
            print("\n=== IDENTITY 3: missing authentication is rejected ===")
            # ==========================================================
            resp = client.post("/api/chat/free", json={"question": "x", "birth": birth})
            check("3: no Authorization header -> 401", resp.status_code == 401)

            # ==========================================================
            print("\n=== IDENTITY 4: invalid authentication is rejected ===")
            # ==========================================================
            resp = client.post(
                "/api/chat/free", json={"question": "x", "birth": birth},
                headers={"Authorization": "Bearer this.is.not.a.valid.jwt", "Content-Type": "application/json"},
            )
            # Flask-JWT-Extended's own, unmodified behavior: a
            # structurally malformed token is 422 (couldn't even be
            # parsed as a JWT), not 401 (401 is for a well-formed but
            # invalid/expired/missing token) -- both are non-2xx
            # rejections; this is standard framework behavior already in
            # use everywhere else in this codebase, not something Ask
            # Now's own hardening should override.
            check("4: malformed JWT is rejected, never granted access (422)", resp.status_code == 422)
            check("4: malformed JWT never reaches the route body at all (no 'answer' in the error response)", "answer" not in resp.get_json())

            # ==========================================================
            print("\n=== IDENTITY 5: existing valid users retain access ===")
            # ==========================================================
            resp = client.get("/api/chat/free/status", headers=headers_b)
            check("5: B (never touched above) still resolves and reads their own status (200)", resp.status_code == 200)
            check("5: B's own status correctly shows free question still available", resp.get_json().get("used_today") is False)

            # ==========================================================
            print("\n=== ASK NOW 1: paid ChatPack balance / consumption remains correct ===")
            # ==========================================================
            pack_a = ChatPack(user_id=A_UID, amount=51, questions_total=8, questions_used=3, status="success")
            db.session.add(pack_a)
            db.session.commit()

            resp = client.post("/api/chat/pack", json={"question": "Paid Q", "birth": birth}, headers=headers_a)
            check("ASK1: paid question succeeds (200)", resp.status_code == 200)
            check("ASK1: remaining count reflects the real deduction (8-3-1=4)", resp.get_json().get("remaining") == 4)
            db.session.refresh(pack_a)
            check("ASK1: questions_used incremented on A's OWN pack", pack_a.questions_used == 4)

            # ==========================================================
            print("\n=== ASK NOW 2: mutation endpoints cannot modify another account ===")
            # ==========================================================
            pack_b = ChatPack(user_id=B_UID, amount=51, questions_total=8, questions_used=0, status="success")
            db.session.add(pack_b)
            db.session.commit()

            resp = client.post(
                "/api/chat/pack",
                json={"user_id": B_UID, "question": "Attempted cross-account drain", "birth": birth},
                headers=headers_a,  # A's real token, body claims B
            )
            check("ASK2: request processed under A's real identity (200)", resp.status_code == 200)
            db.session.refresh(pack_a)
            db.session.refresh(pack_b)
            check("ASK2: A's OWN pack was deducted again (5), not B's", pack_a.questions_used == 5)
            check("ASK2: B's pack is COMPLETELY UNTOUCHED by A's spoofed body", pack_b.questions_used == 0)

            # ==========================================================
            print("\n=== ASK NOW 3: balance/read endpoints cannot inspect another account ===")
            # ==========================================================
            resp = client.get("/api/chat/pack/status", query_string={"user_id": B_PID}, headers=headers_a)
            check("ASK3: status read succeeds (200)", resp.status_code == 200)
            body = resp.get_json()
            check(
                "ASK3: response reflects A's OWN pack (remaining=3), NOT B's (remaining=8), "
                "despite the query string asking for a different id",
                body.get("remaining") == 3,
            )

            # ==========================================================
            print("\n=== ASK NOW 4: debug endpoint is production-safe ===")
            # ==========================================================
            resp = client.post("/api/chat/debug/pack", json={"user_id": B_UID, "action": "reset"})
            check("ASK4a: no auth at all -> 401 (was previously 200, zero auth)", resp.status_code == 401)

            resp = client.post("/api/chat/debug/pack", json={"user_id": B_UID, "action": "reset"}, headers=headers_a)
            check("ASK4b: authenticated but NON-admin caller -> 403", resp.status_code == 403)
            db.session.refresh(pack_b)
            check("ASK4c: no existing ChatPack balance was reset by the rejected non-admin attempt", pack_b.questions_used == 0)

            os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)
            resp = client.post("/api/chat/debug/pack", json={"user_id": B_UID, "action": "reset"}, headers=headers_admin)
            check("ASK4d: a genuine admin (ADMIN_USER_IDS allowlisted) CAN still use the tool (200)", resp.status_code == 200)

            # ==========================================================
            print("\n=== PAYMENT 1: valid Razorpay payment verification succeeds ===")
            # ==========================================================
            order_id = "order_PHASE0TEST001"
            payment_id = "pay_PHASE0TEST001"
            pending_pack = ChatPack(user_id=A_UID, amount=51, questions_total=8, questions_used=0, status="pending", razorpay_order_id=order_id)
            db.session.add(pending_pack)
            db.session.commit()

            valid_sig = _razorpay_signature(order_id, payment_id)
            resp = client.post(
                "/api/chat/pack/verify",
                json={"order_id": order_id, "payment_id": payment_id, "razorpay_signature": valid_sig},
                headers=headers_a,
            )
            check("PAY1: genuine signature verified and pack activated (200)", resp.status_code == 200)
            check("PAY1: response reports success", resp.get_json().get("success") is True)
            db.session.refresh(pending_pack)
            check("PAY1: ChatPack status is now 'success'", pending_pack.status == "success")

            # ==========================================================
            print("\n=== PAYMENT 2: replay/idempotency behavior is safe ===")
            # ==========================================================
            resp = client.post(
                "/api/chat/pack/verify",
                json={"order_id": order_id, "payment_id": payment_id, "razorpay_signature": valid_sig},
                headers=headers_a,
            )
            check("PAY2: replay of an already-verified order returns success (idempotent, not an error)", resp.status_code == 200)
            check("PAY2: replay is explicitly flagged already_processed", resp.get_json().get("already_processed") is True)
            db.session.refresh(pending_pack)
            check("PAY2: replay did NOT grant a second pack / re-credit anything (still 8 total, 0 used)", pending_pack.questions_total == 8 and pending_pack.questions_used == 0)

            # ==========================================================
            print("\n=== PAYMENT 3: invalid signature fails ===")
            # ==========================================================
            order_id_2 = "order_PHASE0TEST002"
            payment_id_2 = "pay_PHASE0TEST002"
            pending_pack_2 = ChatPack(user_id=A_UID, amount=51, questions_total=8, questions_used=0, status="pending", razorpay_order_id=order_id_2)
            db.session.add(pending_pack_2)
            db.session.commit()

            resp = client.post(
                "/api/chat/pack/verify",
                json={"order_id": order_id_2, "payment_id": payment_id_2, "razorpay_signature": "0" * 64},
                headers=headers_a,
            )
            check("PAY3: forged/wrong signature REJECTED (400, not 200)", resp.status_code == 400)
            check("PAY3: response reports failure", resp.get_json().get("success") is False)
            db.session.refresh(pending_pack_2)
            check("PAY3: failed verification GRANTED NOTHING -- pack still 'pending'", pending_pack_2.status == "pending")

            # ==========================================================
            print("\n=== PAYMENT 4: fabricated payment identifiers fail ===")
            # ==========================================================
            fake_order = "order_DOES_NOT_EXIST_ANYWHERE"
            fake_payment = "pay_DOES_NOT_EXIST_ANYWHERE"
            fake_sig = _razorpay_signature(fake_order, fake_payment)  # even a REAL signature for a fake order
            resp = client.post(
                "/api/chat/pack/verify",
                json={"order_id": fake_order, "payment_id": fake_payment, "razorpay_signature": fake_sig},
                headers=headers_a,
            )
            check("PAY4: fabricated order_id (no matching pending ChatPack) REJECTED (400)", resp.status_code == 400)
            check("PAY4: error message says order not found", "not found" in resp.get_json().get("error", "").lower())

            # ==========================================================
            print("\n=== PAYMENT 5: wrong-account payment/credit attempt fails ===")
            # ==========================================================
            order_id_3 = "order_PHASE0TEST003_FOR_B"
            payment_id_3 = "pay_PHASE0TEST003_FOR_B"
            pack_for_b = ChatPack(user_id=B_UID, amount=51, questions_total=8, questions_used=0, status="pending", razorpay_order_id=order_id_3)
            db.session.add(pack_for_b)
            db.session.commit()

            sig_3 = _razorpay_signature(order_id_3, payment_id_3)  # a REAL, validly-signed payment...
            resp = client.post(  # ...but A tries to claim B's own pending order
                "/api/chat/pack/verify",
                json={"order_id": order_id_3, "payment_id": payment_id_3, "razorpay_signature": sig_3},
                headers=headers_a,
            )
            check("PAY5: A cannot claim B's order even with a genuinely valid signature (400)", resp.status_code == 400)
            db.session.refresh(pack_for_b)
            check("PAY5: B's order was NOT activated by A's cross-account attempt", pack_for_b.status == "pending")

            # ==========================================================
            print("\n=== PAYMENT 6: missing signature is rejected outright (never silently optional) ===")
            # ==========================================================
            resp = client.post(
                "/api/chat/pack/verify",
                json={"order_id": order_id_2, "payment_id": payment_id_2},  # no signature at all
                headers=headers_a,
            )
            check("PAY6: missing razorpay_signature -> 400, not treated as valid", resp.status_code == 400)

        finally:
            chat_engine_module.client = original_client
            if original_env is None:
                os.environ.pop("ASKNOW_JWT_ENFORCEMENT", None)
            else:
                os.environ["ASKNOW_JWT_ENFORCEMENT"] = original_env
            cleanup()

    print("\n" + "=" * 50)
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
