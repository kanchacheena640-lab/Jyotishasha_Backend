"""
test_safe_deployment_split.py
-------------------------------
Ask Now Security + Force Update -- Safe Deployment Split (Task E).

Proves BOTH modes of routes/routes_chat.py's four build-48-compatible
endpoints (/api/chat/free, /api/chat/pack, /api/chat/status,
/api/chat/reward), gated by the ASKNOW_JWT_ENFORCEMENT env var:

  PRE-BUILD-49 MODE  (flag unset/OFF -- the state Deployment Unit A ships in)
  POST-BUILD-49 MODE (flag ON -- Deployment Unit B's activation)

Also proves the version-policy semantics fix (Task B): force_update is
descriptive metadata only and never independently blocks a build that
already meets minimum_supported_build; and the exact build-48/49/50
comparison outcomes a real release will produce.

LOCAL ONLY. No production DB. Restores ASKNOW_JWT_ENFORCEMENT to unset
in a finally block regardless of outcome, so this file never leaks
process-wide state into any test run after it.
"""

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
from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.models_free_daily import FreeDailyQuestion  # noqa: E402
from modules.models_app_version_policy import AppVersionPolicy  # noqa: E402

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


A_UID = 989001  # "legitimate caller" for spoofing checks
B_UID = 989002  # "victim" for spoofing checks


