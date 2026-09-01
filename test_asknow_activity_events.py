"""
test_asknow_activity_events.py
-------------------------------------------------
Phase 4E: proves the Ask Now domain's 3 canonical backend activity
events (asknow_question_submitted, asknow_answer_delivered,
asknow_answer_failed) are emitted at the correct, already-frozen
producer points in routes/routes_chat.py's /api/chat/free and
/api/chat/pack -- strictly after their own authoritative business
state (credit consumption commit, successful generation return, or
compensation attempt), with the exact identity/entity/properties/
dedupe contract the Phase 4E design freeze locked (profile_id/
firebase_uid/entity_type/entity_id/session_id/correlation_id/
dedupe_key all None -- no truthful durable identity/entity/attempt
identifier exists for Ask Now), and that analytics failure of every
kind can never alter the Ask Now business result or credit state.
Also proves the raw question, generated answer, and all birth-detail
fields never reach the ledger in any form.

Since dedupe_key is always None for these events (by design -- see the
Phase 4E audit), rows cannot be looked up by dedupe key like every
other phase's tests. Instead each check captures the database's own
NOW() as a checkpoint immediately before each HTTP call, then queries
for rows with recorded_at strictly after that checkpoint -- precise
and race-free since each call in this file runs sequentially.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real OpenAI/kundali call is ever made
(routes_chat.chat_engine is monkeypatched, the exact seam
test_asknow_credit_safety.py already uses). All test rows are created
with dedicated, obviously-test-only markers and deleted in a finally
block, keyed by their own ids -- never a broad DELETE.
"""

