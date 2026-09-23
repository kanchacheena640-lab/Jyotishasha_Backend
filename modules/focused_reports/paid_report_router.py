"""P0.3 -- Focused Reports Rs51 Payment Bridge: paid-order router.

Bridges a trusted, already-PAID Order into the existing, already-frozen
focused-report generation system (modules/focused_reports/dispatcher.py).
No astrology, prompt, evidence, Luna, or PDF logic is reimplemented here
-- every one of those steps calls the SAME existing function every other
caller already uses, unmodified.

CRITICAL SECURITY RULE: question_key is Order.product, and ONLY
Order.product. It is never accepted as a parameter from a webhook
payload, Razorpay notes, browser-supplied value, or visible question
text -- Order.product is durable DB state already validated once, at
pre-payment order-creation time, by OrderService.create_pending_order()
against the ReportProduct registry (see modules/payments/
report_generation_dispatcher.py's own module docstring for why this is
the one trustworthy source after payment).

FAIL-CLOSED CONTRACT: the caller (tasks.py) only makes a cheap, in-memory
"is this question_key a member of the focused-report family at all"
check (modules.focused_reports.dispatcher.HANDLERS -- zero DB access, so
every standard/relationship Order's routing decision stays exactly as
DB-free as it already was). The actual trust boundary lives entirely
HERE: this module resolves Order.product against BOTH the ReportProduct
registry (for the trusted `generator`) AND the authoritative catalog
(modules.intents.question_catalog, for `person_mode`), and requires the
two to agree (single -> "focused_v1", dual -> "focused_dual_v1"). Any
disagreement -- an unknown question_key, a registry row that's missing,
or a generator/person_mode mismatch -- is raised as
FocusedReportRoutingError BEFORE any kundali/evidence/Luna work begins.
This is a belt-and-suspenders check: the registry seed migration (P0.3)
and the catalog are two independently-maintained sources that must
agree; a future edit to either that silently drifts from the other is
caught here rather than silently misrouting a customer's payment to the
wrong report shape.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict

from extensions import db
from models import Order
from email_utils import send_email
from full_kundali_api import calculate_full_kundali
from modules.intents.question_catalog import get_question, UnknownQuestionError
from modules.focused_reports.dispatcher import generate_focused_report
from modules.focused_reports.pdf_adapter import render_focused_report_pdf
from modules.payments.report_delivery_service import deliver_generated_report
from modules.payments.report_product_registry import ReportProduct

SELF_GENERATOR = "focused_v1"
DUAL_GENERATOR = "focused_dual_v1"

_GENERATOR_TO_PERSON_MODE = {SELF_GENERATOR: "single", DUAL_GENERATOR: "dual"}


class FocusedReportRoutingError(Exception):
    """Raised for a trust/contract violation caught before any generation
    work begins (unknown question_key, or catalog person_mode disagreeing
    with the trusted registry generator). Fails closed -- never guesses,
    never defaults to either shape."""


def _customer_fields(name, dob, tob, pob) -> Dict[str, str]:
    return {"name": name, "dob": dob, "tob": tob, "pob": pob}


def _build_pdf_customer(order: Order) -> Dict[str, Any]:
    """Shape required by pdf_adapter.render_focused_report_pdf()'s own
    `customer` argument -- name/dob/tob/pob, plus a `partner` block with
    the same four keys for a dual-person report. Reuses Order's existing
    columns/partner_payload verbatim; no new field, no reformatting."""
    customer = _customer_fields(order.name, order.dob, order.tob, order.pob)
    partner = order.partner_payload
    if isinstance(partner, dict) and partner:
        customer["partner"] = _customer_fields(
            partner.get("name"), partner.get("dob"), partner.get("tob"), partner.get("pob"),
        )
    return customer


def route_focused_report_generation(order_id: int) -> None:
    """Called by tasks.py::_generate_and_send_report_core() for an Order
    whose product is a member of modules.focused_reports.dispatcher.HANDLERS
    (a cheap, in-memory, no-DB membership check the caller already made --
    see that call site's own comment for why: it keeps the standard/
    relationship pipelines' own existing "zero DB access for this routing
    decision" property intact for every Order that isn't a focused
    product). The actual trust boundary -- resolving Order.product against
    the ReportProduct registry and requiring its generator to agree with
    the catalog's own person_mode -- is owned entirely HERE, the one place
    reached only for a genuine focused-report Order.

    Mirrors the existing, proven lifecycle (modules/love/
    love_premium_task.py::generate_love_premium_report): Processing ->
    build astrology input -> ONE generate_focused_report() call -> PDF
    -> Ready -> deliver_generated_report() -> Failed on any exception
    (unless already Ready). Reuses that exact state machine; does not
    reimplement it.
    """
    order = Order.query.get(order_id)
    if order is None:
        raise FocusedReportRoutingError(f"Order {order_id} not found.")

    # SECURITY: the ONE and ONLY source of question_key. See module docstring.
    question_key = order.product

    try:
        question = get_question(question_key)
    except UnknownQuestionError as exc:
        raise FocusedReportRoutingError(
            f"Order {order_id}: Order.product={question_key!r} is not a known "
            f"focused-report question_key."
        ) from exc

    product = ReportProduct.query.get(question_key)
    generator = product.generator if product is not None else None
    expected_mode = _GENERATOR_TO_PERSON_MODE.get(generator)
    if expected_mode is None or question.person_mode != expected_mode:
        raise FocusedReportRoutingError(
            f"Order {order_id}: catalog person_mode={question.person_mode!r} for "
            f"question_key={question_key!r} does not agree with trusted "
            f"registry generator={generator!r} -- refusing to guess, failing closed."
        )

    order.report_stage = "Processing"
    order.processing_started_at = datetime.utcnow()
    db.session.commit()

    try:
        language = order.language or "en"

        if question.person_mode == "dual":
            partner = order.partner_payload if isinstance(order.partner_payload, dict) else {}
            # Shape required by modules/focused_reports/relationship_evidence.py::
            # collect_relationship_evidence(): {user:{...}, partner:{...},
            # boy_is_user: bool}. latitude/longitude pass through verbatim --
            # _profile() there already accepts either latitude/longitude or
            # lat/lng, and calls calculate_full_kundali() itself for BOTH
            # people; no kundali is pre-built here for a dual report.
            #
            # boy_is_user: no Order/partner_payload field encodes this today
            # for ANY paid product -- modules/love/love_premium_task.py's own
            # existing, live relationship_future_report pipeline hardcodes
            # boy_is_user=True unconditionally (verified: it never reads this
            # from the Order). Reusing that exact same existing convention
            # here, not inventing a new one or a new field.
            payload = {
                "user": {
                    "name": order.name, "dob": order.dob, "tob": order.tob, "pob": order.pob,
                    "latitude": order.latitude, "longitude": order.longitude,
                },
                "partner": {
                    "name": partner.get("name"), "dob": partner.get("dob"), "tob": partner.get("tob"),
                    "pob": partner.get("pob"), "latitude": partner.get("latitude"),
                    "longitude": partner.get("longitude"),
                },
                "boy_is_user": True,
            }
            result = generate_focused_report(question_key, payload, language)
        else:
            kundali = calculate_full_kundali(
                name=order.name, dob=order.dob, tob=order.tob,
                lat=float(order.latitude), lon=float(order.longitude), language=language,
            )
            result = generate_focused_report(question_key, kundali, language)

        customer = _build_pdf_customer(order)
        safe_name = (order.name or "customer").replace(" ", "_")
        output_path = f"/home/Jyotishasha/reports/focused_{safe_name}_{order_id}.pdf"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        path = render_focused_report_pdf(result, customer, output_path)

        order.pdf_url = path
        order.report_stage = "Ready"
        db.session.commit()

        try:
            # send_email_fn passed explicitly (matching tasks.py's own and
            # love_premium_task.py's own identical call convention) so a
            # caller/test can mock this module's own `send_email` name
            # rather than reaching into report_delivery_service's already-
            # bound default parameter.
            deliver_generated_report(order_id, path, send_email_fn=send_email)
        except Exception as email_exc:
            # Matches love_premium_task.py's own existing outer-catch-and-log
            # policy for the email step: report_stage stays "Ready" (the PDF
            # genuinely exists), only email_status reflects the failure
            # (deliver_generated_report() itself already records that).
            print("[FOCUSED REPORT EMAIL ERROR]", email_exc)

    except Exception:
        # Matches love_premium_task.py's own outer-except pattern: re-query
        # rather than trust the in-memory `order` object, and never
        # overwrite report_stage="Ready" if generation actually completed
        # before whatever failed (e.g. the email step already handled its
        # own exception above and never reaches here).
        failed_order = Order.query.get(order_id)
        if failed_order is not None and failed_order.report_stage != "Ready":
            failed_order.report_stage = "Failed"
            db.session.commit()
        raise