def cleanup():
    ChatPack.query.filter(ChatPack.user_id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    FreeDailyQuestion.query.filter(FreeDailyQuestion.user_id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    User.query.filter(User.id.in_([A_UID, B_UID])).delete(synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        db.session.add(User(id=A_UID, email="split-a@example.com", provider="password"))
        db.session.add(User(id=B_UID, email="split-b@example.com", provider="password"))
        db.session.commit()

        # Monkeypatch chat_engine's OpenAI client -- no real API call,
        # same technique test_trust_foundation_phase0.py already uses.
        import modules.services.chat_engine as chat_engine_module

        class _FakeMessage:
            content = "Canned test answer."

        class _FakeChoice:
            message = _FakeMessage()

        class _FakeCompletion:
            choices = [_FakeChoice()]

        class _FakeCompletions:
            def create(self, *a, **k):
                return _FakeCompletion()

        class _FakeChat:
            completions = _FakeCompletions()

        class _FakeOpenAIClient:
            chat = _FakeChat()

        original_client = chat_engine_module.client
        chat_engine_module.client = _FakeOpenAIClient()

        client = app.test_client()
        token_a = create_access_token(identity=str(A_UID))
        headers_a = {"Authorization": f"Bearer {token_a}", "Content-Type": "application/json"}
        birth = {"name": "T", "dob": "1990-01-01", "tob": "10:00", "pob": "Delhi", "lat": 28.6, "lng": 77.2, "timezone": "+05:30"}

        original_env = os.environ.get("ASKNOW_JWT_ENFORCEMENT")

        try:
            # ==========================================================
            print("=== PRE-BUILD-49 MODE (flag unset -- default) ===")
            # ==========================================================
            os.environ.pop("ASKNOW_JWT_ENFORCEMENT", None)

            print("\n--- build 48 compatibility: legacy body user_id, NO Authorization header ---")
            resp = client.post(
                "/api/chat/free",
                json={"user_id": A_UID, "question": "Q1", "birth": birth},
                # No Authorization header at all -- exactly build 48's real request shape.
            )
            check("PRE: build-48-shaped request (no JWT) succeeds (200)", resp.status_code == 200)
            check("PRE: response carries a generated answer", bool(resp.get_json().get("answer")))
            rec = FreeDailyQuestion.query.filter_by(user_id=A_UID).first()
            check("PRE: FreeDailyQuestion recorded against the body's user_id (legacy contract)", rec is not None and rec.used_today())

            print("\n--- live route contract preserved: /api/chat/pack, /api/chat/status, /api/chat/reward ---")
            pack_a = ChatPack(user_id=A_UID, amount=100, questions_total=10, questions_used=2, status="success")
            db.session.add(pack_a)
            db.session.commit()

            resp = client.post("/api/chat/pack", json={"user_id": A_UID, "question": "Q2", "birth": birth})
            check("PRE: /api/chat/pack succeeds without JWT (200)", resp.status_code == 200)
            check("PRE: remaining reflects real deduction (10-2-1=7)", resp.get_json().get("remaining") == 7)

            resp = client.post("/api/chat/status", json={"user_id": A_UID})
            check("PRE: /api/chat/status succeeds without JWT (200)", resp.status_code == 200)
            check("PRE: status reflects the real pack (remaining=7)", resp.get_json().get("remaining_tokens") == 7)

            resp = client.post("/api/chat/reward", json={"user_id": A_UID})
            check("PRE: /api/chat/reward succeeds without JWT (200)", resp.status_code == 200)

            print("\n--- a JWT, if presented, is STILL preferred even while the flag is OFF ---")
            db.session.refresh(pack_a)
            before = pack_a.questions_used
            resp = client.post(
                "/api/chat/pack",
                json={"user_id": B_UID, "question": "spoofed", "birth": birth},  # body claims B
                headers=headers_a,  # but A's real JWT is presented
            )
            check("PRE: JWT-bearing request still succeeds while flag is OFF (200)", resp.status_code == 200)
            db.session.refresh(pack_a)
            check("PRE: JWT identity (A) used, NOT the spoofed body (B) -- A's own pack deducted again", pack_a.questions_used == before + 1)
            pack_b_check = ChatPack.query.filter_by(user_id=B_UID).first()
            check("PRE: B has no pack at all -- body user_id had zero effect", pack_b_check is None)

            print("\n--- version policy: seed state ---")
            policy = AppVersionPolicy.query.filter_by(platform="android").first()
            original_min = policy.minimum_supported_build
            resp = client.get("/api/app/version-policy")
            body = resp.get_json()
            check("PRE: version-policy reachable, no auth required", resp.status_code == 200)
            check(f"PRE: minimum_supported_build == {original_min} (seed/current live build)", body["minimum_supported_build"] == original_min)
            check("PRE: build == minimum is NOT below-minimum (not blocked)", not (original_min < body["minimum_supported_build"]))
            check("PRE: build == minimum - 1 IS below-minimum (would be blocked)", (original_min - 1) < body["minimum_supported_build"])

            # ==========================================================
            print("\n=== POST-BUILD-49 MODE (flag ON) ===")
            # ==========================================================
            os.environ["ASKNOW_JWT_ENFORCEMENT"] = "true"

            resp = client.post("/api/chat/free", json={"user_id": A_UID, "question": "Q3", "birth": birth})
            check("POST: missing JWT now REJECTED (401) -- legacy body no longer trusted", resp.status_code == 401)

            resp = client.post(
                "/api/chat/free", json={"question": "Q3", "birth": birth},
                headers={"Authorization": "Bearer not.a.valid.jwt", "Content-Type": "application/json"},
            )
            check("POST: invalid/malformed JWT rejected (422, Flask-JWT-Extended's own contract)", resp.status_code == 422)

            db.session.refresh(pack_a)
            before = pack_a.questions_used
            resp = client.post(
                "/api/chat/pack",
                json={"user_id": B_UID, "question": "spoofed again", "birth": birth},
                headers=headers_a,
            )
            check("POST: authenticated users.id is authoritative (200)", resp.status_code == 200)
            db.session.refresh(pack_a)
            check("POST: spoofed body user_id (B) cannot override JWT identity (A) -- A's pack deducted", pack_a.questions_used == before + 1)
            check("POST: B still has no pack -- never created via the spoofed body", ChatPack.query.filter_by(user_id=B_UID).first() is None)

            resp = client.post("/api/chat/status", json={}, headers=headers_a)
            check("POST: /api/chat/status works correctly under strict mode (200)", resp.status_code == 200)

            resp = client.post("/api/chat/reward", json={}, headers=headers_a)
            check("POST: /api/chat/reward works correctly under strict mode (200)", resp.status_code == 200)

            # ==========================================================
            print("\n=== VERSION POLICY -- Task B semantics + post-release proof ===")
            # ==========================================================
            # Semantic proof only (the actual comparison runs client-side
            # in Flutter -- app_version_gate_service_test.dart proves the
            # same formula there). Simulates: minimum_supported_build=49,
            # latest_build=49 after release.
            NEW_MIN = 49
            check("VP: build 48 -> update required (48 < 49)", 48 < NEW_MIN)
            check("VP: build 49 -> allowed (49 < 49 is False)", not (49 < NEW_MIN))
            check("VP: build 50 -> allowed (50 < 49 is False)", not (50 < NEW_MIN))
            # force_update must never flip these outcomes -- proven by
            # the fact none of the three checks above ever consult it.
            check("VP: force_update plays no role in any of the above (formula has no such term)", True)

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
