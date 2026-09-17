import logging
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from dotenv import load_dotenv
from extensions import db
from models import Order
from email_utils import send_email
from modules.payments.report_delivery_service import deliver_generated_report
from summary_blocks import build_summary_blocks_with_transit
from full_kundali_api import calculate_full_kundali
from transit_engine import get_current_positions
from kundali_chart_generator import generate_kundali_drawing
from pdf_generator_weasy import generate_pdf_report_weasy as generate_pdf_report

# Q3 Batch 0 -- shared paid-report AI client/model (replaces this
# file's own former direct `from openai import OpenAI` + module-level
# client + hardcoded model="gpt-4o-mini"; see modules/payments/
# report_ai_client.py's own docstring for the full rationale, incl.
# the locked "no automatic model fallback" rule).
from modules.payments.report_ai_client import generate_report_completion
from modules.payments.report_product_intelligence import get_product_intelligence
from modules.payments.report_structured_output import (
    parse_structured_response,
    validate_required_hero_fields,
    assemble_answer_hero,
    assemble_gemstone_component,
    ReportMetadataError,
)
# ReportMetadataError is imported here ONLY to be RAISED (Q3 Batch 1 --
# gemstone_consultation's own-gemstone-missing case and saturn_transit_
# report's own-house-undetermined case below), never caught -- it must
# still propagate to this function's own existing `except Exception`
# below unchanged (see report_structured_output.py's own docstring).

# Q3 Batch 1 -- product-specific deterministic hero/timing/disclaimer
# wiring for the 4 newly-enabled products. See report_q3_batch1.py's
# own docstring; this introduces no new AI call, PDF component shape,
# or astrology calculation.
from modules.payments.report_q3_batch1 import (
    compute_gemstone_hero_value,
    compute_saturn_transit_hero,
    get_mandatory_disclaimer,
)

# Q3 Batch 2 -- product-specific deterministic timeline wiring for the
# 4 marriage-family products. See report_q3_batch2.py's own docstring;
# same "no new AI call/component shape/astrology calculation" rule.
from modules.payments.report_q3_batch2 import compute_dasha_window_timeline

# Q3 Batch 3 -- the 6 career/money/business products reuse the exact
# same compute_dasha_window_timeline() helper above (imported directly
# from report_q3_batch2, not re-exported/duplicated) -- see
# report_q3_batch3.py's own docstring for why this batch needs no
# compute_*_hero() function of its own.
from modules.payments.report_q3_batch3 import BATCH3_PRODUCT_SLUGS

# Q3 Batch 1 (visual QA correction round) -- shared, renderer-level
# label localization (see report_i18n_labels.py's own docstring) and
# the Q2.1 app-download CTA's verified store URL(s) (see app_config.py
# -- JYOTISHASHA_PLAY_STORE_URL is derived from the exact production
# package id already used by the live Force-Update system, never
# invented; JYOTISHASHA_APP_STORE_URL is None because this app does not
# yet ship on iOS).
from modules.payments.report_i18n_labels import get_label
from app_config import JYOTISHASHA_PLAY_STORE_URL, JYOTISHASHA_APP_STORE_URL

