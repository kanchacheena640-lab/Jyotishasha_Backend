"""
test_asknow_credit_safety.py
-------------------------------
Ask Now Credit Safety + Live Balance Reconciliation Fix -- backend half.

Covers, against /api/chat/free and /api/chat/pack:
  1. Free success -- exactly one free quota consumed.
  2. Free generation exception -- request fails cleanly AND free quota
     restored (exact restoration, not a blanket reset).
  3. Pack/Earned success -- exactly one question consumed.
  4. Pack/Earned generation exception -- exactly one question restored.
  5. Compensation does not reset the entire pack (questions_total and
     any pre-existing questions_used are left exactly as they were).
  6. Failure before consumption (no free quota / no active pack) grants
     or refunds nothing.
  7. chat_engine()'s existing OpenAI-fallback-text behavior still counts
     as a successful, consumed question (a route-level mock standing in
     for "chat_engine() returned normally" -- chat_engine() itself
     already never raises for an OpenAI-side failure).
  8. Existing auth/JWT behavior unchanged (both build-49-style JWT and
     legacy build-48-style body user_id, with ASKNOW_JWT_ENFORCEMENT
     left unset/OFF).
  9. Existing Ask Now pricing/product semantics unchanged
     (CHATPACK_AMOUNT/CHATPACK_QUESTIONS untouched).

chat_engine is monkeypatched at the exact name routes_chat.py imported
it under (routes_chat.chat_engine) -- no real OpenAI/kundali call is
ever made. Uses the LOCAL scratch Postgres DB ONLY.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.pop("ASKNOW_JWT_ENFORCEMENT", None)  # explicit: stays OFF for this whole file

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_free_daily import FreeDailyQuestion  # noqa: E402
from modules.models_chat_pack import ChatPack  # noqa: E402

import routes.routes_chat as routes_chat_module  # noqa: E402
import modules.services.chat_engine as chat_engine_module  # noqa: E402
from openai import APITimeoutError  # noqa: E402
from modules.services.chat_pack_service import CHATPACK_AMOUNT, CHATPACK_QUESTIONS  # noqa: E402

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


USER_IDS = list(range(985501, 985520))
BIRTH = {
    "name": "Test",
    "dob": "1990-01-01",
    "tob": "10:00",
    "pob": "Delhi",
    "lat": 28.6,
    "lng": 77.2,
    "tz": "+05:30",
}


def cleanup():
    FreeDailyQuestion.query.filter(FreeDailyQuestion.user_id.in_(USER_IDS)).delete(synchronize_session=False)
    ChatPack.query.filter(ChatPack.user_id.in_(USER_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


def _ensure_user(user_id: int):
    if User.query.get(user_id) is None:
        db.session.add(User(id=user_id, email=f"asknow-credit-{user_id}@example.com", provider="password"))
        db.session.commit()


def _auth_headers(user_id: int) -> dict:
    _ensure_user(user_id)
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _make_pack(user_id: int, questions_total: int, questions_used: int) -> ChatPack:
    pack = ChatPack(
        user_id=user_id,
        amount=0,
        questions_total=questions_total,
        questions_used=questions_used,
        status="success",
        razorpay_order_id="TEST",
        razorpay_payment_id="TEST",
    )
    db.session.add(pack)
    db.session.commit()
    return pack


class _RaisingChatEngine:
    """Stands in for a generation-path exception (e.g.
    generate_full_kundali_payload() throwing) -- routes_chat.chat_engine
    is monkeypatched to this."""

    def __call__(self, birth, question):
        raise RuntimeError("simulated kundali/generation failure")


def _fallback_answer_chat_engine(birth, question):
    """
    Stands in for chat_engine()'s own existing behavior when OpenAI
    itself failed internally -- chat_engine() already catches that and
    returns a normal dict with a fallback text answer, never raises.
    The route must treat this exactly like any other successful
    generation (consumed, not compensated).
    """
    return {
        "answer": "AI temporarily unavailable. Error: simulated OpenAI outage",
        "kundali_preview": None,
        "dasha_preview": {},
        "transit_preview": {},
        "disclaimer": "This answer is for astrological guidance only.",
    }


def _real_answer_chat_engine(birth, question):
    return {
        "answer": "A real generated answer.",
        "kundali_preview": "Leo",
        "dasha_preview": {},
        "transit_preview": {},
        "disclaimer": "This answer is for astrological guidance only.",
    }


class _SeamProbeCompletions:
    def __init__(self, state, create_fn):
        self._state = state
        self._create_fn = create_fn

    def create(self, **kwargs):
        self._state["create_called"] = True
        self._state["create_kwargs"] = kwargs
        return self._create_fn(**kwargs)


class _SeamProbeChat:
    def __init__(self, state, create_fn):
        self.completions = _SeamProbeCompletions(state, create_fn)


class _SeamProbeOpenAIClient:
    """
    Ask Now OpenAI Client Test-Seam Regression fix -- proof fixture.

    A faithful-enough OpenAI client double proving chat_engine.py's
    monkeypatch seam (chat_engine_module.client, reassigned BEFORE
    chat_engine() runs) is honored end to end: with_options() is
    called with the exact kwargs chat_engine() uses, and the object IT
    RETURNS -- a distinct instance on every call, matching the real
    SDK's own with_options() semantics, deliberately never literally
    `self` -- is what actually serves chat.completions.create(). No
    import-time-cached client can bypass this, because chat_engine()
    now reads chat_engine_module.client fresh on every call.

    `create_fn` receives the exact create(**kwargs) call and returns/
    raises whatever the test needs (a canned answer, an
    APITimeoutError, ...). `state` is a single shared dict -- the
    original probe and every scoped instance with_options() returns
    write into the SAME dict, so assertions against it after the call
    are correct regardless of which instance ended up serving the
    request.
    """

    def __init__(self, create_fn, state=None):
        self._create_fn = create_fn
        self.state = state if state is not None else {
            "with_options_kwargs": None,
            "create_called": False,
            "create_kwargs": None,
        }
        self.chat = _SeamProbeChat(self.state, create_fn)

    def with_options(self, **kwargs):
        self.state["with_options_kwargs"] = kwargs
        return _SeamProbeOpenAIClient(self._create_fn, state=self.state)


def main():
    with app.app_context():
        cleanup()
        original_chat_engine = routes_chat_module.chat_engine

        try:
            client = app.test_client()

            # ==================================================
            print("\n=== 1: Free success -- exactly one free quota consumed ===")
            # ==================================================
            uid = USER_IDS[0]
            routes_chat_module.chat_engine = _real_answer_chat_engine
            resp = client.post(
                "/api/chat/free",
                json={"question": "What about my career?", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("1: 200 on success", resp.status_code == 200)
            check(
                "1: answer present",
                "A real generated answer." in resp.get_json().get("answer", {}).get("answer", ""),
            )
            record = FreeDailyQuestion.query.filter_by(user_id=uid).first()
            from datetime import date
            check("1: free quota consumed (last_used_date == today)", record.last_used_date == date.today().strftime("%Y-%m-%d"))

            # Immediately asking again today is correctly rejected -- proves
            # exactly ONE consumption happened, not zero and not double.
            resp2 = client.post(
                "/api/chat/free",
                json={"question": "Another one?", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("1: second free attempt same day -> 403 (already used)", resp2.status_code == 403)

            # ==================================================
            print("\n=== 2: Free generation exception -- fails cleanly AND quota restored ===")
            # ==================================================
            uid = USER_IDS[1]
            routes_chat_module.chat_engine = _RaisingChatEngine()
            resp = client.post(
                "/api/chat/free",
                json={"question": "Will this fail?", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("2: controlled JSON error, not a raw 500", resp.status_code == 502)
            body = resp.get_json()
            check("2: structured error body", body is not None and body.get("success") is False and body.get("error") == "generation_failed")
            check("2: no internal exception text leaked", "RuntimeError" not in str(body) and "Traceback" not in str(body))

            # Quota must be genuinely restored -- a fresh free attempt for
            # the SAME user, SAME day, must now succeed (not 403).
            routes_chat_module.chat_engine = _real_answer_chat_engine
            resp2 = client.post(
                "/api/chat/free",
                json={"question": "Retry after failure", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("2: free quota restored -- retry same day succeeds (200)", resp2.status_code == 200)

            # ==================================================
            print("\n=== 3: Pack/Earned success -- exactly one question consumed ===")
            # ==================================================
            uid = USER_IDS[2]
            pack = _make_pack(uid, questions_total=10, questions_used=3)
            routes_chat_module.chat_engine = _real_answer_chat_engine
            resp = client.post(
                "/api/chat/pack",
                json={"question": "Pack question", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("3: 200 on success", resp.status_code == 200)
            check("3: remaining reflects exactly one consumed (10-4=6)", resp.get_json().get("remaining") == 6)
            db.session.refresh(pack)
            check("3: questions_used incremented by exactly 1 (3 -> 4)", pack.questions_used == 4)

            # ==================================================
            print("\n=== 4/5: Pack generation exception -- exactly one restored, NOT a full pack reset ===")
            # ==================================================
            uid = USER_IDS[3]
            pack2 = _make_pack(uid, questions_total=10, questions_used=3)  # pre-existing usage, must survive untouched
            routes_chat_module.chat_engine = _RaisingChatEngine()
            resp = client.post(
                "/api/chat/pack",
                json={"question": "Will this fail?", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("4: controlled JSON error, not a raw 500", resp.status_code == 502)
            db.session.refresh(pack2)
            check(
                "4/5: exactly ONE question restored -- back to the pre-existing 3, not reset to 0",
                pack2.questions_used == 3,
            )
            check("5: questions_total untouched (still 10, not reset/changed)", pack2.questions_total == 10)

            # Retry must succeed and consume exactly one again.
            routes_chat_module.chat_engine = _real_answer_chat_engine
            resp2 = client.post(
                "/api/chat/pack",
                json={"question": "Retry after failure", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("4: retry after restoration succeeds (200)", resp2.status_code == 200)
            db.session.refresh(pack2)
            check("4: retry consumed exactly one (3 -> 4)", pack2.questions_used == 4)

            # ==================================================
            print("\n=== 6: Failure BEFORE consumption grants/refunds nothing ===")
            # ==================================================
            uid = USER_IDS[4]
            routes_chat_module.chat_engine = _real_answer_chat_engine  # irrelevant -- must never be reached
            resp = client.post(
                "/api/chat/pack",
                json={"question": "No pack at all", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("6: no active pack -> 403, no crash", resp.status_code == 403)
            check("6: no ChatPack row was created as a side effect", ChatPack.query.filter_by(user_id=uid).count() == 0)

            uid2 = USER_IDS[5]
            # Use up today's free quota first via a clean success, then
            # attempt again -- the SECOND attempt must not touch anything.
            resp_ok = client.post(
                "/api/chat/free",
                json={"question": "Use it up", "birth": BIRTH},
                headers=_auth_headers(uid2),
            )
            check("6b: setup free-success", resp_ok.status_code == 200)
            record_before = FreeDailyQuestion.query.filter_by(user_id=uid2).first().last_used_date
            resp_blocked = client.post(
                "/api/chat/free",
                json={"question": "Already used", "birth": BIRTH},
                headers=_auth_headers(uid2),
            )
            check("6b: already-used free attempt -> 403", resp_blocked.status_code == 403)
            record_after = FreeDailyQuestion.query.filter_by(user_id=uid2).first().last_used_date
            check("6b: last_used_date unchanged by the blocked attempt", record_before == record_after)

            # ==================================================
            print("\n=== 7: OpenAI-internal-fallback-text still counts as a successful, consumed question ===")
            # ==================================================
            uid = USER_IDS[6]
            routes_chat_module.chat_engine = _fallback_answer_chat_engine
            resp = client.post(
                "/api/chat/free",
                json={"question": "Trigger fallback", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("7: 200, NOT treated as a failure", resp.status_code == 200)
            check("7: fallback text delivered as the answer", "temporarily unavailable" in resp.get_json().get("answer", {}).get("answer", ""))
            record = FreeDailyQuestion.query.filter_by(user_id=uid).first()
            check("7: free quota WAS consumed (fallback text is a valid delivered answer)", record is not None and record.last_used_date == date.today().strftime("%Y-%m-%d"))

            # ==================================================
            print("\n=== 8: Existing auth/JWT behavior unchanged (build-49 JWT + legacy build-48 body user_id) ===")
            # ==================================================
            uid = USER_IDS[7]
            routes_chat_module.chat_engine = _real_answer_chat_engine
            resp = client.post(
                "/api/chat/free",
                json={"question": "JWT path", "birth": BIRTH},
                headers=_auth_headers(uid),
            )
            check("8: build-49-style JWT path still works (200)", resp.status_code == 200)

            uid_legacy = USER_IDS[8]
            _ensure_user(uid_legacy)
            resp_legacy = client.post(
                "/api/chat/free",
                json={"question": "Legacy path", "birth": BIRTH, "user_id": uid_legacy},
                headers={"Content-Type": "application/json"},  # no Authorization -- build-48 shape
            )
            check(
                "8: legacy build-48 body user_id path still works with ASKNOW_JWT_ENFORCEMENT off (200)",
                resp_legacy.status_code == 200,
            )

            resp_noauth_strict_check = client.post(
                "/api/chat/free",
                json={"question": "No identity at all"},  # no birth, no user_id -- existing 400 path
                headers={"Content-Type": "application/json"},
            )
            check("8: still 400 for a genuinely malformed request (missing fields)", resp_noauth_strict_check.status_code == 400)

            # ==================================================
            print("\n=== 9: Ask Now pricing/product semantics unchanged ===")
            # ==================================================
            check("9: CHATPACK_AMOUNT unchanged (Rs 51)", CHATPACK_AMOUNT == 51)
            check("9: CHATPACK_QUESTIONS unchanged (8)", CHATPACK_QUESTIONS == 8)

            # ==================================================
            print("\n=== 10: Ask Now Timeout Delivery Fix -- OpenAI timeout vs. other OpenAI failures ===")
            # ==================================================
            # This section exercises the REAL chat_engine() (not the
            # route-level chat_engine mock used everywhere above) with
            # only the OpenAI call itself mocked -- via the CORRECT,
            # regression-fixed seam (chat_engine_module.client, read
            # fresh at call time -- see _SeamProbeOpenAIClient's own
            # docstring) -- to prove the distinction: a timeout is
            # compensated like any other generation failure, while
            # every OTHER OpenAI-side failure still degrades to a
            # delivered, consumed fallback answer -- unchanged from the
            # original Credit Safety Fix.
            routes_chat_module.chat_engine = original_chat_engine
            original_client = chat_engine_module.client

            import httpx

            def _timeout_create(**kwargs):
                raise APITimeoutError(httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

            def _other_failure_create(**kwargs):
                raise RuntimeError("simulated non-timeout OpenAI failure")

            uid = USER_IDS[9]
            timeout_probe = _SeamProbeOpenAIClient(_timeout_create)
            chat_engine_module.client = timeout_probe
            try:
                resp = client.post(
                    "/api/chat/free",
                    json={"question": "Will OpenAI time out?", "birth": BIRTH},
                    headers=_auth_headers(uid),
                )
            finally:
                chat_engine_module.client = original_client

            check("10: OpenAI timeout -> controlled 502, not a raw crash", resp.status_code == 502)
            check("10: OpenAI timeout classified as generation_failed", resp.get_json().get("error") == "generation_failed")
            check("10: the monkeypatched fake was actually reached (no bypass)", timeout_probe.state["create_called"] is True)
            check(
                "10: with_options received the exact production timeout/retry contract",
                timeout_probe.state["with_options_kwargs"] == {"timeout": 20, "max_retries": 0},
            )
            record = FreeDailyQuestion.query.filter_by(user_id=uid).first()
            check(
                "10: OpenAI timeout -- free quota compensated (record absent or not marked used today)",
                record is None or record.last_used_date != date.today().strftime("%Y-%m-%d"),
            )

            uid2 = USER_IDS[10]
            other_failure_probe = _SeamProbeOpenAIClient(_other_failure_create)
            chat_engine_module.client = other_failure_probe
            try:
                resp2 = client.post(
                    "/api/chat/free",
                    json={"question": "Will OpenAI fail non-timeout?", "birth": BIRTH},
                    headers=_auth_headers(uid2),
                )
            finally:
                chat_engine_module.client = original_client

            check("10: non-timeout OpenAI failure still delivers a successful fallback answer (200)", resp2.status_code == 200)
            check(
                "10: non-timeout OpenAI failure -- fallback text present",
                "temporarily unavailable" in resp2.get_json().get("answer", {}).get("answer", ""),
            )
            check("10: the monkeypatched fake was actually reached for the non-timeout case too", other_failure_probe.state["create_called"] is True)
            record2 = FreeDailyQuestion.query.filter_by(user_id=uid2).first()
            check(
                "10: non-timeout OpenAI failure -- free quota WAS consumed (fallback text is a valid delivered answer, unchanged design)",
                record2 is not None and record2.last_used_date == date.today().strftime("%Y-%m-%d"),
            )

            # ==================================================
            print("\n=== 11: OpenAI client test-seam regression proof (chat_engine_module.client) ===")
            # ==================================================
            # Direct, dedicated proof -- independent of the route/credit
            # machinery above -- that:
            #   1. monkeypatching chat_engine_module.client AFTER import
            #      affects the client chat_engine() actually uses,
            #   2. no import-time-cached/pre-scoped client can bypass it,
            #   3. with_options() receives exactly timeout=20, max_retries=0,
            #   4. the fake's own completion response is what chat_engine()
            #      returns/processes,
            #   5. no real OpenAI network call can occur -- the fake never
            #      makes one, and create_called proves OUR fake is what
            #      actually ran.
            def _canned_create(**kwargs):
                class _Msg:
                    content = "[SEAM PROOF] no real OpenAI call was made."
                class _Choice:
                    message = _Msg()
                class _Resp:
                    choices = [_Choice()]
                return _Resp()

            seam_probe = _SeamProbeOpenAIClient(_canned_create)
            chat_engine_module.client = seam_probe
            try:
                result = chat_engine_module.chat_engine(dict(BIRTH), "Seam regression proof question")
            finally:
                chat_engine_module.client = original_client

            check("11: monkeypatch was honored -- fake create() was actually called", seam_probe.state["create_called"] is True)
            check(
                "11: with_options received exactly timeout=20, max_retries=0",
                seam_probe.state["with_options_kwargs"] == {"timeout": 20, "max_retries": 0},
            )
            check(
                "11: chat_engine() returned/processed the fake's own response, not a real one",
                result.get("answer") == "[SEAM PROOF] no real OpenAI call was made.",
            )
            check("11: chat_engine_module.client is restored to the real client afterward", chat_engine_module.client is original_client)

        finally:
            routes_chat_module.chat_engine = original_chat_engine
            cleanup()

    print("\n" + "=" * 50)
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
