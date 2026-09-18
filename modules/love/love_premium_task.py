# Path: modules/love/love_premium_task.py
# Jyotishasha — Love Premium Report Task
#
# This plugs Love Premium into the EXISTING report pipeline.
# No change to old reports.

import logging
import os
import traceback
from datetime import datetime, timezone
from dotenv import load_dotenv

from full_kundali_api import calculate_full_kundali
from transit_engine import get_current_positions
from kundali_chart_generator import generate_kundali_drawing
from pdf_generator_weasy import generate_pdf_report_weasy as generate_pdf_report
from email_utils import send_email
from modules.payments.report_delivery_service import deliver_generated_report
from models import Order
from extensions import db
from app import app

# Love-specific modules
from modules.love.love_data_collector import collect_love_report_data
from modules.love.love_prompt_builder import build_love_premium_prompt

# Phase 4C -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from modules.love.
from modules.activity_events.service import record_event

# Q3 Batch 0 -- shared paid-report AI client/model (replaces this
# file's own former direct `from openai import OpenAI` + module-level
# client + hardcoded model="gpt-4o-mini"; see modules/payments/
# report_ai_client.py's own docstring for the full rationale, incl.
# the locked "no automatic model fallback" rule). Same shared client
# tasks.py now uses -- no separate OpenAI client instance lives here
# anymore.
from modules.payments.report_ai_client import generate_report_completion
from modules.payments.report_product_intelligence import get_product_intelligence
from modules.payments.report_q3_batch1 import get_mandatory_disclaimer
from modules.payments.report_i18n_labels import get_label
from app_config import JYOTISHASHA_PLAY_STORE_URL, JYOTISHASHA_APP_STORE_URL
from modules.payments.report_structured_output import (
    ReportMetadataError,
    parse_structured_response,
    validate_required_hero_fields,
    assemble_answer_hero,
)
# Invalid Q3 metadata propagates to the existing Failed/recovery path;
# it never silently degrades to a narrative-only delivered report.

load_dotenv()

_activity_events_logger = logging.getLogger("activity_events")


def _emit_report_event(
    *,
    event_name,
    order_id,
    attempt_started_at,
    report_type=None,
    failure_reason=None,
    # Q3 Batch 0 -- AI usage/cost observability (report_generation_
    # completed only; see call site). Never PII: a model name and four
    # numbers. None means "not applicable/not attempted" and is simply
    # omitted below, matching every other optional field's convention
    # in this function.
    model=None,
    input_tokens=None,
    output_tokens=None,
    total_tokens=None,
    duration_seconds=None,
    structured_metadata_valid=None,
):
    """Phase 4C -- observational only, called ONLY after this pipeline's
    own authoritative report_stage commit for this attempt has already
    completed (see each call site in generate_love_premium_report()).
    Same contract as tasks.py's own _emit_report_event() (a separate,
    intentionally-duplicated copy per the Phase 4C design freeze --
    these two pipelines are not refactored together in this phase);
    see that function's own docstring for the full non-regression
    reasoning. This entire body -- not just the record_event() call --
    is wrapped in one try/except so nothing here can ever propagate
    into this Celery-task/thread's own outer except-Exception, which
    would otherwise misclassify a genuinely successful report as
    Failed. profile_id/firebase_uid are always None -- Order has no
    profile/account identity column of any kind."""
    try:
        properties = {}
        if report_type is not None:
            properties["report_type"] = report_type
        if failure_reason is not None:
            properties["failure_reason"] = failure_reason
        # Q3 Batch 0 -- AI usage/cost observability. No prompt text, no
        # response text, no customer PII -- model name + token counts +
        # duration only. Property KEYS are "ai_*_units", not
        # "*_tokens" -- activity_events' own _FORBIDDEN_KEY_SUBSTRINGS
        # denylist rejects any key containing "token" (defense-in-depth
        # against auth/session/API tokens) regardless of allowlist
        # membership; see event_schemas.py's own comment on this exact
        # entry, and tasks.py's identical fix. Local Python parameter
        # names stay input_tokens/output_tokens/total_tokens (matches
        # ReportAICompletion's own field names) -- only the string keys
        # written into `properties` are renamed.
        if model is not None:
            properties["model"] = model
        if input_tokens is not None:
            properties["ai_input_units"] = input_tokens
        if output_tokens is not None:
            properties["ai_output_units"] = output_tokens
        if total_tokens is not None:
            properties["ai_total_units"] = total_tokens
        if duration_seconds is not None:
            properties["duration_seconds"] = round(duration_seconds, 3)
        if structured_metadata_valid is not None:
            properties["structured_metadata_valid"] = structured_metadata_valid

        dedupe_key = None
        if attempt_started_at is not None:
            dedupe_key = f"{event_name}:ORDER:{order_id}:{attempt_started_at.isoformat()}"

        if event_name == "report_generation_started" and attempt_started_at is not None:
            occurred_at = attempt_started_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = datetime.now(timezone.utc)

        record_event(
            event_name=event_name,
            occurred_at=occurred_at,
            platform="backend_internal",
            source="love_premium_report_task",
            firebase_uid=None,
            profile_id=None,
            entity_type="order",
            entity_id=str(order_id),
            properties=properties,
            dedupe_key=dedupe_key,
        )
    except Exception:
        _activity_events_logger.warning(
            "love_premium_task.py: unexpected error emitting %s for "
            "Order.id=%s (swallowed -- the report pipeline's own "
            "outcome is unaffected)",
            event_name, order_id, exc_info=True,
        )


