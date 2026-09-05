"""
test_asknow_intent_classification.py
--------------------------------------
Ask Now Category Architecture v1 -- proves:
  - modules/models_ask_now_concern_category.py / modules/services/
    asknow_category_service.py (small, controlled, DB-backed concern-
    category master; seeded with 13 initial categories; unique names;
    list/add/enable-disable service functions for a future Admin
    Dashboard)
  - modules/services/chat_engine.py sources ACTIVE category names from
    that master at generation time (never a hardcoded taxonomy, never
    model-invented categories), in the SAME single OpenAI call as the
    answer; a category-master read failure degrades to a safe ["Other"]
    fallback and never fails a valid answer; an inactive/added category
    takes effect with NO chat_engine.py code change
  - modules/models_ask_now_intent_history.py / modules/services/
    asknow_intent_service.py (question-level intent history, failure-
    isolated write path) -- unchanged architecture, still records the
    validated canonical category
  - routes/routes_chat.py -- concern_category still stripped before the
    Flutter-facing response; existing free/pack credit contract, timeout
    behavior, and third-party/future-window/answer-style prompt
    contracts from the prior Ask Now Improvement Batch are all preserved

LOCAL ONLY. No real OpenAI call is ever made -- modules.services.
chat_engine's module-level `client` is monkeypatched with a fake, same
technique test_chat_engine_temporal_grounding.py / test_trust_foundation_
phase0.py already established. Kundali/transit generation is real (not
mocked), matching test_trust_foundation_phase0.py's own convention for
route-level tests.
"""

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.models_free_daily import FreeDailyQuestion  # noqa: E402
from modules.models_ask_now_intent_history import AskNowIntentHistory  # noqa: E402
from modules.models_ask_now_concern_category import AskNowConcernCategory  # noqa: E402

import modules.services.chat_engine as chat_engine_module  # noqa: E402
from modules.services.chat_engine import (  # noqa: E402
    chat_engine,
    _parse_answer_and_category,
    _get_active_concern_categories,
)
import modules.services.asknow_category_service as asknow_category_service  # noqa: E402
from modules.services.asknow_category_service import (  # noqa: E402
    get_active_category_names,
    list_categories,
    add_category,
    set_category_active,
)
import modules.services.asknow_intent_service as asknow_intent_service  # noqa: E402
from modules.services.asknow_intent_service import record_intent_history  # noqa: E402
from openai import APITimeoutError  # noqa: E402
import httpx  # noqa: E402


def _fake_timeout_error():
    # Matches the exact construction test_asknow_credit_safety.py / test_
    # asknow_activity_events.py already use for this same exception.
    return APITimeoutError(httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))


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


A_UID = 988001
B_UID = 988002
BIRTH = {"name": "Test", "dob": "1990-01-01", "tob": "10:00", "pob": "Delhi",
         "lat": 28.6, "lng": 77.2, "timezone": "+05:30"}

# The 13 categories seeded by migrations/versions/
# 0e2036a0b4b7_add_ask_now_concern_category_master.py -- Ask Now Category
# Architecture v1's FINAL PRODUCT DECISION (not the earlier 36-item
# granular taxonomy, not model-invented categories).
EXPECTED_INITIAL_CATEGORIES = [
    "Love & Relationship",
    "Breakup",
    "Marriage / Marriage Delay",
    "Marital Conflict / Divorce",
    "Job & Career",
    "Business",
    "Money / Debt",
    "Property",
    "Childbirth / Children",
    "Health & Mental Wellbeing",
    "Education / Foreign Career & Settlement",
    "Spiritual / Dosh / Remedies",
    "Other",
]

TEST_TEMP_CATEGORY = "Test Temp Category ZZZ (asknow intent test)"


