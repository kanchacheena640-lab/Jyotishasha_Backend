"""
test_report_activity_events.py
-------------------------------------------------
Phase 4C: proves the Reports domain's 3 canonical activity events
(report_generation_started, report_generation_completed,
report_generation_failed) are emitted at the correct, already-frozen
producer points across BOTH report systems:

  A. AIReport / cached synchronous report generation
     (modules/ai_report_engine/lifecycle_manager.py) -- completed/
     failed only, report_generation_started deliberately NEVER
     implemented (no durable pre-generation state exists).

  B. Purchased PDF Order report generation (tasks.py and
     modules/love/love_premium_task.py) -- all 3 events, with the
     "captured once, at the true Processing commit, never re-read
     after the mid-pipeline heartbeat rewrite" attempt-identity
     contract.

with the exact identity/entity/properties/dedupe contract the Phase 4C
design freeze locked, and that analytics failure of every kind can
never alter the report business result -- including analytics
exceptions raised from inside a synchronously-invoked report-generation
function body (the tasks.py/love_premium_task.py "task/thread" shape),
where an escaping exception would otherwise be caught by that
function's own outer except and incorrectly flip a successful report
to report_stage="Failed".

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real OpenAI/kundali/PDF/email calls are ever
made -- every external/expensive call inside the Order pipelines is
monkeypatched to a deterministic fake for the duration of each call;
AIReport tests use a tiny in-test fake ReportGenerator instead of any
real segment generator. All test rows are created with dedicated,
obviously-test-only markers and deleted in a finally block, keyed by
their own ids -- never a broad DELETE.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

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

    from models import Order
    from modules.models_user import AppUser
    from modules.models_ai_reports import AIReport

    from modules.activity_events.service import LedgerWriteResult
    import modules.ai_report_engine.lifecycle_manager as lifecycle_manager_module
    from modules.ai_report_engine.lifecycle_manager import (
        ReportLifecycleManager, ReportGenerationError,
    )
    from modules.ai_report_engine.cache_repository import ReportCacheRepository
    from modules.ai_report_engine.generator_interface import GeneratedReport, ReportGenerator
    from modules.ai_report_engine.exceptions import (
        ContextBuildError, OpenAICallError, OutputValidationError,
    )

    import tasks as tasks_module
    import modules.love.love_premium_task as love_task_module

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"REFUSING to run against {current_db!r} -- local only."
        )

        created_app_user_ids = []
        created_ai_report_ids = []
        created_order_ids = []
        created_event_ids = []

        def new_profile():
            au = AppUser(firebase_uid=f"phase4c-test-{uuid.uuid4().hex[:10]}")
            db.session.add(au)
            db.session.commit()
            created_app_user_ids.append(au.id)
            return au.id

        def new_order(product="career_report", partner_payload=None):
            o = Order(
                name="Phase4C Test", email=f"phase4c-{uuid.uuid4().hex[:8]}@example.com",
                phone="9999999999", product=product,
                dob="1990-01-01", tob="10:00", pob="Delhi, India",
                language="en", status="PAID",
                latitude="28.6139", longitude="77.2090",
                partner_payload=partner_payload,
            )
            db.session.add(o)
            db.session.commit()
            created_order_ids.append(o.id)
            return o.id

        def get_ledger_row(dedupe_key):
            return db.session.execute(
                text("SELECT * FROM activity_events WHERE dedupe_key = :dk"),
                {"dk": dedupe_key},
            ).fetchone()

        def rows_for_entity(entity_type, entity_id, event_name=None):
            if event_name:
                return db.session.execute(
                    text(
                        "SELECT * FROM activity_events WHERE entity_type = :et "
                        "AND entity_id = :eid AND event_name = :en ORDER BY recorded_at"
                    ),
                    {"et": entity_type, "eid": str(entity_id), "en": event_name},
                ).fetchall()
            return db.session.execute(
                text(
                    "SELECT * FROM activity_events WHERE entity_type = :et "
                    "AND entity_id = :eid ORDER BY recorded_at"
                ),
                {"et": entity_type, "eid": str(entity_id)},
            ).fetchall()

        def track_event(row):
            if row is not None:
                created_event_ids.append(str(row.event_id))
            return row

        def track_all(rows):
            for r in rows:
                created_event_ids.append(str(r.event_id))
            return rows

        # ==============================================================
        # Fake ReportGenerator for AIReport tests -- full control, no
        # real segment generator / OpenAI call involved.
        # ==============================================================
        class FakeGenerator(ReportGenerator):
            def __init__(self, content="fake content", raises=None):
                self._content = content
                self._raises = raises
                self.call_count = 0

            def generate(self, *, profile_id, report_type, language):
                self.call_count += 1
                if self._raises is not None:
                    raise self._raises
                return GeneratedReport(content_json={"text": self._content})

        try:
            # ==========================================================
            print("=== 1: AIReport -- first successful generation ===")
            # ==========================================================
            profile1 = new_profile()
            gen1 = FakeGenerator(content="v1")
            manager1 = ReportLifecycleManager(generators={"LOVE": gen1})
            result1 = manager1.get_report(profile_id=profile1, segment="LOVE", report_type="DNA", language="en")
            check("1: business result has content", result1.get("content_json") == {"text": "v1"})
            row1_db = AIReport.query.filter_by(profile_id=profile1, segment="LOVE", report_type="DNA", language="en").first()
            check("1: AIReport row created with status READY", row1_db is not None and row1_db.status == "READY")
            if row1_db:
                created_ai_report_ids.append(row1_db.id)
                dedupe1 = f"report_generation_completed:AI_REPORT:{row1_db.id}:{row1_db.generated_at.isoformat()}"
                row1_evt = track_event(get_ledger_row(dedupe1))
                check("1: report_generation_completed row exists", row1_evt is not None)
                if row1_evt:
                    check("1: platform/source correct", row1_evt.platform == "backend_internal" and row1_evt.source == "ai_report_lifecycle_manager")
                    check("1: profile_id correct", row1_evt.profile_id == profile1)
                    check("1: firebase_uid None", row1_evt.firebase_uid is None)
                    check("1: entity_type/entity_id correct", row1_evt.entity_type == "ai_report" and row1_evt.entity_id == str(row1_db.id))
                    check("1: properties == {report_type: DNA} only", row1_evt.properties == {"report_type": "DNA"})
                    check("1: no report_generation_started row exists for this entity", len(rows_for_entity("ai_report", row1_db.id, "report_generation_started")) == 0)

            # ==========================================================
            print("\n=== 2: AIReport -- cached read (no regeneration) emits NO new event ===")
            # ==========================================================
            before_count_2 = len(rows_for_entity("ai_report", row1_db.id))
            result2 = manager1.get_report(profile_id=profile1, segment="LOVE", report_type="DNA", language="en")
            check("2: cached content returned, generator NOT called again", gen1.call_count == 1)
            after_count_2 = len(rows_for_entity("ai_report", row1_db.id))
            check("2: no new activity_events row for this entity", after_count_2 == before_count_2)

            # ==========================================================
            print("\n=== 3: AIReport -- successful regeneration (CURRENT_PHASE, forced expiry) ===")
            # ==========================================================
            profile3 = new_profile()
            gen3 = FakeGenerator(content="phase-v1")
            manager3 = ReportLifecycleManager(generators={"LOVE": gen3})
            result3a = manager3.get_report(profile_id=profile3, segment="LOVE", report_type="CURRENT_PHASE", language="en")
            row3_db = AIReport.query.filter_by(profile_id=profile3, segment="LOVE", report_type="CURRENT_PHASE", language="en").first()
            created_ai_report_ids.append(row3_db.id)
            generated_at_1 = row3_db.generated_at
            dedupe3a = f"report_generation_completed:AI_REPORT:{row3_db.id}:{generated_at_1.isoformat()}"
            row3a_evt = track_event(get_ledger_row(dedupe3a))
            check("3: first completed row exists", row3a_evt is not None)

            # Force expiry so the next call regenerates.
            row3_db.expires_at = datetime.utcnow() - __import__("datetime").timedelta(seconds=1)
            db.session.commit()
            gen3._content = "phase-v2"
            result3b = manager3.get_report(profile_id=profile3, segment="LOVE", report_type="CURRENT_PHASE", language="en")
            check("3: regeneration actually ran", gen3.call_count == 2)
            db.session.refresh(row3_db)
            generated_at_2 = row3_db.generated_at
            check("3: generated_at changed on regeneration", generated_at_2 != generated_at_1)
            dedupe3b = f"report_generation_completed:AI_REPORT:{row3_db.id}:{generated_at_2.isoformat()}"
            row3b_evt = track_event(get_ledger_row(dedupe3b))
            check("3: second completed row exists with a DIFFERENT canonical dedupe", row3b_evt is not None and dedupe3a != dedupe3b)
            check("3: exactly 2 completed rows total for this entity", len(rows_for_entity("ai_report", row3_db.id, "report_generation_completed")) == 2)

            # ==========================================================
            print("\n=== 4: AIReport -- first-ever generation failure: NO event, NO row ===")
            # ==========================================================
            profile4 = new_profile()
            gen4 = FakeGenerator(raises=RuntimeError("boom"))
            manager4 = ReportLifecycleManager(generators={"LOVE": gen4})
            threw4 = False
            try:
                manager4.get_report(profile_id=profile4, segment="LOVE", report_type="DNA", language="en")
            except ReportGenerationError:
                threw4 = True
            check("4: ReportGenerationError still raised (business behavior unchanged)", threw4 is True)
            row4_db = AIReport.query.filter_by(profile_id=profile4, segment="LOVE", report_type="DNA", language="en").first()
            check("4: NO AIReport row was created", row4_db is None)
            fail_rows_4 = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE event_name='report_generation_failed' AND profile_id=:pid"),
                {"pid": profile4},
            ).scalar()
            check("4: NO report_generation_failed row exists for this profile", fail_rows_4 == 0)

            # ==========================================================
            print("\n=== 5: AIReport -- regeneration failure: failed event after authoritative FAILED commit ===")
            # ==========================================================
            profile5 = new_profile()
            gen5 = FakeGenerator(content="ok")
            manager5 = ReportLifecycleManager(generators={"LOVE": gen5})
            manager5.get_report(profile_id=profile5, segment="LOVE", report_type="CURRENT_PHASE", language="en")
            row5_db = AIReport.query.filter_by(profile_id=profile5, segment="LOVE", report_type="CURRENT_PHASE", language="en").first()
            created_ai_report_ids.append(row5_db.id)
            # This initial successful generation also emits its own
            # report_generation_completed row -- track it for cleanup too.
            track_event(get_ledger_row(f"report_generation_completed:AI_REPORT:{row5_db.id}:{row5_db.generated_at.isoformat()}"))
            row5_db.expires_at = datetime.utcnow() - __import__("datetime").timedelta(seconds=1)
            db.session.commit()
            gen5._raises = OpenAICallError("simulated OpenAI failure")
            threw5 = False
            try:
                manager5.get_report(profile_id=profile5, segment="LOVE", report_type="CURRENT_PHASE", language="en")
            except ReportGenerationError:
                threw5 = True
            check("5: ReportGenerationError raised", threw5 is True)
            db.session.refresh(row5_db)
            check("5: authoritative status FAILED", row5_db.status == "FAILED")
            failed_rows_5 = track_all(rows_for_entity("ai_report", row5_db.id, "report_generation_failed"))
            check("5: exactly one report_generation_failed row", len(failed_rows_5) == 1)
            if failed_rows_5:
                check("5: failure_reason == upstream_error (OpenAICallError mapping)", failed_rows_5[0].properties.get("failure_reason") == "upstream_error")
                check("5: dedupe_key is None", failed_rows_5[0].dedupe_key is None)
                check("5: profile_id/entity correct", failed_rows_5[0].profile_id == profile5 and failed_rows_5[0].entity_id == str(row5_db.id))

            # ==========================================================
            print("\n=== 6: AIReport -- two separate regeneration failures both persist (dedupe_key=None) ===")
            # ==========================================================
            gen5._raises = ContextBuildError("simulated context failure")
            threw6 = False
            try:
                manager5.get_report(profile_id=profile5, segment="LOVE", report_type="CURRENT_PHASE", language="en")
            except ReportGenerationError:
                threw6 = True
            check("6: second failure also raised", threw6 is True)
            failed_rows_6 = track_all(rows_for_entity("ai_report", row5_db.id, "report_generation_failed"))
            check("6: now TWO report_generation_failed rows exist (not deduped away)", len(failed_rows_6) == 2)
            check("6: second failure classified unknown (ContextBuildError mapping)", failed_rows_6[-1].properties.get("failure_reason") == "unknown")

            # ==========================================================
            print("\n=== 7: AIReport -- concurrent first-generation race collapses to ONE completed row ===")
            # ==========================================================
            profile7 = new_profile()
            repo7 = ReportCacheRepository()
            real_save_cache = ReportCacheRepository.save_cache
            call_state = {"n": 0}

            def racy_save_cache(self, **kwargs):
                call_state["n"] += 1
                if call_state["n"] == 1:
                    # Simulate a concurrent winner inserting first.
                    winner = AIReport(
                        profile_id=kwargs["profile_id"], segment=kwargs["segment"],
                        report_type=kwargs["report_type"], language=kwargs["language"],
                        content_json=kwargs["content_json"], status="READY",
                        generated_at=datetime.utcnow(), expires_at=kwargs["expires_at"],
                    )
                    db.session.add(winner)
                    db.session.commit()
                return real_save_cache(self, **kwargs)

            ReportCacheRepository.save_cache = racy_save_cache
            try:
                gen7 = FakeGenerator(content="race")
                manager7 = ReportLifecycleManager(generators={"LOVE": gen7}, repository=repo7)
                result7 = manager7.get_report(profile_id=profile7, segment="LOVE", report_type="DNA", language="en")
            finally:
                ReportCacheRepository.save_cache = real_save_cache
            row7_db = AIReport.query.filter_by(profile_id=profile7, segment="LOVE", report_type="DNA", language="en").first()
            created_ai_report_ids.append(row7_db.id)
            completed_rows_7 = track_all(rows_for_entity("ai_report", row7_db.id, "report_generation_completed"))
            check("7: race recovered to the winner's row, exactly ONE completed row (dedupe collapse)", len(completed_rows_7) == 1)

            # ==========================================================
            print("\n=== 8: AIReport -- analytics failure isolation ===")
            # ==========================================================
            profile8 = new_profile()

            with patch("modules.ai_report_engine.lifecycle_manager.record_event") as mock_re_8a:
                mock_re_8a.return_value = LedgerWriteResult(status="write_failed")
                gen8a = FakeGenerator(content="8a")
                manager8a = ReportLifecycleManager(generators={"LOVE": gen8a})
                result8a = manager8a.get_report(profile_id=profile8, segment="LOVE", report_type="DNA", language="en")
            check("8a write_failed: business result unchanged", result8a.get("content_json") == {"text": "8a"})
            row8a_db = AIReport.query.filter_by(profile_id=profile8, segment="LOVE", report_type="DNA", language="en").first()
            created_ai_report_ids.append(row8a_db.id)
            check("8a write_failed: AIReport row still committed READY", row8a_db is not None and row8a_db.status == "READY")

            profile8b = new_profile()
            with patch("modules.ai_report_engine.lifecycle_manager.record_event") as mock_re_8b:
                mock_re_8b.side_effect = RuntimeError("simulated unexpected analytics exception")
                gen8b = FakeGenerator(content="8b")
                manager8b = ReportLifecycleManager(generators={"LOVE": gen8b})
                result8b = manager8b.get_report(profile_id=profile8b, segment="LOVE", report_type="DNA", language="en")
            check("8b exception: does NOT propagate, business result unchanged", result8b.get("content_json") == {"text": "8b"})
            row8b_db = AIReport.query.filter_by(profile_id=profile8b, segment="LOVE", report_type="DNA", language="en").first()
            created_ai_report_ids.append(row8b_db.id)
            check("8b exception: AIReport row still committed READY", row8b_db is not None and row8b_db.status == "READY")

            profile8c = new_profile()
            real_env = os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            try:
                gen8c = FakeGenerator(content="8c")
                manager8c = ReportLifecycleManager(generators={"LOVE": gen8c})
                result8c = manager8c.get_report(profile_id=profile8c, segment="LOVE", report_type="DNA", language="en")
            finally:
                if real_env is not None:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = real_env
            check("8c missing env: business result unchanged", result8c.get("content_json") == {"text": "8c"})
            row8c_db = AIReport.query.filter_by(profile_id=profile8c, segment="LOVE", report_type="DNA", language="en").first()
            created_ai_report_ids.append(row8c_db.id)
            check("8c missing env: AIReport row still committed READY", row8c_db is not None and row8c_db.status == "READY")
            check("8c missing env: no completed row persisted for this entity", len(rows_for_entity("ai_report", row8c_db.id, "report_generation_completed")) == 0)

            profile8d = new_profile()
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "not_a_real_environment"
            try:
                gen8d = FakeGenerator(content="8d")
                manager8d = ReportLifecycleManager(generators={"LOVE": gen8d})
                result8d = manager8d.get_report(profile_id=profile8d, segment="LOVE", report_type="DNA", language="en")
            finally:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            check("8d invalid env: business result unchanged", result8d.get("content_json") == {"text": "8d"})
            row8d_db = AIReport.query.filter_by(profile_id=profile8d, segment="LOVE", report_type="DNA", language="en").first()
            created_ai_report_ids.append(row8d_db.id)
            check("8d invalid env: AIReport row still committed READY", row8d_db is not None and row8d_db.status == "READY")

            # ==============================================================
            # ORDER GENERAL PIPELINE (tasks.py) -- heavy mocking of every
            # external/expensive call so _generate_and_send_report_core()
            # can be invoked directly and synchronously, deterministically.
            # ==============================================================
            def fake_kundali(**kwargs):
                return {"lagna_rashi": "Aries", "planets": {}}

            def fake_transit():
                return {}

            def fake_summary_blocks(kundali, transit):
                return {
                    "birth_chart_summary": "x", "current_transit_summary": "x",
                    "mahadasha_summary": "x",
                }

            def fake_drawing(**kwargs):
                return "fake_drawing"

            def fake_pdf(**kwargs):
                return None

            def fake_send_email(*a, **k):
                return None

            class _FakeCompletions:
                def __init__(self, content):
                    self._content = content

                def create(self, **kwargs):
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
                    )

            class _FakeOpenAIClient:
                def __init__(self, content="Fake generated report body."):
                    self.chat = SimpleNamespace(completions=_FakeCompletions(content))

            def apply_tasks_mocks(openai_content="Fake generated report body."):
                tasks_module.calculate_full_kundali = fake_kundali
                tasks_module.get_current_positions = fake_transit
                tasks_module.build_summary_blocks_with_transit = fake_summary_blocks
                tasks_module.generate_kundali_drawing = fake_drawing
                tasks_module.generate_pdf_report = fake_pdf
                tasks_module.send_email = fake_send_email
                tasks_module.openai_client = _FakeOpenAIClient(openai_content)

            real_tasks_attrs = {
                name: getattr(tasks_module, name) for name in (
                    "calculate_full_kundali", "get_current_positions",
                    "build_summary_blocks_with_transit", "generate_kundali_drawing",
                    "generate_pdf_report", "send_email", "openai_client",
                )
            }

            def restore_tasks_mocks():
                for name, value in real_tasks_attrs.items():
                    setattr(tasks_module, name, value)

            # ==========================================================
            print("\n=== 9: Order pipeline -- first Processing commit -> exactly one started ===")
            # ==========================================================
            order9_id = new_order(product="career_report")
            apply_tasks_mocks()
            try:
                tasks_module._generate_and_send_report_core(order9_id)
            finally:
                restore_tasks_mocks()
            order9 = Order.query.get(order9_id)
            check("9: report_stage Ready (business result unchanged)", order9.report_stage == "Ready")
            attempt9 = order9.processing_started_at  # NOTE: heartbeat may have moved this; use started row to get true attempt id
            started_rows_9 = track_all(rows_for_entity("order", order9_id, "report_generation_started"))
            check("9: exactly ONE report_generation_started row", len(started_rows_9) == 1)
            completed_rows_9 = track_all(rows_for_entity("order", order9_id, "report_generation_completed"))
            check("10: exactly ONE report_generation_completed row (Ready commit)", len(completed_rows_9) == 1)
            if started_rows_9 and completed_rows_9:
                # Extract the attempt-identity suffix by removing the known
                # "<event_name>:ORDER:<order_id>:" prefix -- NOT rsplit(":", 1),
                # since an ISO timestamp itself contains colons.
                prefix_9 = f"ORDER:{order9_id}:"
                started_dedupe_9 = started_rows_9[0].dedupe_key
                completed_dedupe_9 = completed_rows_9[0].dedupe_key
                attempt_id_9 = started_dedupe_9.split(prefix_9, 1)[-1]
                check("2/j: heartbeat rewrite did NOT create a second started row (already proven by count==1 above)", True)
                check("4: completed event uses the SAME attempt timestamp identity as started", completed_dedupe_9.split(prefix_9, 1)[-1] == attempt_id_9)
                check("9: platform/source correct", started_rows_9[0].platform == "backend_internal" and started_rows_9[0].source == "report_generation_task")
                check("9: profile_id/firebase_uid both None", started_rows_9[0].profile_id is None and started_rows_9[0].firebase_uid is None)
                check("9: entity_type/entity_id == order/<id>", started_rows_9[0].entity_type == "order" and started_rows_9[0].entity_id == str(order9_id))
                check("9: properties == {report_type: career_report}", started_rows_9[0].properties == {"report_type": "career_report"})
                check("10: completed properties == {report_type: career_report}", completed_rows_9[0].properties == {"report_type": "career_report"})
                # Sanity-check the extracted attempt identity is a real,
                # parseable ISO timestamp (proves the prefix-strip above
                # actually isolated the timestamp, not a truncated colon
                # fragment).
                check("attempt identity is a well-formed ISO timestamp", datetime.fromisoformat(attempt_id_9) is not None)

            # ==========================================================
            print("\n=== 11/12: Order pipeline -- Failed commit -> failed event, failure_reason unknown ===")
            # ==========================================================
            order11_id = new_order(product="a-product-with-no-real-prompt-template-phase4c")
            apply_tasks_mocks()
            try:
                tasks_module._generate_and_send_report_core(order11_id)
            finally:
                restore_tasks_mocks()
            order11 = Order.query.get(order11_id)
            check("11: report_stage Failed", order11.report_stage == "Failed")
            started_rows_11 = track_all(rows_for_entity("order", order11_id, "report_generation_started"))
            check("11: started row still exists (Processing was truthfully reached)", len(started_rows_11) == 1)
            failed_rows_11 = track_all(rows_for_entity("order", order11_id, "report_generation_failed"))
            check("11: exactly one report_generation_failed row", len(failed_rows_11) == 1)
            if failed_rows_11 and started_rows_11:
                check("11: failure_reason == unknown", failed_rows_11[0].properties.get("failure_reason") == "unknown")
                prefix_11 = f"ORDER:{order11_id}:"
                check("12: failed event uses the SAME attempt timestamp identity as started", failed_rows_11[0].dedupe_key.split(prefix_11, 1)[-1] == started_rows_11[0].dedupe_key.split(prefix_11, 1)[-1])
                check("11: no exception text/traceback in properties", "traceback" not in str(failed_rows_11[0].properties) and "Traceback" not in str(failed_rows_11[0].properties))
            completed_rows_11 = rows_for_entity("order", order11_id, "report_generation_completed")
            check("11: NO report_generation_completed row (pipeline genuinely failed)", len(completed_rows_11) == 0)

            # ==========================================================
            print("\n=== 13/14: Order pipeline -- redispatch produces a fresh, non-deduped started/completed pair ===")
            # ==========================================================
            order13_id = new_order(product="career_report")
            apply_tasks_mocks()
            try:
                tasks_module._generate_and_send_report_core(order13_id)
            finally:
                restore_tasks_mocks()
            started_first = track_all(rows_for_entity("order", order13_id, "report_generation_started"))
            completed_first = track_all(rows_for_entity("order", order13_id, "report_generation_completed"))
            # Simulate a real redispatch: same Order, pipeline invoked again
            # (mirrors OrderService.redispatch_report_generation() calling
            # the exact same function again for an existing order_id).
            apply_tasks_mocks(openai_content="Second attempt body.")
            try:
                tasks_module._generate_and_send_report_core(order13_id)
            finally:
                restore_tasks_mocks()
            started_all = track_all(rows_for_entity("order", order13_id, "report_generation_started"))
            completed_all = track_all(rows_for_entity("order", order13_id, "report_generation_completed"))
            check("13: redispatch produced a SECOND, distinct started row (fresh attempt timestamp)", len(started_all) == 2 and started_all[0].dedupe_key != started_all[1].dedupe_key)
            check("14: redispatch produced a SECOND, distinct completed row (not deduped against the first)", len(completed_all) == 2 and completed_all[0].dedupe_key != completed_all[1].dedupe_key)

            # ==========================================================
            print("\n=== 15/16: Order pipeline -- analytics failure isolation (including post-Ready) ===")
            # ==========================================================
            order15_id = new_order(product="career_report")
            with patch("tasks.record_event") as mock_re_15:
                mock_re_15.return_value = LedgerWriteResult(status="write_failed")
                apply_tasks_mocks()
                try:
                    tasks_module._generate_and_send_report_core(order15_id)
                finally:
                    restore_tasks_mocks()
            order15 = Order.query.get(order15_id)
            check("15 write_failed: report_stage STILL Ready (business unaffected)", order15.report_stage == "Ready")

            order16_id = new_order(product="career_report")
            with patch("tasks.record_event") as mock_re_16:
                mock_re_16.side_effect = RuntimeError("simulated unexpected analytics exception")
                apply_tasks_mocks()
                try:
                    tasks_module._generate_and_send_report_core(order16_id)
                finally:
                    restore_tasks_mocks()
            order16 = Order.query.get(order16_id)
            check(
                "16 exception: report_stage STILL Ready -- an analytics exception raised from INSIDE the "
                "record_event() call (post-Ready commit) did NOT propagate to this function's own outer "
                "except and did NOT flip Ready back to Failed",
                order16.report_stage == "Ready",
            )

            order17_id = new_order(product="career_report")
            real_env_17 = os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
            try:
                apply_tasks_mocks()
                try:
                    tasks_module._generate_and_send_report_core(order17_id)
                finally:
                    restore_tasks_mocks()
            finally:
                if real_env_17 is not None:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = real_env_17
            order17 = Order.query.get(order17_id)
            check("missing env: report_stage STILL Ready", order17.report_stage == "Ready")
            check("missing env: no started/completed rows persisted", len(rows_for_entity("order", order17_id)) == 0)

            order18_id = new_order(product="career_report")
            os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "not_a_real_environment"
            try:
                apply_tasks_mocks()
                try:
                    tasks_module._generate_and_send_report_core(order18_id)
                finally:
                    restore_tasks_mocks()
            finally:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
            order18 = Order.query.get(order18_id)
            check("invalid env: report_stage STILL Ready", order18.report_stage == "Ready")

            # ==============================================================
            # LOVE PREMIUM PIPELINE (modules/love/love_premium_task.py)
            # ==============================================================
            def fake_love_collect(**kwargs):
                return {"fake": "payload"}

            def fake_love_prompt(payload):
                return "Fake love prompt."

            def apply_love_mocks(openai_content="Fake love report body."):
                love_task_module.calculate_full_kundali = fake_kundali
                love_task_module.get_current_positions = fake_transit
                love_task_module.collect_love_report_data = fake_love_collect
                love_task_module.build_love_premium_prompt = fake_love_prompt
                love_task_module.generate_kundali_drawing = fake_drawing
                love_task_module.generate_pdf_report = fake_pdf
                love_task_module.send_email = fake_send_email
                love_task_module.openai_client = _FakeOpenAIClient(openai_content)

            real_love_attrs = {
                name: getattr(love_task_module, name) for name in (
                    "calculate_full_kundali", "get_current_positions",
                    "collect_love_report_data", "build_love_premium_prompt",
                    "generate_kundali_drawing", "generate_pdf_report",
                    "send_email", "openai_client",
                )
            }

            def restore_love_mocks():
                for name, value in real_love_attrs.items():
                    setattr(love_task_module, name, value)

            # ==========================================================
            print("\n=== 17a: Love premium pipeline -- Processing -> started, Ready -> completed ===")
            # ==========================================================
            order_love_ok_id = new_order(
                product="relationship_future_report",
                partner_payload={"name": "Test Partner", "dob": "1991-02-02", "tob": "11:00", "pob": "Mumbai, India"},
            )
            apply_love_mocks()
            try:
                love_task_module.generate_love_premium_report(order_love_ok_id)
            finally:
                restore_love_mocks()
            order_love_ok = Order.query.get(order_love_ok_id)
            check("17a: report_stage Ready", order_love_ok.report_stage == "Ready")
            love_started = track_all(rows_for_entity("order", order_love_ok_id, "report_generation_started"))
            love_completed = track_all(rows_for_entity("order", order_love_ok_id, "report_generation_completed"))
            check("17a: exactly one started (no second from heartbeat)", len(love_started) == 1)
            check("17a: exactly one completed", len(love_completed) == 1)
            if love_started and love_completed:
                check("17a: source == love_premium_report_task", love_started[0].source == "love_premium_report_task")
                prefix_love = f"ORDER:{order_love_ok_id}:"
                check("17a: attempt identity shared between started/completed", love_started[0].dedupe_key.split(prefix_love, 1)[-1] == love_completed[0].dedupe_key.split(prefix_love, 1)[-1])
                check("17a: identity/entity correct", love_started[0].profile_id is None and love_started[0].firebase_uid is None and love_started[0].entity_type == "order")
                check("17a: properties == {report_type: relationship_future_report}", love_completed[0].properties == {"report_type": "relationship_future_report"})

            # ==========================================================
            print("\n=== 17b: Love premium pipeline -- failure (missing partner details) -> failed ===")
            # ==========================================================
            order_love_fail_id = new_order(product="relationship_future_report", partner_payload=None)
            apply_love_mocks()
            try:
                love_task_module.generate_love_premium_report(order_love_fail_id)
            finally:
                restore_love_mocks()
            order_love_fail = Order.query.get(order_love_fail_id)
            check("17b: report_stage Failed", order_love_fail.report_stage == "Failed")
            love_started_fail = track_all(rows_for_entity("order", order_love_fail_id, "report_generation_started"))
            love_failed = track_all(rows_for_entity("order", order_love_fail_id, "report_generation_failed"))
            check("17b: started row exists (Processing was reached before the partner-details check)", len(love_started_fail) == 1)
            check("17b: exactly one failed row", len(love_failed) == 1)
            if love_failed:
                check("17b: failure_reason == unknown", love_failed[0].properties.get("failure_reason") == "unknown")

            # ==========================================================
            print("\n=== 17c: Love premium pipeline -- analytics failure isolation ===")
            # ==========================================================
            order_love_iso_id = new_order(
                product="relationship_future_report",
                partner_payload={"name": "Test Partner", "dob": "1991-02-02", "tob": "11:00", "pob": "Mumbai, India"},
            )
            with patch("modules.love.love_premium_task.record_event") as mock_re_love:
                mock_re_love.side_effect = RuntimeError("simulated unexpected analytics exception")
                apply_love_mocks()
                try:
                    love_task_module.generate_love_premium_report(order_love_iso_id)
                finally:
                    restore_love_mocks()
            order_love_iso = Order.query.get(order_love_iso_id)
            check("17c: report_stage STILL Ready despite analytics exception", order_love_iso.report_stage == "Ready")

            # ==========================================================
            print("\n=== 18: Security scan -- no forbidden content anywhere in rows created above ===")
            # ==========================================================
            all_test_event_ids = list(dict.fromkeys(created_event_ids))
            forbidden_substrings = [
                "1990-01-01", "Delhi, India", "phase4c-", "@example.com",
                "Fake generated report body", "Fake love report body",
                "Fake love prompt", "boom", "simulated", "Traceback",
                "/home/Jyotishasha/reports",
            ]
            leak_found = False
            for eid in all_test_event_ids:
                row = db.session.execute(
                    text("SELECT * FROM activity_events WHERE event_id = :id"), {"id": eid},
                ).fetchone()
                if row is None:
                    continue
                serialized = str(row.properties) + str(row.dedupe_key) + str(row.entity_id) + str(row.correlation_id) + str(row.campaign_context) + str(row.notification_context)
                for term in forbidden_substrings:
                    if term in serialized:
                        leak_found = True
                        print(f"  LEAK: {term!r} found in row {eid}")
            check("18: no report content/prompt/OpenAI text/email/name/DOB/POB/path/exception text found in any row", leak_found is False)

        finally:
            # ----------------------------------------------------------
            # Cleanup -- precise, per-row, never a broad DELETE.
            # ----------------------------------------------------------
            for eid in dict.fromkeys(created_event_ids):
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()

            for oid in dict.fromkeys(created_order_ids):
                db.session.execute(text("DELETE FROM orders WHERE id = :id"), {"id": oid})
            db.session.commit()

            for rid in dict.fromkeys(created_ai_report_ids):
                db.session.execute(text("DELETE FROM ai_reports WHERE id = :id"), {"id": rid})
            db.session.commit()

            for uid in dict.fromkeys(created_app_user_ids):
                db.session.execute(text("DELETE FROM app_users WHERE id = :id"), {"id": uid})
            db.session.commit()

            remaining_events = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE event_id = ANY(:ids)"),
                {"ids": [uuid.UUID(e) for e in dict.fromkeys(created_event_ids)] or [uuid.uuid4()]},
            ).scalar()
            check("cleanup: all Phase-4C activity_events rows removed", remaining_events == 0)

            remaining_orders = Order.query.filter(Order.id.in_(created_order_ids or [-1])).count()
            check("cleanup: all Phase-4C Order fixtures removed", remaining_orders == 0)

            remaining_reports = AIReport.query.filter(AIReport.id.in_(created_ai_report_ids or [-1])).count()
            check("cleanup: all Phase-4C AIReport fixtures removed", remaining_reports == 0)

            remaining_users = AppUser.query.filter(AppUser.id.in_(created_app_user_ids or [-1])).count()
            check("cleanup: all Phase-4C AppUser fixtures removed", remaining_users == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