def generate_love_premium_report(order_id: int):
    """
    END-TO-END Love Premium Report Generator
    Dedicated relationship product; pricing remains owned by ReportProduct.
    """
    # Phase 4C -- captured once, the moment this invocation's own first
    # report_stage="Processing" commit succeeds (below). See tasks.py's
    # own _generate_and_send_report_core() for the full reasoning.
    attempt_started_at = None

    try:
        with app.app_context():

            # ---------------- 1) Fetch Order ----------------
            order = Order.query.get(order_id)
            if not order:
                raise RuntimeError(f"Order {order_id} not found")

            # Payment Hardening Phase 6: mark as actively processing
            # before any real work begins (see tasks.py for the same
            # pattern and its rationale).
            order.report_stage = "Processing"
            # Payment Hardening Blocker 02: same abandonment-detection
            # signal as tasks.py -- see that file and
            # reconciliation_service.py for how it's used.
            order.processing_started_at = datetime.utcnow()
            db.session.commit()
            # Phase 4C -- report_generation_started. The ONE true
            # "attempt started" moment for this invocation -- captured
            # now, reused (never re-read from the column) for every
            # later activity event this invocation emits. processing_
            # started_at is rewritten again below as a progress
            # heartbeat -- that later rewrite must NEVER be treated as
            # a second "started".
            attempt_started_at = order.processing_started_at
            _emit_report_event(
                event_name="report_generation_started",
                order_id=order_id,
                report_type=order.product,
                attempt_started_at=attempt_started_at,
            )

            language = getattr(order, "language", "en")

            # ---------------- 2) User Kundali ----------------
            kundali = calculate_full_kundali(
                name=order.name,
                dob=order.dob,
                tob=order.tob,
                lat=float(order.latitude),
                lon=float(order.longitude),
                language=language,
            )

            transit = get_current_positions()
            kundali["transit_summary"] = transit

            # ---------------- 3) Partner safety check ----------------
            partner_payload = getattr(order, "partner_payload", None)
            if not partner_payload:
                raise RuntimeError("Partner details missing for love premium report")

            # ---------------- 4) Love Data Collection ----------------
            love_payload = collect_love_report_data(
                order={
                    "name": order.name,
                    "dob": order.dob,
                    "tob": order.tob,
                    "pob": order.pob,
                    "latitude": order.latitude,
                    "longitude": order.longitude,
                    "language": language,
                    "partner": partner_payload,
                },
                user_kundali=kundali,
                language=language,
                boy_is_user=True,
            )

            # ---------------- 5) Prompt Build ----------------
            final_prompt = build_love_premium_prompt(love_payload)
            
            print("\n========== LOVE PREMIUM FINAL PROMPT START ==========\n")
            print(final_prompt)
            print("\n========== LOVE PREMIUM FINAL PROMPT END ==========\n")

            # Debug save (recommended)
            os.makedirs("debug_prompts", exist_ok=True)
            with open(f"debug_prompts/love_{order_id}.txt", "w", encoding="utf-8") as f:
                f.write(final_prompt)

            # ---------------- 6) AI Call (Q3 Batch 0 -- shared Luna client) ----------------
            # Raises straight through on failure -- no automatic
            # fallback model (see report_ai_client.py's own docstring)
            # -- caught by this function's own existing outer
            # except-Exception below, exactly as an OpenAI failure
            # already was before this change.
            completion = generate_report_completion(final_prompt)

            # Q3 Batch 4: dedicated structured relationship contract.
            product_intel = get_product_intelligence("relationship_future_report")
            answer_hero = None
            structured_metadata_valid = None  # None = not attempted

            disclaimer_text = get_mandatory_disclaimer(product_intel.disclaimer_type, language)
            app_download_component = {
                "heading": get_label("app_download_heading", language),
                "benefit_text": get_label("app_download_body", language),
                "play_store_url": JYOTISHASHA_PLAY_STORE_URL,
                "app_store_url": JYOTISHASHA_APP_STORE_URL,
            }
            if product_intel.q3_enabled:
                # Q3 Batch 0 correction #1 (LOCKED): missing/malformed
                # structured metadata for a Q3-enabled product is a
                # HARD FAILURE -- propagates to this function's own
                # existing outer except-Exception and becomes
                # report_stage="Failed" (F2-recoverable), never a
                # silent narrative-only degrade.
                metadata, report_text = parse_structured_response(completion.content)
                # The premium wire contract names this object "hero"; adapt
                # locally to the shared parser/validator's answer_hero contract.
                if isinstance(metadata, dict) and "hero" in metadata:
                    metadata = {"answer_hero": metadata["hero"]}
                hero = validate_required_hero_fields(metadata, product_intel.required_hero_fields)
                hero["label"] = product_intel.hero_label
                if any(char.isdigit() or char == "%" for char in hero["value"]):
                    raise ReportMetadataError("Relationship Outlook must be qualitative, not a score or percentage.")
                # The engine owns the supporting total; never trust Luna's
                # reproduction of it. Other chart evidence stays interpretive.
                hero["evidence"] = [
                    item for item in hero["evidence"]
                    if "ashtakoot" not in item.lower() and "अष्टकूट" not in item
                ]
                score = (love_payload["compatibility"].get("ashtakoot") or {}).get("total_score")
                if isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 36:
                    score_label = "अष्टकूट अनुकूलता" if language == "hi" else "Ashtakoot compatibility"
                    hero["evidence"].insert(0, f"{score_label}: {score:g}/36")
                if not hero["evidence"]:
                    raise ReportMetadataError("Relationship Outlook supporting evidence unavailable.")
                answer_hero = assemble_answer_hero(hero)
                structured_metadata_valid = True
            else:
                # Not yet migrated to Q3 structured output -- entire
                # response is narrative, byte-for-byte the same
                # behavior as before Batch 0.
                report_text = completion.content

            report_text = report_text[:18000]

            # Payment Hardening Blocker 02.1 (Progress Heartbeat): same
            # reasoning as tasks.py -- GPT's own legitimate worst-case
            # duration can approach the abandonment threshold on its
            # own, so progress is marked here, the moment it returns,
            # rather than only once at the very start of Processing.
            order.processing_started_at = datetime.utcnow()
            db.session.commit()

            # ---------------- 7) Kundali Drawing ----------------
            RASHI_MAP = {
                "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
                "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
                "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12
            }

            lagna = kundali.get("lagna_rashi") or kundali.get("lagna_sign")
            lagna_number = RASHI_MAP.get(lagna, lagna)

            kundali_drawing = generate_kundali_drawing(
                planets=kundali["planets"],
                lagna_rashi=lagna_number,   # ✅ ab numeric (1–12)
            )

            # ---------------- 8) PDF ----------------
            safe_name = order.name.replace(" ", "_")
            output_path = f"/home/Jyotishasha/reports/love_{safe_name}_{order_id}.pdf"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            generate_pdf_report(
                output_path=output_path,
                user_info={
                    "name": order.name,
                    "dob": order.dob,
                    "tob": order.tob,
                    "pob": order.pob,
                },
                summary_blocks={},  # Love report uses GPT narrative
                gpt_response=report_text,
                kundali_drawing=kundali_drawing,
                used_placeholders=[],
                product="relationship_future_report",
                # Q2 -- wires the language this function already resolves
                # (see `language` above) through to the PDF's own
                # typography choice.
                language=language,
                answer_hero=answer_hero,
                gemstone=None,
                disclaimer=disclaimer_text,
                app_download=app_download_component,
                action_list={"heading": get_label("suggested_next_steps", language),
                             "items": answer_hero.get("action_items", [])} if answer_hero else None,
            )

            del kundali_drawing

            # ---------------- 9) Save + Email ----------------
            order.pdf_url = output_path
            order.report_stage = "Ready"
            db.session.commit()
            # Phase 4C -- report_generation_completed. Emitted only
            # after the Ready commit above, strictly BEFORE the email
            # send below -- same semantic boundary as tasks.py (a
            # post-Ready email failure is caught by this function's own
            # outer except, which already refuses to overwrite
            # report_stage back to "Failed" once it is "Ready").
            _emit_report_event(
                event_name="report_generation_completed",
                order_id=order_id,
                report_type=order.product,
                attempt_started_at=attempt_started_at,
                # Q3 Batch 0 -- AI usage/cost observability. No
                # prompt/response content, no PII -- see
                # _emit_report_event()'s own docstring/comment.
                model=completion.model,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                total_tokens=completion.total_tokens,
                duration_seconds=completion.duration_seconds,
                structured_metadata_valid=structured_metadata_valid,
            )

            try:
                deliver_generated_report(order_id, output_path, send_email_fn=send_email)
            except Exception as email_exc:
                print("[LOVE PREMIUM EMAIL ERROR]", email_exc)

            import gc
            gc.collect()

    except Exception as e:
        print("[LOVE PREMIUM TASK ERROR]", e)
        traceback.print_exc()
        # Payment Hardening Phase 6: same failure-state recording as
        # tasks.py -- a fresh app context is needed since the one from
        # the `with` block above has already been torn down here.
        try:
            with app.app_context():
                order_model = Order.query.get(order_id)
                if order_model and order_model.report_stage != "Ready":
                    order_model.report_stage = "Failed"
                    db.session.commit()
                    # Phase 4C -- report_generation_failed. failure_reason
                    # is always "unknown" -- this pipeline has no typed
                    # exception hierarchy to classify more precisely; raw
                    # exception text/traceback is never persisted here.
                    # attempt_started_at may legitimately be None (e.g.
                    # "Order not found" raised before the Processing
                    # commit was ever reached) -- dedupe_key is then None
                    # rather than fabricated.
                    _emit_report_event(
                        event_name="report_generation_failed",
                        order_id=order_id,
                        attempt_started_at=attempt_started_at,
                        failure_reason="unknown",
                    )
        except Exception as state_write_error:
            print("[LOVE PREMIUM TASK ERROR] Could not record Failed report_stage:", state_write_error)
