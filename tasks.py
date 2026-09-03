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
from summary_blocks import build_summary_blocks_with_transit
from full_kundali_api import calculate_full_kundali
from transit_engine import get_current_positions
from openai import OpenAI
from kundali_chart_generator import generate_kundali_drawing
from pdf_generator_weasy import generate_pdf_report_weasy as generate_pdf_report

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

# OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

            # Step 5: GPT call
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt_final}]
            )
            gpt_content = response.choices[0].message.content.strip()

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
                product=order["product"]
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
                )

            subject = f"Your {product_slug.replace('-', ' ').title()} Report"
            body = (
                f"Hello {order['name']},\n\n"
                f"Please find attached your personalized astrology report.\n\n"
                f"Regards,\nTeam Jyotishasha"
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
                send_email(order["email"], subject, body, output_path)
                print(f"[Task] ✅ Email sent to {order['email']}")
                email_order = Order.query.get(order_id)
                if email_order:
                    now = datetime.utcnow()
                    email_order.email_last_attempt_at = now
                    email_order.email_status = "SENT"
                    email_order.email_sent_at = now
                    email_order.email_error = None
                    db.session.commit()
            except Exception as email_exc:
                print(f"[Task] ❌ Error sending report email: {email_exc}")
                try:
                    email_order = Order.query.get(order_id)
                    if email_order:
                        email_order.email_last_attempt_at = datetime.utcnow()
                        email_order.email_status = "FAILED"
                        # Bounded/sanitized: smtplib's own exception text never
                        # contains SENDER_PASSWORD/credentials, but this is
                        # truncated defensively regardless -- this column's
                        # only job is "give an operator a clue," never a full
                        # traceback or provider internals.
                        email_order.email_error = str(email_exc)[:500]
                        db.session.commit()
                except Exception as state_write_error:
                    print(f"[Task] ⚠️ Could not record email FAILED state: {state_write_error}")
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