# Phase 4C -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from tasks.py.
from modules.activity_events.service import record_event

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
    completed (see each call site in _generate_and_send_report_core()).
    record_event() (Phase 2, unmodified) already guarantees it never
    raises and never touches db.session; this helper is additionally
    wrapped in its own try/except so an unexpected error in the small
    amount of dict-building above can never propagate into the
    Celery-task/thread caller -- it must never mark a successful report
    Failed, prevent Ready, trigger a retry, or otherwise alter the
    report pipeline. profile_id/firebase_uid are always None -- Order
    has no profile/account identity column of any kind (confirmed,
    Phase 4C Step 1 audit); no identity bridge is introduced.
    attempt_started_at is the LOCAL value captured once, at the moment
    this invocation's own first report_stage="Processing" commit
    succeeded -- never re-read from order.processing_started_at later,
    since that column is rewritten mid-attempt as a progress heartbeat
    (see the "Processing" commit's own comment below)."""
    # This entire body -- not just the record_event() call -- is wrapped
    # in one try/except. This function runs inside a Celery task/daemon
    # thread whose OWN outer except-Exception (see
    # _generate_and_send_report_core()) would otherwise misclassify a
    # genuinely successful report as report_stage="Failed" if anything
    # here raised -- an analytics-only bug must never be able to do
    # that, so nothing below this line is allowed to escape.
    try:
        properties = {}
        if report_type is not None:
            properties["report_type"] = report_type
        if failure_reason is not None:
            properties["failure_reason"] = failure_reason
        # Q3 Batch 0 -- AI usage/cost observability. No prompt text, no
        # response text, no customer PII -- model name + token counts +
        # duration only (modules/payments/report_ai_client.py's own
        # docstring states the same "never log content/PII" rule; this
        # is the one place that data is allowed to reach a durable log).
        # Property KEYS are "ai_*_units", not "*_tokens" -- discovered
        # by a real failing test that activity_events' own
        # _FORBIDDEN_KEY_SUBSTRINGS denylist (correctly) rejects any
        # key containing "token" as a defense-in-depth measure against
        # auth/session/API tokens, regardless of allowlist membership;
        # see event_schemas.py's own comment on this exact entry. The
        # local Python parameter names here stay input_tokens/
        # output_tokens/total_tokens (accurate, matches
        # ReportAICompletion's own field names) -- only the string keys
        # actually written into `properties` are renamed.
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

        # report_generation_started's occurred_at is the real, persisted
        # attempt-start moment (made explicitly timezone-aware ONLY for
        # this analytics call, never mutating the persisted naive-UTC
        # business column). completed/failed have no equivalent
        # persisted timestamp at this seam (Order has no "completed_at"/
        # "failed_at" column, and none is invented here) -- their
        # occurred_at is the actual moment of this emission.
        if event_name == "report_generation_started" and attempt_started_at is not None:
            occurred_at = attempt_started_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = datetime.now(timezone.utc)

        record_event(
            event_name=event_name,
            occurred_at=occurred_at,
            platform="backend_internal",
            source="report_generation_task",
            firebase_uid=None,
            profile_id=None,
            entity_type="order",
            entity_id=str(order_id),
            properties=properties,
            dedupe_key=dedupe_key,
        )
    except Exception:
        _activity_events_logger.warning(
            "tasks.py: unexpected error emitting %s for Order.id=%s "
            "(swallowed -- the report pipeline's own outcome is unaffected)",
            event_name, order_id, exc_info=True,
        )


# ------------------------------------------------------------
# 🧩 Optional Celery/Redis setup — enabled only if USE_CELERY=True
# ------------------------------------------------------------
from app_config import USE_CELERY
if USE_CELERY:
    from celery_app import celery
else:
    celery = None  # dummy placeholder for compatibility

# 🔧 Fix for app context
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app import app

# Load environment variables
load_dotenv()

# Q3 Batch 0 -- the module-level `openai_client = OpenAI(...)` that
# used to live here is gone; generate_report_completion()
# (modules/payments/report_ai_client.py) owns its own lazy singleton
# client now, shared with modules/love/love_premium_task.py instead of
# each file constructing its own.

# ------------------------------------------------------------
# 🚀 Dual-Mode Task Definition
# ------------------------------------------------------------
def _generate_and_send_report_core(order_id):
    """Shared report generation logic for both Celery and direct modes."""
    from modules.love.love_report_router import route_report_generation
    print(f"[Task] Starting report generation for Order ID: {order_id}")

    # Phase 4C -- captured once, the moment this invocation's own first
    # report_stage="Processing" commit succeeds (below). Stays None if
    # that commit is never reached/never happens (e.g. the Order.query.
    # get(order_id) race the existing `if order_model:` guard already
    # defends against) -- in that case no activity event is emitted
    # anywhere in this invocation rather than fabricating an attempt
    # identity that was never truthfully established.
    attempt_started_at = None

    try:
        with app.app_context():
            # Step 1: Order fetch
            order = get_order_details(order_id)
            if not order:
                print(f"[ERROR] Order {order_id} not found!")
                return
            
            # ⬇️ YAHAN ADD KARO
            product = order.get("product")
            if product == "relationship_future_report":
                routed = route_report_generation(order_id, product)
                return
            # ⬆️ YAHAN TAK

            # Payment Hardening Phase 6: mark this order as actively
            # processing BEFORE any real work begins, so a retry
            # arriving while this is still running can be told apart
            # from one arriving after a genuine failure (previously
            # both looked identical -- report_stage stuck at "Pending").
            order_model = Order.query.get(order_id)
            if order_model:
                order_model.report_stage = "Processing"
                # Payment Hardening Blocker 02: the only signal that lets
                # ReconciliationService later tell "still genuinely
                # running" apart from "abandoned -- the process that was
                # running this died" (crash/deploy restart, thread mode
                # has no other liveness signal). See reconciliation_service.py.
                order_model.processing_started_at = datetime.utcnow()
                db.session.commit()
                # Phase 4C -- report_generation_started. This is the ONE
                # true "attempt started" moment for this invocation --
                # captured into a local variable now, immediately after
                # the commit, and reused (never re-read from the column)
                # for every later activity event this invocation emits.
                # This column is rewritten again below as a progress
                # heartbeat after the GPT call returns -- that later
                # rewrite must NEVER be treated as a second "started".
                attempt_started_at = order_model.processing_started_at
                _emit_report_event(
                    event_name="report_generation_started",
                    order_id=order_id,
                    report_type=product,
                    attempt_started_at=attempt_started_at,
                )

            language = order.get("language", "en")
            print(f"[DEBUG] Language for this order: {language}")

            # Step 2: Kundali calculation
            kundali = calculate_full_kundali(
                name=order["name"],
                dob=order["dob"],
                tob=order["tob"],
                lat=float(order.get("latitude", 28.6139)),
                lon=float(order.get("longitude", 77.2090)),
                language=language
            )

            transit = get_current_positions()
            kundali["transit_summary"] = transit

            # Step 3: Summary blocks
            summary_blocks = build_summary_blocks_with_transit(kundali, transit)

            # Step 4: Prompt load
            product_slug = order["product"]
            template_path = f"prompts/{product_slug}_{language}.txt"
            try:
                with open(template_path, encoding="utf-8") as f:
                    template = f.read()
            except FileNotFoundError:
                print(f"[WARN] Template not found: {template_path}. Falling back to EN.")
                with open(f"prompts/{product_slug}_en.txt", encoding="utf-8") as f:
                    template = f.read()

            used_placeholders = re.findall(r"{(.*?)}", template)
            prompt_final = template.format(**summary_blocks)

            # Save prompt for debugging
            os.makedirs("debug_prompts", exist_ok=True)
            with open(f"debug_prompts/{product_slug}_{order_id}_prompt.txt", "w", encoding="utf-8") as f:
                f.write(prompt_final)

            # Step 5: AI call (Q3 Batch 0 -- shared Luna client). Raises
            # straight through on failure -- no automatic fallback
            # model (see report_ai_client.py's own docstring) -- caught
            # by this function's own existing outer except-Exception
            # below, exactly as an OpenAI failure already was before
            # this change.
            completion = generate_report_completion(prompt_final)

            # Q3 Batch 0/1 -- product-intelligence lookup. Exactly 4
            # products (gemstone_consultation, saturn_transit_report,
            # mood_mental_health_report, divorce_possibility_report)
            # have q3_enabled=True as of Batch 1; the `if` branch below
            # is unreachable for any of the other 21 products, which
            # keep their exact pre-Batch-0 narrative-only behavior.
            product_intel = get_product_intelligence(product_slug)
            answer_hero = None
            gemstone_component = None
            action_list_component = None
            timeline_component = None
            structured_metadata_valid = None  # None = not attempted

            if product_intel.q3_enabled:
                # Q3 Batch 0 correction #1 (LOCKED): missing/malformed
                # structured metadata for a Q3-enabled product is a
                # HARD FAILURE -- validate_required_hero_fields() raises
                # ReportMetadataError here, which propagates to this
                # function's own existing outer except-Exception and
                # becomes report_stage="Failed" (F2-recoverable),
                # exactly like any other generation failure. This never
                # silently degrades to a narrative-only report for a
                # Q3-enabled product -- Page 2 must answer the
                # purchased question, or the report is not delivered.
                metadata, gpt_content = parse_structured_response(completion.content)
                hero = validate_required_hero_fields(metadata, product_intel.required_hero_fields)

                # Q3 Batch 1 -- product-specific deterministic
                # value/timing overrides. AI's own value/timing is
                # discarded (never merged) whenever one of these is
                # supplied -- see assemble_answer_hero()'s own docstring.
                deterministic_value = None
                deterministic_timing = None
                if product_slug == "gemstone_consultation":
                    deterministic_value = compute_gemstone_hero_value(kundali.get("gemstone_suggestion"))
                    if not deterministic_value:
                        # This product's purchased answer IS the
                        # gemstone recommendation -- with no
                        # deterministic recommendation to show, this
                        # must FAIL rather than render an incomplete
                        # (or AI-invented) premium report.
                        raise ReportMetadataError(
                            "gemstone_consultation: deterministic gemstone "
                            "recommendation unavailable; the purchased "
                            "answer cannot be produced."
                        )
                elif product_slug == "saturn_transit_report":
                    saturn_hero = compute_saturn_transit_hero(kundali, language=language)
                    deterministic_value = saturn_hero["value"]
                    deterministic_timing = saturn_hero["timing"]
                    timeline_component = saturn_hero["timeline"]
                elif product_slug in ("marriage_report", "delay_in_marriage_report"):
                    # Q3 Batch 2 -- these 2 products (of the 4 marriage-
                    # family products) declare timeline=True in their
                    # registry entry; hero value/timing stay AI-authored
                    # (no deterministic override -- unlike gemstone_
                    # consultation/saturn_transit_report above, no
                    # marriage-scoring or marriage-timing-event engine
                    # exists to source a deterministic value from). Real
                    # Dasha-window dates only, never a guessed marriage
                    # date -- see report_q3_batch2.py's own docstring.
                    timeline_component = compute_dasha_window_timeline(kundali, language=language)
                elif product_slug in BATCH3_PRODUCT_SLUGS:
                    # Q3 Batch 3 -- all 6 career/money/business products
                    # declare timeline=True; hero value stays AI-
                    # authored for all 6 (no financial/career/business
                    # scoring engine exists to source a deterministic
                    # value from -- see report_q3_batch3.py's own
                    # docstring). Same Dasha-window helper as Batch 2,
                    # reused unchanged, never duplicated.
                    timeline_component = compute_dasha_window_timeline(kundali, language=language)

                answer_hero = assemble_answer_hero(
                    hero,
                    deterministic_value=deterministic_value,
                    deterministic_timing=deterministic_timing,
                )
                structured_metadata_valid = True

                if product_intel.gemstone_policy != "disabled":
                    gemstone_component = assemble_gemstone_component(
                        kundali.get("gemstone_suggestion"),
                        ai_reason=metadata.get("gemstone_reason"),
                    )
                    if gemstone_component is None and product_intel.gemstone_policy == "required":
                        # Q3 Batch 1 -- gemstone_consultation's own
                        # required-gemstone rule (see comment above):
                        # this branch is actually unreachable in
                        # practice since deterministic_value's own
                        # check above already caught the same missing
                        # data, but is kept as an explicit, direct
                        # safeguard against exactly this failure mode
                        # for any future "required" product.
                        raise ReportMetadataError(
                            f"{product_slug}: deterministic gemstone data "
                            "unavailable; this product's purchased answer "
                            "cannot be produced without it."
                        )

                # Q3 Batch 1 -- AI-authored action_items, only when the
                # product's own registry entry enables the component and
                # the metadata actually supplied a valid, non-empty list
                # of non-empty strings. Never invented by the backend.
                if product_intel.components_enabled.get("action_list"):
                    raw_items = metadata.get("action_items")
                    if isinstance(raw_items, list):
                        items = [item.strip() for item in raw_items if isinstance(item, str) and item.strip()]
                        if items:
                            action_list_component = {"heading": get_label("suggested_next_steps", language), "items": items}
            else:
                # Not yet migrated to Q3 structured output -- the
                # entire response is narrative, byte-for-byte the same
                # behavior as every report generated before Batch 0.
                gpt_content = completion.content

            # Q3 Batch 1 -- fixed, backend-controlled disclaimer text.
            # Never sourced from Luna's own output; returns None for
            # every disclaimer_type other than the two Batch-1 mandatory
            # ones, so this is inert for all other products/products'
            # existing behavior.
            disclaimer_text = get_mandatory_disclaimer(product_intel.disclaimer_type, language)

            # Q3 Batch 1 (visual QA correction) -- Q2.1's own LOCKED
            # closing CTA. Every paid report (not just the 4 Q3-enabled
            # ones -- this was a global gap, never wired from this call
            # site at all until now) ends with the Jyotishasha App
            # download CTA. No consultation/gemstone-purchase/cross-sell
            # copy is possible through this component (Q2.1's own
            # structural rule); play_store_url is the verified,
            # non-invented production URL from app_config.py,
            # app_store_url stays None (no verified iOS listing exists).
            app_download_component = {
                "heading": get_label("app_download_heading", language),
                "benefit_text": get_label("app_download_body", language),
                "play_store_url": JYOTISHASHA_PLAY_STORE_URL,
                "app_store_url": JYOTISHASHA_APP_STORE_URL,
            }

            # Payment Hardening Blocker 02.1 (Progress Heartbeat): GPT is
            # the one stage whose legitimate duration can approach the
            # abandonment threshold on its own (the OpenAI SDK's default
            # per-attempt timeout is 600s with up to 2 retries -- a
            # healthy call can take a long time before this line is ever
            # reached). Marking progress here, the moment it returns,
            # means a slow-but-successful GPT call is never mistaken for
            # an abandoned pipeline once PDF generation begins -- that
            # stage gets its own fresh window instead of inheriting
            # however long GPT happened to take.
            if order_model:
                order_model.processing_started_at = datetime.utcnow()
                db.session.commit()

            with open(f"debug_prompts/{product_slug}_{order_id}_gpt_response.txt", "w", encoding="utf-8") as f:
                f.write(gpt_content)

            # Step 6: Image + PDF
            safe_name = order["name"].replace(" ", "_")
            lagna_rashi = kundali.get("lagna_rashi") or kundali.get("lagna_sign")
            if not lagna_rashi:
                raise ValueError("Missing lagna_rashi in kundali result")

            RASHI_MAP = {
                "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
                "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
                "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12
            }
            rashi_number = RASHI_MAP.get(lagna_rashi) if isinstance(lagna_rashi, str) else lagna_rashi

            kundali_drawing = generate_kundali_drawing(
                planets=kundali["planets"],
                lagna_rashi=rashi_number
            )

            output_path = f"/home/Jyotishasha/reports/{product_slug}_{safe_name}.pdf"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            generate_pdf_report(
                output_path=output_path,
                user_info={
                    "name": order["name"],
                    "dob": order["dob"],
                    "tob": order["tob"],
                    "pob": order["pob"]
                },
                summary_blocks=summary_blocks,
                gpt_response=gpt_content,
                kundali_drawing=kundali_drawing,
                used_placeholders=used_placeholders,
                product=order["product"],
                # Q2 -- wires the language this function already resolves
                # (see `language` above) through to the PDF's own
                # typography choice.
                language=language,
                # Q3 Batch 0/1 -- None for every product not enabled in
                # the registry (generate_pdf_report_weasy() already
                # treats None as "render nothing" for all of these,
                # Q2/Q2.1); populated only for the 4 Q3 Batch 1 products
                # per their own registry configuration above.
                answer_hero=answer_hero,
                gemstone=gemstone_component,
                action_list=action_list_component,
                timeline=timeline_component,
                disclaimer=disclaimer_text,
                app_download=app_download_component,
            )

            # Step 7: Save + Email
            order_model = Order.query.get(order_id)
            if order_model:
                order_model.pdf_url = output_path
                order_model.report_stage = "Ready"
                db.session.commit()
                # Phase 4C -- report_generation_completed. Emitted only
                # after the Ready commit above, and strictly BEFORE the
                # email send below -- report_generation_completed means
                # the report itself was generated, independent of
                # whether delivery afterward succeeds. Task 17B: a
                # post-Ready email failure is now caught by its own
                # dedicated try/except immediately below (not this
                # function's outer one), which records truthful email
                # state and never touches report_stage.
                _emit_report_event(
                    event_name="report_generation_completed",
                    order_id=order_id,
                    report_type=product,
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

            # Task 17B -- deliberately its OWN try/except, separate from
            # this function's outer one below. report_stage is already
            # "Ready" at this point (the report itself is genuinely done);
            # an email failure must never be allowed to fall through to
            # the outer handler and either flip report_stage back toward
            # "Failed" or emit a misleading report_generation_failed event
            # for what is actually only a delivery failure. email_utils.
            # send_email() now RAISES on failure instead of swallowing it
            # (Task 17A's own root-cause finding) -- caught here, exactly
            # once, and turned into durable, truthful Order state instead.
            # Commits only ONCE, after the SMTP attempt has already
            # concluded either way -- never before -- so a DB failure here
            # can never falsely claim an email was sent (or attempted)
            # before the real SMTP outcome is already known.
            try:
                deliver_generated_report(order_id, output_path, send_email_fn=send_email)
                print(f"[Task] ✅ Email sent to {order['email']}")
            except Exception as email_exc:
                print(f"[Task] ❌ Error sending report email: {email_exc}")
                # Deliberately NOT re-raised -- report generation already
                # succeeded (report_stage == "Ready") and must stay that
                # way; see this block's own docstring-comment above.

    except Exception as e:
        print(f"[Task] ❌ Error generating report: {e}")
        traceback.print_exc()
        # Payment Hardening Phase 6: record that generation failed, so
        # a retry can safely resume instead of staying indistinguishable
        # from "still processing" forever. A fresh app context is
        # needed here since the one from the `with` block above has
        # already been torn down by the time this except runs.
        try:
            with app.app_context():
                order_model = Order.query.get(order_id)
                if order_model and order_model.report_stage != "Ready":
                    order_model.report_stage = "Failed"
                    db.session.commit()
                    # Phase 4C -- report_generation_failed. Emitted only
                    # after the Failed commit actually happened above --
                    # if the existing guard above skipped it (report_
                    # stage was already "Ready", or order_model is None),
                    # this event is correctly never emitted either.
                    # failure_reason is always "unknown" -- this pipeline
                    # has no typed exception hierarchy to classify more
                    # precisely (Phase 4C Step 1 audit finding), and raw
                    # exception text/traceback is never persisted here.
                    # attempt_started_at may legitimately be None (the
                    # exception happened before this invocation's own
                    # "Processing" commit was ever reached) -- in that
                    # case dedupe_key is None rather than fabricated.
                    _emit_report_event(
                        event_name="report_generation_failed",
                        order_id=order_id,
                        attempt_started_at=attempt_started_at,
                        failure_reason="unknown",
                    )
        except Exception as state_write_error:
            print(f"[Task] ⚠️ Could not record Failed report_stage: {state_write_error}")


# ------------------------------------------------------------
# 🧩 Mode Bridge — Choose Celery or Direct based on USE_CELERY
# ------------------------------------------------------------
if USE_CELERY:
    @celery.task(name="tasks.generate_and_send_report")
    def generate_and_send_report(order_id):
        """Celery asynchronous mode"""
        _generate_and_send_report_core(order_id)
else:
    def generate_and_send_report(order_id):
        """Direct synchronous mode"""
        _generate_and_send_report_core(order_id)


# ------------------------------------------------------------
# 🧾 Helper: fetch order details
# ------------------------------------------------------------
def get_order_details(order_id):
    from app import app
    with app.app_context():
        order = Order.query.get(order_id)
        if not order:
            return None
        return {
            "name": order.name,
            "email": order.email,
            "product": order.product,
            "dob": order.dob,
            "tob": order.tob,
            "pob": order.pob,
            "phone": order.phone,
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "latitude": getattr(order, "latitude", 28.6139),
            "longitude": getattr(order, "longitude", 77.2090),
            "language": getattr(order, "language", "en"),
        }


# ✅ Windows-only safety
if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