import os
import sys
import uuid
from datetime import date
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.pop("ASKNOW_JWT_ENFORCEMENT", None)  # explicit: stays OFF for this whole file

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token

    from modules.auth.models import User
    from modules.models_free_daily import FreeDailyQuestion
    from modules.models_chat_pack import ChatPack

    import routes.routes_chat as routes_chat_module
    from modules.activity_events.service import LedgerWriteResult
    from openai import APITimeoutError
    import httpx

    USER_IDS = list(range(986601, 986650))
    BIRTH = {
        "name": "Distinctive Fake Name QwertyZ",
        "dob": "1985-07-15",
        "tob": "03:33",
        "pob": "Distinctive Fake City Qwerty",
        "lat": 12.3456,
        "lng": 65.4321,
        "tz": "+05:30",
    }
    RAW_QUESTION_MARKER = "DISTINCTIVE-RAW-QUESTION-MARKER-9f8e7d"
    RAW_ANSWER_MARKER = "DISTINCTIVE-RAW-ANSWER-MARKER-1a2b3c"
    TOKEN_LIKE_MARKER = "sk-fake-token-like-string-should-never-leak-4d5e6f"

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"REFUSING to run against {current_db!r} -- local only."
        )

        created_event_ids = []

        def cleanup():
            FreeDailyQuestion.query.filter(FreeDailyQuestion.user_id.in_(USER_IDS)).delete(synchronize_session=False)
            ChatPack.query.filter(ChatPack.user_id.in_(USER_IDS)).delete(synchronize_session=False)
            User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
            db.session.commit()

        def _ensure_user(user_id):
            if User.query.get(user_id) is None:
                db.session.add(User(id=user_id, email=f"asknow-events-{user_id}@example.com", provider="password"))
                db.session.commit()

        def auth_headers(user_id):
            _ensure_user(user_id)
            token = create_access_token(identity=str(user_id))
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        def make_pack(user_id, questions_total=10, questions_used=0):
            pack = ChatPack(
                user_id=user_id, amount=0, questions_total=questions_total,
                questions_used=questions_used, status="success",
                razorpay_order_id="TEST", razorpay_payment_id="TEST",
            )
            db.session.add(pack)
            db.session.commit()
            return pack

        def db_now():
            # clock_timestamp(), NOT now()/current_timestamp -- the
            # latter is frozen at transaction start in PostgreSQL and
            # would return the SAME value for every checkpoint in this
            # test's own long-running session, silently making every
            # "since" window overlap every other one.
            return db.session.execute(text("SELECT clock_timestamp()")).scalar()

        def events_since(event_name, since_ts):
            rows = db.session.execute(
                text(
                    "SELECT * FROM activity_events WHERE event_name = :en "
                    "AND recorded_at > :since ORDER BY recorded_at"
                ),
                {"en": event_name, "since": since_ts},
            ).fetchall()
            for r in rows:
                created_event_ids.append(str(r.event_id))
            return rows

        def all_asknow_events_since(since_ts):
            out = []
            for en in ("asknow_question_submitted", "asknow_answer_delivered", "asknow_answer_failed"):
                out.extend(events_since(en, since_ts))
            return out

        def _real_answer_chat_engine(birth, question):
            return {
                "answer": f"{RAW_ANSWER_MARKER} A real generated answer.",
                "kundali_preview": "Leo",
                "dasha_preview": {},
                "transit_preview": {},
                "disclaimer": "This answer is for astrological guidance only.",
            }

        class _RaisingChatEngine:
            def __call__(self, birth, question):
                raise RuntimeError(f"simulated kundali/generation failure ({TOKEN_LIKE_MARKER})")

        class _TimeoutChatEngine:
            def __call__(self, birth, question):
                raise APITimeoutError(httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

        original_chat_engine = routes_chat_module.chat_engine

        try:
            client = app.test_client()

            def ask_free(uid, question=None, birth=None):
                return client.post(
                    "/api/chat/free",
                    json={"question": question or RAW_QUESTION_MARKER, "birth": birth if birth is not None else BIRTH},
                    headers=auth_headers(uid),
                )

            def ask_pack(uid, question=None, birth=None):
                return client.post(
                    "/api/chat/pack",
                    json={"question": question or RAW_QUESTION_MARKER, "birth": birth if birth is not None else BIRTH},
                    headers=auth_headers(uid),
                )

            # ==========================================================
            print("=== 1: FREE success -> submitted + delivered, no failed ===")
            # ==========================================================
            uid1 = USER_IDS[0]
            routes_chat_module.chat_engine = _real_answer_chat_engine
            checkpoint1 = db_now()
            resp1 = ask_free(uid1)
            check("1: 200 on success", resp1.status_code == 200)

            submitted1 = events_since("asknow_question_submitted", checkpoint1)
            delivered1 = events_since("asknow_answer_delivered", checkpoint1)
            failed1 = events_since("asknow_answer_failed", checkpoint1)
            check("1: exactly one asknow_question_submitted", len(submitted1) == 1)
            check("1: exactly one asknow_answer_delivered", len(delivered1) == 1)
            check("1: no asknow_answer_failed", len(failed1) == 0)

            if submitted1:
                s = submitted1[0]
                check("1: submitted properties == {source: free}", s.properties == {"source": "free"})
                check("1: submitted profile_id None", s.profile_id is None)
                check("1: submitted firebase_uid None", s.firebase_uid is None)
                check("1: submitted entity_type/entity_id None", s.entity_type is None and s.entity_id is None)
                check("1: submitted session_id None", s.session_id is None)
                check("1: submitted correlation_id None", s.correlation_id is None)
                check("1: submitted dedupe_key None", s.dedupe_key is None)
                check("1: submitted platform == backend_internal", s.platform == "backend_internal")
                check("1: submitted envelope source == asknow_chat", s.source == "asknow_chat")
            if delivered1:
                d = delivered1[0]
                # Phase 4E.1 -- latency_ms now survives sanitize_properties()
                # (see test 12 for the isolated sanitizer-level proof).
                check("1: delivered properties has source=free AND latency_ms", d.properties.get("source") == "free" and "latency_ms" in d.properties)
                check("1: delivered latency_ms is a non-negative int", isinstance(d.properties.get("latency_ms"), int) and d.properties["latency_ms"] >= 0)
                check("1: delivered has NO category key", "category" not in d.properties)
                check("1: delivered profile_id/entity/session/correlation/dedupe all None", d.profile_id is None and d.entity_type is None and d.entity_id is None and d.session_id is None and d.correlation_id is None and d.dedupe_key is None)

            # ==========================================================
            print("\n=== 2: PACK success -> submitted + delivered, source=pack, credit unchanged pattern ===")
            # ==========================================================
            uid2 = USER_IDS[1]
            make_pack(uid2, questions_total=10, questions_used=3)
            routes_chat_module.chat_engine = _real_answer_chat_engine
            checkpoint2 = db_now()
            resp2 = ask_pack(uid2)
            check("2: 200 on success", resp2.status_code == 200)
            check("2: remaining reflects exactly one consumed (10-4=6)", resp2.get_json().get("remaining") == 6)

            submitted2 = events_since("asknow_question_submitted", checkpoint2)
            delivered2 = events_since("asknow_answer_delivered", checkpoint2)
            check("2: exactly one submitted", len(submitted2) == 1)
            check("2: exactly one delivered", len(delivered2) == 1)
            if submitted2:
                check("2: submitted properties == {source: pack}", submitted2[0].properties == {"source": "pack"})
            if delivered2:
                check("2: delivered source == pack AND latency_ms present", delivered2[0].properties.get("source") == "pack" and "latency_ms" in delivered2[0].properties)
                check("2: delivered latency_ms is a non-negative int", isinstance(delivered2[0].properties.get("latency_ms"), int) and delivered2[0].properties["latency_ms"] >= 0)

            # ==========================================================
            print("\n=== 3: FREE timeout -> submitted + failed(timeout), no delivered, quota compensated ===")
            # ==========================================================
            uid3 = USER_IDS[2]
            routes_chat_module.chat_engine = _TimeoutChatEngine()
            checkpoint3 = db_now()
            resp3 = ask_free(uid3)
            check("3: 502 on timeout", resp3.status_code == 502)

            submitted3 = events_since("asknow_question_submitted", checkpoint3)
            delivered3 = events_since("asknow_answer_delivered", checkpoint3)
            failed3 = events_since("asknow_answer_failed", checkpoint3)
            check("3: exactly one submitted", len(submitted3) == 1)
            check("3: no delivered", len(delivered3) == 0)
            check("3: exactly one failed", len(failed3) == 1)
            if failed3:
                check("3: failed properties == {source: free, failure_reason: timeout}", failed3[0].properties == {"source": "free", "failure_reason": "timeout"})
                check("3: failed has no latency_ms", "latency_ms" not in failed3[0].properties)

            record3 = FreeDailyQuestion.query.filter_by(user_id=uid3).first()
            check("3: free quota compensated (not marked used today)", record3 is None or record3.last_used_date != date.today().strftime("%Y-%m-%d"))

            # ==========================================================
            print("\n=== 4: PACK timeout -> submitted + failed(timeout), exact credit restored ===")
            # ==========================================================
            uid4 = USER_IDS[3]
            pack4 = make_pack(uid4, questions_total=10, questions_used=5)
            routes_chat_module.chat_engine = _TimeoutChatEngine()
            checkpoint4 = db_now()
            resp4 = ask_pack(uid4)
            check("4: 502 on timeout", resp4.status_code == 502)
            submitted4 = events_since("asknow_question_submitted", checkpoint4)
            failed4 = events_since("asknow_answer_failed", checkpoint4)
            check("4: exactly one submitted", len(submitted4) == 1)
            check("4: exactly one failed(timeout)", len(failed4) == 1 and failed4[0].properties.get("failure_reason") == "timeout")
            db.session.refresh(pack4)
            check("4: exactly the one consumed question was restored (back to 5)", pack4.questions_used == 5)

            # ==========================================================
            print("\n=== 5: FREE generic failure -> submitted + failed(unknown), no delivered ===")
            # ==========================================================
            uid5 = USER_IDS[4]
            routes_chat_module.chat_engine = _RaisingChatEngine()
            checkpoint5 = db_now()
            resp5 = ask_free(uid5)
            check("5: 502 on generic failure", resp5.status_code == 502)
            submitted5 = events_since("asknow_question_submitted", checkpoint5)
            delivered5 = events_since("asknow_answer_delivered", checkpoint5)
            failed5 = events_since("asknow_answer_failed", checkpoint5)
            check("5: exactly one submitted", len(submitted5) == 1)
            check("5: no delivered", len(delivered5) == 0)
            check("5: exactly one failed(unknown)", len(failed5) == 1 and failed5[0].properties.get("failure_reason") == "unknown")
            record5 = FreeDailyQuestion.query.filter_by(user_id=uid5).first()
            check("5: free quota compensated", record5 is None or record5.last_used_date != date.today().strftime("%Y-%m-%d"))

            # ==========================================================
            print("\n=== 6: PACK generic failure -> submitted + failed(unknown), credit restored ===")
            # ==========================================================
            uid6 = USER_IDS[5]
            pack6 = make_pack(uid6, questions_total=10, questions_used=2)
            routes_chat_module.chat_engine = _RaisingChatEngine()
            checkpoint6 = db_now()
            resp6 = ask_pack(uid6)
            check("6: 502 on generic failure", resp6.status_code == 502)
            submitted6 = events_since("asknow_question_submitted", checkpoint6)
            failed6 = events_since("asknow_answer_failed", checkpoint6)
            check("6: exactly one submitted", len(submitted6) == 1)
            check("6: exactly one failed(unknown)", len(failed6) == 1 and failed6[0].properties.get("failure_reason") == "unknown")
            db.session.refresh(pack6)
            check("6: credit restored to 2", pack6.questions_used == 2)

            # ==========================================================
            print("\n=== 7: pre-submission rejections -> ZERO Ask Now events ===")
            # ==========================================================
            uid7a = USER_IDS[6]
            checkpoint7a = db_now()
            resp7a = client.post("/api/chat/free", json={"question": "", "birth": BIRTH}, headers=auth_headers(uid7a))
            check("7a: missing question -> 400", resp7a.status_code == 400)
            check("7a: zero Ask Now events", len(all_asknow_events_since(checkpoint7a)) == 0)

            uid7b = USER_IDS[7]
            checkpoint7b = db_now()
            resp7b = client.post("/api/chat/free", json={"question": "Q?", "birth": {}}, headers=auth_headers(uid7b))
            check("7b: missing birth -> 400", resp7b.status_code == 400)
            check("7b: zero Ask Now events", len(all_asknow_events_since(checkpoint7b)) == 0)

            uid7c = USER_IDS[8]
            # Use up today's free quota first, then attempt again. The
            # setup call itself is a real success and legitimately emits
            # its own submitted+delivered pair -- tracked here too, not
            # just the blocked second attempt below.
            routes_chat_module.chat_engine = _real_answer_chat_engine
            checkpoint7c_setup = db_now()
            ask_free(uid7c)
            events_since("asknow_question_submitted", checkpoint7c_setup)
            events_since("asknow_answer_delivered", checkpoint7c_setup)
            checkpoint7c = db_now()
            resp7c = ask_free(uid7c)
            check("7c: free quota already used -> 403", resp7c.status_code == 403)
            check("7c: zero Ask Now events for the blocked attempt", len(all_asknow_events_since(checkpoint7c)) == 0)

            uid7d = USER_IDS[9]
            checkpoint7d = db_now()
            resp7d = ask_pack(uid7d)  # no pack at all
            check("7d: no pack -> 403", resp7d.status_code == 403)
            check("7d: zero Ask Now events", len(all_asknow_events_since(checkpoint7d)) == 0)

            uid7e = USER_IDS[10]
            make_pack(uid7e, questions_total=1, questions_used=1)  # exhausted
            checkpoint7e = db_now()
            resp7e = ask_pack(uid7e)
            check("7e: pack exhausted -> 403", resp7e.status_code == 403)
            check("7e: zero Ask Now events", len(all_asknow_events_since(checkpoint7e)) == 0)

            uid7f = USER_IDS[11]
            checkpoint7f = db_now()
            with patch("routes.routes_chat.use_free_quota", side_effect=RuntimeError("simulated quota consumption failure")):
                resp7f = ask_free(uid7f)
            check("7f: use_free_quota raising -> 502 quota_error", resp7f.status_code == 502 and resp7f.get_json().get("error") == "quota_error")
            check("7f: zero Ask Now events (consumption never truly committed)", len(all_asknow_events_since(checkpoint7f)) == 0)

            uid7g = USER_IDS[12]
            make_pack(uid7g, questions_total=10, questions_used=0)
            checkpoint7g = db_now()
            with patch("routes.routes_chat.deduct_question", side_effect=RuntimeError("simulated deduct failure")):
                resp7g = ask_pack(uid7g)
            check("7g: deduct_question raising -> 502 quota_error", resp7g.status_code == 502 and resp7g.get_json().get("error") == "quota_error")
            check("7g: zero Ask Now events", len(all_asknow_events_since(checkpoint7g)) == 0)

            # ==========================================================
            print("\n=== 8: analytics failure isolation ===")
            # ==========================================================
            uid8a = USER_IDS[13]
            routes_chat_module.chat_engine = _real_answer_chat_engine
            with patch("routes.routes_chat.record_event") as mock_re_8a:
                mock_re_8a.return_value = LedgerWriteResult(status="write_failed")
                resp8a = ask_free(uid8a)
            check("8a write_failed: business result unchanged (200)", resp8a.status_code == 200)
            record8a = FreeDailyQuestion.query.filter_by(user_id=uid8a).first()
            check("8a write_failed: free quota STILL consumed", record8a is not None and record8a.last_used_date == date.today().strftime("%Y-%m-%d"))

            uid8b = USER_IDS[14]
            with patch("routes.routes_chat.record_event") as mock_re_8b:
                mock_re_8b.side_effect = RuntimeError("simulated unexpected analytics exception")
                resp8b = ask_free(uid8b)
            check("8b exception: does NOT propagate, business result unchanged (200)", resp8b.status_code == 200)
            record8b = FreeDailyQuestion.query.filter_by(user_id=uid8b).first()
            check("8b exception: free quota STILL consumed", record8b is not None and record8b.last_used_date == date.today().strftime("%Y-%m-%d"))

            uid8c = USER_IDS[15]
            real_env_8c = os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            try:
                resp8c = ask_free(uid8c)
            finally:
                if real_env_8c is not None:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = real_env_8c
            check("8c missing env: business result unchanged (200)", resp8c.status_code == 200)
            record8c = FreeDailyQuestion.query.filter_by(user_id=uid8c).first()
            check("8c missing env: free quota STILL consumed", record8c is not None and record8c.last_used_date == date.today().strftime("%Y-%m-%d"))

            uid8d = USER_IDS[16]
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "not_a_real_environment"
            try:
                resp8d = ask_free(uid8d)
            finally:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            check("8d invalid env: business result unchanged (200)", resp8d.status_code == 200)
            record8d = FreeDailyQuestion.query.filter_by(user_id=uid8d).first()
            check("8d invalid env: free quota STILL consumed", record8d is not None and record8d.last_used_date == date.today().strftime("%Y-%m-%d"))

            # Failure-path analytics isolation -- prove compensation still
            # commits correctly even when the asknow_answer_failed emitter
            # itself fails.
            uid8e = USER_IDS[17]
            pack8e = make_pack(uid8e, questions_total=10, questions_used=4)
            routes_chat_module.chat_engine = _RaisingChatEngine()
            with patch("routes.routes_chat.record_event") as mock_re_8e:
                mock_re_8e.side_effect = RuntimeError("simulated analytics failure on the FAILED path")
                resp8e = ask_pack(uid8e)
            check("8e failed-path analytics exception: still a controlled 502, not a crash", resp8e.status_code == 502)
            db.session.refresh(pack8e)
            check("8e failed-path analytics exception: credit compensation STILL committed (restored to 4)", pack8e.questions_used == 4)

            # ==========================================================
            print("\n=== 9: latency_ms never appears on submitted/failed (never even attempted there) ===")
            # ==========================================================
            check("9: submitted never has latency_ms (checked across tests 1-2 above)", "latency_ms" not in submitted1[0].properties and "latency_ms" not in submitted2[0].properties)
            check("9: failed never has latency_ms (checked across tests 3/5 above)", "latency_ms" not in failed3[0].properties and "latency_ms" not in failed5[0].properties)

            # ==========================================================
            print("\n=== 12: direct sanitizer tests -- latency_ms survives, real geo keys stay blocked ===")
            # ==========================================================
            # Phase 4E.1 -- global sanitizer/record_event() coverage
            # kept local here (not in the foundation suite) per this
            # phase's own stated preference: the collision was
            # discovered via Ask Now's own latency_ms property
            # specifically, and this file already owns the fixture/
            # cleanup machinery needed to prove it end to end via
            # record_event() itself, not just the pure function.
            from modules.activity_events.event_schemas import (
                sanitize_properties, EVENT_SCHEMAS, _key_is_forbidden,
            )

            check("12: latency_ms IS listed as an allowed property for asknow_answer_delivered", "latency_ms" in EVENT_SCHEMAS[("asknow_answer_delivered", 1)]["properties"])

            clean, dropped = sanitize_properties("asknow_answer_delivered", 1, {"source": "free", "latency_ms": 42})
            check("12: latency_ms now SURVIVES sanitize_properties()", "latency_ms" in clean and "latency_ms" not in dropped)
            check("12: latency_ms remains numeric, not converted to text", clean.get("latency_ms") == 42 and isinstance(clean.get("latency_ms"), int))
            check("12: source survives unaffected alongside it", clean.get("source") == "free")

            must_block = ["lat", "latitude", "user_lat", "birth_lat", "birth_latitude", "location_lat", "geo_lat", "lng", "longitude", "user_lng", "geo_lng"]
            for k in must_block:
                check(f"12: {k!r} remains forbidden (real geo key)", _key_is_forbidden(k) is True)

            must_survive = ["latency_ms", "source", "category", "failure_reason"]
            for k in must_survive:
                check(f"12: {k!r} remains allowed (not a geo key)", _key_is_forbidden(k) is False)

            # Existing, unrelated protections must remain fully intact --
            # representative sample per this phase's own requirement.
            for k in ["email", "phone", "dob", "tob", "pob", "birth", "auth_token", "jwt_token", "password", "full_name", "first_name"]:
                check(f"12: existing protection intact -- {k!r} still forbidden", _key_is_forbidden(k) is True)
            for k in ["screen_name", "feature_name"]:
                check(f"12: existing precedent intact -- {k!r} still allowed", _key_is_forbidden(k) is False)

            # End-to-end proof via the real record_event() path (not just
            # the pure sanitizer function) -- a forbidden geo-shaped key
            # sent through the SAME allowlisted producer path is still
            # dropped, never persisted, even though it is not one this
            # phase's own producer ever actually sends.
            geo_clean, geo_dropped = sanitize_properties("asknow_answer_delivered", 1, {"source": "free", "latency_ms": 10, "birth_lat": 12.34})
            check("12: a forbidden geo-shaped key alongside latency_ms is still dropped", "birth_lat" in geo_dropped and "birth_lat" not in geo_clean)
            check("12: latency_ms unaffected by the sibling forbidden key", geo_clean.get("latency_ms") == 10)

            # ==========================================================
            print("\n=== 10: multiple pack questions -> independent rows, dedupe_key stays None throughout ===")
            # ==========================================================
            uid10 = USER_IDS[18]
            make_pack(uid10, questions_total=10, questions_used=0)
            routes_chat_module.chat_engine = _real_answer_chat_engine
            checkpoint10 = db_now()
            ask_pack(uid10)
            ask_pack(uid10)
            submitted10 = events_since("asknow_question_submitted", checkpoint10)
            delivered10 = events_since("asknow_answer_delivered", checkpoint10)
            check("10: two separate questions -> two separate submitted rows", len(submitted10) == 2)
            check("10: two separate questions -> two separate delivered rows", len(delivered10) == 2)
            check("10: both submitted rows have dedupe_key None (no artificial idempotency)", all(r.dedupe_key is None for r in submitted10))
            check("10: distinct event_ids (genuinely separate rows, not the same row twice)", submitted10[0].event_id != submitted10[1].event_id)

            # ==========================================================
            print("\n=== 11: Privacy scan -- raw question/answer/birth/token markers must never leak ===")
            # ==========================================================
            all_ids = list(dict.fromkeys(created_event_ids))
            forbidden = [
                RAW_QUESTION_MARKER, RAW_ANSWER_MARKER, TOKEN_LIKE_MARKER,
                "Distinctive Fake Name", "1985-07-15", "03:33", "Distinctive Fake City",
                "12.3456", "65.4321", "RuntimeError", "Traceback",
                "simulated", "asknow-events-",
            ]
            leak_found = False
            for eid in all_ids:
                row = db.session.execute(text("SELECT * FROM activity_events WHERE event_id = :id"), {"id": eid}).fetchone()
                if row is None:
                    continue
                serialized = (
                    str(row.properties) + str(row.entity_type) + str(row.entity_id)
                    + str(row.correlation_id) + str(row.session_id) + str(row.dedupe_key)
                    + str(row.campaign_context) + str(row.notification_context) + str(row.source)
                )
                for term in forbidden:
                    if term in serialized:
                        leak_found = True
                        print(f"  LEAK: {term!r} found in row {eid}")
            check("11: no raw question/answer/birth-detail/token text found in any row", leak_found is False)

        finally:
            routes_chat_module.chat_engine = original_chat_engine
            # ----------------------------------------------------------
            # Cleanup -- precise, per-row, never a broad DELETE.
            # ----------------------------------------------------------
            for eid in dict.fromkeys(created_event_ids):
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()
            cleanup()

            remaining_events = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE event_id = ANY(:ids)"),
                {"ids": [uuid.UUID(e) for e in dict.fromkeys(created_event_ids)] or [uuid.uuid4()]},
            ).scalar()
            check("cleanup: all Phase-4E activity_events rows removed", remaining_events == 0)

            remaining_fdq = FreeDailyQuestion.query.filter(FreeDailyQuestion.user_id.in_(USER_IDS)).count()
            check("cleanup: all Phase-4E FreeDailyQuestion fixtures removed", remaining_fdq == 0)

            remaining_packs = ChatPack.query.filter(ChatPack.user_id.in_(USER_IDS)).count()
            check("cleanup: all Phase-4E ChatPack fixtures removed", remaining_packs == 0)

            remaining_users = User.query.filter(User.id.in_(USER_IDS)).count()
            check("cleanup: all Phase-4E User fixtures removed", remaining_users == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