def cleanup():
    AskNowIntentHistory.query.filter(AskNowIntentHistory.user_id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    ChatPack.query.filter(ChatPack.user_id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    FreeDailyQuestion.query.filter(FreeDailyQuestion.user_id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    User.query.filter(User.id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    # Test-only category created by section D below -- never leave it in
    # the real master.
    AskNowConcernCategory.query.filter_by(name=TEST_TEMP_CATEGORY).delete(synchronize_session=False)
    # Safety net: if a test aborted mid-way while a real seeded category
    # was toggled inactive (section C), restore every one of the 13
    # initial categories to active -- this suite must never leave the
    # real master in a different state than it found it.
    AskNowConcernCategory.query.filter(
        AskNowConcernCategory.name.in_(EXPECTED_INITIAL_CATEGORIES)
    ).update({"is_active": True}, synchronize_session=False)
    db.session.commit()


# ---------------------------------------------------------------------
# Fake OpenAI client family. Each records call count on a shared dict so
# "exactly one OpenAI call" can be proven at both the chat_engine() layer
# and the full route layer.
# ---------------------------------------------------------------------
class _FakeCompletionResponse:
    def __init__(self, text):
        self.choices = [type("Choice", (), {
            "message": type("Message", (), {"content": text})()
        })()]


class _FakeCompletions:
    def __init__(self, captured, response_text, raise_exc=None):
        self._captured = captured
        self._response_text = response_text
        self._raise_exc = raise_exc

    def create(self, **kwargs):
        self._captured["call_count"] = self._captured.get("call_count", 0) + 1
        self._captured["kwargs"] = kwargs
        self._captured["prompt"] = kwargs["messages"][1]["content"]
        if self._raise_exc is not None:
            raise self._raise_exc
        return _FakeCompletionResponse(self._response_text)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, captured, response_text="", raise_exc=None):
        self.chat = _FakeChat(_FakeCompletions(captured, response_text, raise_exc))

    def with_options(self, **kwargs):
        return self


def _run_chat_engine_with_fake(response_text=None, raise_exc=None, question="Will I get married soon?"):
    captured = {}
    original_client = chat_engine_module.client
    chat_engine_module.client = _FakeOpenAIClient(captured, response_text or "", raise_exc)
    try:
        result = chat_engine(BIRTH, question)
    finally:
        chat_engine_module.client = original_client
    return result, captured


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        db.session.add(User(id=A_UID, email="asknow-intent-a@example.com", provider="password"))
        db.session.add(User(id=B_UID, email="asknow-intent-b@example.com", provider="password"))
        db.session.commit()

        client = app.test_client()
        token_a = create_access_token(identity=str(A_UID))
        headers_a = {"Authorization": f"Bearer {token_a}", "Content-Type": "application/json"}

        try:
            # ==========================================================
            print("=== A: Category master -- initial seed, uniqueness ===")
            # ==========================================================
            all_rows = list_categories(include_inactive=True)
            all_names = {r["name"] for r in all_rows}
            check("A1: at least the 13 initial categories exist in the master",
                  set(EXPECTED_INITIAL_CATEGORIES) <= all_names)
            check("A2: every initial category is active by default",
                  all(r["is_active"] for r in all_rows if r["name"] in EXPECTED_INITIAL_CATEGORIES))
            check("A3: 'Other' is present and is a valid fallback category",
                  "Other" in all_names)

            active_names = get_active_category_names()
            check("A4: get_active_category_names() returns all 13 initial categories active",
                  set(EXPECTED_INITIAL_CATEGORIES) <= set(active_names))

            try:
                add_category("Other")
                duplicate_raised = False
            except ValueError:
                duplicate_raised = True
            check("A5: category names must remain unique -- add_category() rejects a duplicate name",
                  duplicate_raised)

            duplicate_row = AskNowConcernCategory(name="Other", is_active=True)
            db.session.add(duplicate_row)
            db_level_raised = False
            try:
                db.session.commit()
            except Exception:
                db_level_raised = True
                db.session.rollback()
            check("A6: uniqueness is ALSO enforced at the DB constraint level, not just in the service layer",
                  db_level_raised)

            # ==========================================================
            print("\n=== B: category master service layer (future Admin Dashboard) ===")
            # ==========================================================
            new_row = add_category(TEST_TEMP_CATEGORY)
            check("B1: add_category() creates a new active category", new_row.is_active is True)
            check("B2: newly added category appears in list_categories()",
                  TEST_TEMP_CATEGORY in {r["name"] for r in list_categories()})

            set_category_active(TEST_TEMP_CATEGORY, False)
            check("B3: set_category_active(False) disables the category",
                  TEST_TEMP_CATEGORY not in get_active_category_names())

            set_category_active(TEST_TEMP_CATEGORY, True)
            check("B4: set_category_active(True) re-enables the category",
                  TEST_TEMP_CATEGORY in get_active_category_names())

            try:
                set_category_active("Category That Does Not Exist At All", True)
                nonexistent_raised = False
            except ValueError:
                nonexistent_raised = True
            check("B5: set_category_active() on a nonexistent category raises, never silently creates one",
                  nonexistent_raised)

            # Clean up the temp category from this section immediately --
            # later sections assume the master is back to exactly the 13
            # initial categories.
            AskNowConcernCategory.query.filter_by(name=TEST_TEMP_CATEGORY).delete(synchronize_session=False)
            db.session.commit()

            # ==========================================================
            print("\n=== C: chat_engine() sources ACTIVE categories from the master (no hardcoding) ===")
            # ==========================================================
            result_c1, captured_c1 = _run_chat_engine_with_fake(
                response_text=json.dumps({"answer": "x", "concern_category": "Job & Career"}),
                question="Will my career improve?",
            )
            prompt_c1 = captured_c1["prompt"]
            check("C1: every currently active category name is supplied to the prompt",
                  all(name in prompt_c1 for name in get_active_category_names()))
            check("C2: prompt's rendered list matches _get_active_concern_categories() for THIS call exactly",
                  ", ".join(_get_active_concern_categories()) in prompt_c1)

            # Disable one real seeded category and prove it disappears
            # from the very next prompt -- restored in the finally below
            # regardless of outcome.
            set_category_active("Spiritual / Dosh / Remedies", False)
            try:
                result_c2, captured_c2 = _run_chat_engine_with_fake(
                    response_text=json.dumps({"answer": "x", "concern_category": "Other"}),
                    question="Will my career improve?",
                )
                prompt_c2 = captured_c2["prompt"]
                check("C3: a disabled category is NOT supplied to the prompt",
                      "Spiritual / Dosh / Remedies" not in prompt_c2)
                check("C4: the other 12 categories are still supplied",
                      all(name in prompt_c2 for name in EXPECTED_INITIAL_CATEGORIES
                          if name != "Spiritual / Dosh / Remedies"))

                # If the model still mistakenly returns the now-disabled
                # category, the validator must reject it (it's not in the
                # active set for THIS call).
                _, rejected_cat = _parse_answer_and_category(
                    json.dumps({"answer": "x", "concern_category": "Spiritual / Dosh / Remedies"}),
                    _get_active_concern_categories(),
                )
                check("C5: a just-disabled category is rejected by the validator for this call",
                      rejected_cat is None)
            finally:
                set_category_active("Spiritual / Dosh / Remedies", True)
            check("C6: the disabled category is supplied again once re-enabled",
                  "Spiritual / Dosh / Remedies" in get_active_category_names())

            # Add a brand-new category through the service layer only --
            # NO chat_engine.py code change -- and prove it is offered on
            # the very next call.
            add_category(TEST_TEMP_CATEGORY)
            try:
                result_c3, captured_c3 = _run_chat_engine_with_fake(
                    response_text=json.dumps({"answer": "x", "concern_category": TEST_TEMP_CATEGORY}),
                    question="Some new kind of question.",
                )
                check("C7: a newly added category becomes available with NO chat_engine.py modification",
                      TEST_TEMP_CATEGORY in captured_c3["prompt"])
                check("C8: chat_engine() accepts/returns the newly added category as valid",
                      result_c3["concern_category"] == TEST_TEMP_CATEGORY)
            finally:
                AskNowConcernCategory.query.filter_by(name=TEST_TEMP_CATEGORY).delete(synchronize_session=False)
                db.session.commit()

            # ==========================================================
            print("\n=== D: category-master DB-read failure -- safe ['Other'] fallback, answer never fails ===")
            # ==========================================================
            def _boom_get_active_category_names():
                raise RuntimeError("simulated category master DB failure")

            original_get_active = chat_engine_module.get_active_category_names
            chat_engine_module.get_active_category_names = _boom_get_active_category_names
            try:
                fallback_categories = _get_active_concern_categories()
                check("D1: DB-read failure degrades to the ['Other']-only safety net, never raises",
                      fallback_categories == ["Other"])

                result_d, captured_d = _run_chat_engine_with_fake(
                    response_text=json.dumps({"answer": "Still a valid answer despite the DB outage.", "concern_category": "Other"}),
                )
                check("D2: a valid, usable answer is still returned when the category master is unreachable",
                      result_d["answer"] == "Still a valid answer despite the DB outage.")
                check("D3: 'Other' still validates correctly under the fallback",
                      result_d["concern_category"] == "Other")
                check("D4: exactly one OpenAI call even during the DB outage", captured_d.get("call_count") == 1)
                # "Breakup" is deliberately excluded from this negative
                # check -- it always appears in the prompt's fixed
                # classification-example sentence (see Section J below),
                # regardless of what the active category list is, so its
                # presence here proves nothing either way.
                other_real_categories = [
                    name for name in EXPECTED_INITIAL_CATEGORIES if name not in ("Other", "Breakup")
                ]
                check("D5: only 'Other' was offered to the model during the outage (none of the other 11 real categories)",
                      "Other" in captured_d["prompt"]
                      and not any(name in captured_d["prompt"] for name in other_real_categories))

                # A category the model might still (wrongly) invent while
                # the master is unreachable must be safely rejected.
                result_d2, _ = _run_chat_engine_with_fake(
                    response_text=json.dumps({"answer": "Another valid answer.", "concern_category": "Job & Career"}),
                )
                check("D6: a category outside the ['Other']-only fallback is safely rejected (None), answer still returned",
                      result_d2["concern_category"] is None and result_d2["answer"] == "Another valid answer.")
            finally:
                chat_engine_module.get_active_category_names = original_get_active

            check("D7: normal DB-backed behavior resumes once the outage ends",
                  set(EXPECTED_INITIAL_CATEGORIES) <= set(_get_active_concern_categories()))

            # ==========================================================
            print("\n=== E: _parse_answer_and_category() -- pure unit tests, dynamic valid_categories ===")
            # ==========================================================
            valid = ["Breakup", "Other"]
            ans, cat = _parse_answer_and_category(
                json.dumps({"answer": "You will find stability by 2027.", "concern_category": "Breakup"}), valid,
            )
            check("E1: valid JSON -> answer extracted", ans == "You will find stability by 2027.")
            check("E1: valid JSON -> valid category extracted", cat == "Breakup")

            ans2, cat2 = _parse_answer_and_category(
                json.dumps({"answer": "Some answer.", "concern_category": "Not A Real Category"}), valid,
            )
            check("E2: invalid/unknown category falls back to None", cat2 is None)
            check("E2: answer is still usable despite invalid category", ans2 == "Some answer.")

            ans3, cat3 = _parse_answer_and_category("This is plain text, not JSON at all.", valid)
            check("E3: malformed/non-JSON response -> raw text becomes the answer",
                  ans3 == "This is plain text, not JSON at all.")
            check("E3: malformed/non-JSON response -> category is None", cat3 is None)

            ans4, cat4 = _parse_answer_and_category(json.dumps({"concern_category": "Breakup"}), valid)
            check("E4: JSON missing 'answer' key -> degrades gracefully, never raises",
                  ans4 == json.dumps({"concern_category": "Breakup"}))
            check("E4: JSON missing 'answer' key -> category is None (nothing trustworthy to keep)", cat4 is None)

            ans5, cat5 = _parse_answer_and_category(json.dumps({"answer": "   ", "concern_category": "Breakup"}), valid)
            check("E5: empty/whitespace-only answer treated as missing, degrades gracefully", cat5 is None)

            ans6, cat6 = _parse_answer_and_category(json.dumps(["not", "an", "object"]), valid)
            check("E6: JSON array (not an object) -> degrades gracefully, never raises", cat6 is None)

            check("E7: every category in a given valid list round-trips correctly",
                  all(_parse_answer_and_category(json.dumps({"answer": "x", "concern_category": c}), valid)[1] == c
                      for c in valid))

            # ==========================================================
            print("\n=== F: chat_engine() -- one call, valid JSON in/out ===")
            # ==========================================================
            result_f, captured_f = _run_chat_engine_with_fake(
                response_text=json.dumps({
                    "answer": "Career growth is favorable through 2027.",
                    "concern_category": "Job & Career",
                }),
                question="Will my career improve?",
            )
            check("F1: exactly one OpenAI call for one chat_engine() invocation",
                  captured_f.get("call_count") == 1)
            check("F2: response_format=json_object sent on the SAME call",
                  captured_f["kwargs"].get("response_format") == {"type": "json_object"})
            check("F3: model unchanged (gpt-5.6-luna)", captured_f["kwargs"].get("model") == "gpt-5.6-luna")
            check("F4: answer extracted correctly", result_f["answer"] == "Career growth is favorable through 2027.")
            check("F5: concern_category extracted correctly", result_f["concern_category"] == "Job & Career")
            check("F6: internal return dict still carries every pre-existing key",
                  {"answer", "kundali_preview", "dasha_preview", "transit_preview", "disclaimer"} <= set(result_f.keys()))

            # ==========================================================
            print("\n=== G: chat_engine() -- non-JSON model output degrades gracefully (safe fallback) ===")
            # ==========================================================
            result_g, captured_g = _run_chat_engine_with_fake(
                response_text="Plain text answer, model ignored the JSON instruction.",
            )
            check("G1: still exactly one OpenAI call", captured_g.get("call_count") == 1)
            check("G2: raw text becomes the answer (never fails the transaction)",
                  result_g["answer"] == "Plain text answer, model ignored the JSON instruction.")
            check("G3: concern_category is None, not fabricated", result_g["concern_category"] is None)

            result_g2, _ = _run_chat_engine_with_fake(
                response_text=json.dumps({"answer": "A real answer.", "concern_category": "Something Made Up"}),
            )
            check("G4: an invalid/model-invented category safely falls back to None, answer still returned",
                  result_g2["concern_category"] is None and result_g2["answer"] == "A real answer.")

            # ==========================================================
            print("\n=== H: chat_engine() -- APITimeoutError still re-raises (unchanged) ===")
            # ==========================================================
            raised = False
            try:
                _run_chat_engine_with_fake(raise_exc=_fake_timeout_error())
            except APITimeoutError:
                raised = True
            check("H1: APITimeoutError still propagates out of chat_engine() unchanged", raised)

            # ==========================================================
            print("\n=== I: prompt contract -- third-party guard / future-window guard / answer style (preserved) ===")
            # ==========================================================
            _, captured_i = _run_chat_engine_with_fake(
                response_text=json.dumps({"answer": "x", "concern_category": "Breakup"}),
                question="My girlfriend (DOB 1992-05-01, time 10:00, place Mumbai) broke up with me -- will we get back together?",
            )
            prompt_i = captured_i["prompt"]
            check("I1: third-party section present", "THIRD-PARTY / OTHER PERSON'S DETAILS" in prompt_i)
            check("I2: forbids calculating another person's kundali",
                  "Do not calculate, infer, or claim to calculate that other person's Kundali" in prompt_i)
            check("I3: forbids requesting missing partner details",
                  "Do not ask the user to provide or complete that other person's birth details" in prompt_i)
            check("I4: forbids compatibility/synastry",
                  "Do not perform compatibility, matching, or synastry analysis" in prompt_i)
            check("I5: future/current window must not have already ended",
                  "must NOT have already fully ended before CURRENT_DATE" in prompt_i)
            check("I6: fully-ended periods may only be used retrospectively",
                  "may only be referenced retrospectively/explanatorily" in prompt_i)
            check("I7: direct-answer-first rule present",
                  "Answer the user's actual question directly first" in prompt_i)
            check("I8: no raw jargon dump rule present",
                  "Do not dump raw planetary/house jargon" in prompt_i)
            check("I9: single context-specific follow-up rule present (never generic)",
                  "exactly ONE follow-up direction" in prompt_i and "never a generic" in prompt_i)
            check("I10: RESPONSE FORMAT section present", "RESPONSE FORMAT (REQUIRED)" in prompt_i)
            check("I11: classification-by-underlying-concern principle present",
                  "NEVER the outcome or resolution they are hoping for" in prompt_i)

            # ==========================================================
            print("\n=== J: REQUIRED -- breakup/patch-up example classifies as 'Breakup' ===")
            # ==========================================================
            check("J1: 'Breakup' is a real active category (never removed by this correction)",
                  "Breakup" in get_active_category_names())
            check("J2: 'Patch-up/Reconciliation' (the outcome) is NOT a category anywhere in the master",
                  "Patch-up/Reconciliation" not in {r["name"] for r in list_categories()})

            result_j, captured_j = _run_chat_engine_with_fake(
                response_text=json.dumps({"answer": "Guidance on moving forward.", "concern_category": "Breakup"}),
                question="Meri girlfriend ne breakup kar liya hai, kya patch-up hoga?",
            )
            check("J3: exactly one OpenAI call for the canonical example",
                  captured_j.get("call_count") == 1)
            check("J4: chat_engine() classifies the canonical example as 'Breakup'",
                  result_j["concern_category"] == "Breakup")
            check("J5: prompt's classification principle explicitly walks through this exact example",
                  "patch-up hoga" in captured_j["prompt"] and 'classify it as "Breakup"' in captured_j["prompt"])

            # ==========================================================
            print("\n=== K: /api/chat/free route -- concern_category hidden, history written, credit unchanged ===")
            # ==========================================================
            chat_engine_module.client = _FakeOpenAIClient(
                {}, json.dumps({"answer": "Focus on steady progress this month.", "concern_category": "Job & Career"})
            )
            resp = client.post("/api/chat/free", json={"question": "How is my career this month?", "birth": BIRTH}, headers=headers_a)
            check("K1: free question succeeds (200)", resp.status_code == 200)
            body = resp.get_json()
            check("K2: concern_category is NOT present in the client-facing answer object",
                  "concern_category" not in (body.get("answer") or {}))
            check("K3: answer text still reaches the client",
                  body.get("answer", {}).get("answer") == "Focus on steady progress this month.")

            history_rows = AskNowIntentHistory.query.filter_by(user_id=A_UID, source="free").all()
            check("K4: exactly one intent history row written for this successful question",
                  len(history_rows) == 1)
            check("K5: history row carries the correct validated canonical category",
                  history_rows and history_rows[0].concern_category == "Job & Career")
            check("K6: history row does NOT store the raw question or answer text",
                  not hasattr(AskNowIntentHistory, "question") and not hasattr(AskNowIntentHistory, "answer"))

            rec = FreeDailyQuestion.query.filter_by(user_id=A_UID).first()
            check("K7: free quota consumed exactly once (existing 1/day contract unchanged)",
                  rec is not None and rec.used_today())

            resp2 = client.post("/api/chat/free", json={"question": "Another one today?", "birth": BIRTH}, headers=headers_a)
            check("K8: a second free question the same day is still blocked (403) -- unchanged contract",
                  resp2.status_code == 403)
            check("K9: no second history row was created for the blocked attempt",
                  AskNowIntentHistory.query.filter_by(user_id=A_UID, source="free").count() == 1)

            # ==========================================================
            print("\n=== L: /api/chat/pack route -- concern_category hidden, history written, credit unchanged ===")
            # ==========================================================
            pack = ChatPack(user_id=A_UID, amount=100, questions_total=10, questions_used=0, status="success")
            db.session.add(pack)
            db.session.commit()

            chat_engine_module.client = _FakeOpenAIClient(
                {}, json.dumps({"answer": "Marriage timing looks supported in late 2027.", "concern_category": "Marriage / Marriage Delay"})
            )
            resp3 = client.post("/api/chat/pack", json={"question": "When will I get married?", "birth": BIRTH}, headers=headers_a)
            check("L1: pack question succeeds (200)", resp3.status_code == 200)
            body3 = resp3.get_json()
            check("L2: concern_category is NOT present in the client-facing answer object",
                  "concern_category" not in (body3.get("answer") or {}))
            check("L3: remaining reflects real deduction (10-1=9) -- unchanged pack contract",
                  body3.get("remaining") == 9)

            db.session.refresh(pack)
            check("L4: pack.questions_used incremented by exactly 1", pack.questions_used == 1)

            history_rows_pack = AskNowIntentHistory.query.filter_by(user_id=A_UID, source="pack").all()
            check("L5: exactly one intent history row written for the pack question",
                  len(history_rows_pack) == 1)
            check("L6: pack history row carries the correct canonical category",
                  history_rows_pack and history_rows_pack[0].concern_category == "Marriage / Marriage Delay")

            # ==========================================================
            print("\n=== M: generation failure -- credit restoration unchanged, no history row ===")
            # ==========================================================
            used_before = pack.questions_used
            chat_engine_module.client = _FakeOpenAIClient({}, "", raise_exc=_fake_timeout_error())
            resp4 = client.post("/api/chat/pack", json={"question": "Will this fail?", "birth": BIRTH}, headers=headers_a)
            check("M1: generation failure returns 502, not a fabricated success", resp4.status_code == 502)
            db.session.refresh(pack)
            check("M2: pack question count restored (unchanged Credit Safety behavior)",
                  pack.questions_used == used_before)
            check("M3: no intent history row created for a failed generation",
                  AskNowIntentHistory.query.filter_by(user_id=A_UID, source="pack").count() == 1)

            # ==========================================================
            print("\n=== N: intent history persistence failure never fails a valid answer ===")
            # ==========================================================
            class _BoomModel:
                def __init__(self, **kwargs):
                    raise RuntimeError("simulated DB failure while writing intent history")

            original_model = asknow_intent_service.AskNowIntentHistory
            asknow_intent_service.AskNowIntentHistory = _BoomModel
            used_before_n = pack.questions_used
            try:
                chat_engine_module.client = _FakeOpenAIClient(
                    {}, json.dumps({"answer": "Still a valid, usable answer.", "concern_category": "Money / Debt"})
                )
                resp5 = client.post("/api/chat/pack", json={"question": "Will I be financially stable?", "birth": BIRTH}, headers=headers_a)
            finally:
                asknow_intent_service.AskNowIntentHistory = original_model

            check("N1: a valid, usable answer is still returned even though history persistence failed (200)",
                  resp5.status_code == 200)
            body5 = resp5.get_json()
            check("N2: the real generated answer still reaches the client",
                  body5.get("answer", {}).get("answer") == "Still a valid, usable answer.")
            db.session.refresh(pack)
            check("N3: credit was consumed normally (generation succeeded) -- not incorrectly restored",
                  pack.questions_used == used_before_n + 1)

            asknow_intent_service.AskNowIntentHistory = _BoomModel
            try:
                direct_result = record_intent_history(user_id=A_UID, concern_category="Money / Debt", source="pack")
                direct_raised = False
            except Exception:
                direct_result = None
                direct_raised = True
            finally:
                asknow_intent_service.AskNowIntentHistory = original_model
            check("N4: record_intent_history() never raises when the DB write fails", not direct_raised)
            check("N5: record_intent_history() reports the failure via its return value (False)",
                  direct_result is False)

            print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
        finally:
            cleanup()

    return failed == 0


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
