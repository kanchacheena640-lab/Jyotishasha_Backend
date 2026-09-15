# modules/payments/order_service.py

"""
OrderService -- the business-logic home for "a report purchase was
paid for," outside of app.py's inline handling. This is what
PaymentService delegates to for PaymentPurpose.REPORT_PURCHASE, per
this phase's "PaymentService -> OrderService / SubscriptionService"
separation of concerns.

create_paid_report_order() reproduces EXACTLY what app.py's /webhook
route does today: build an Order with status="PAID" from the same
field set (name/email/phone/product/dob/tob/pob/language/latitude/
longitude/partner), commit it, then dispatch report generation via
Celery or a background thread depending on app_config.USE_CELERY --
same table, same status value, same dispatch mechanism, same
tasks.generate_and_send_report function.

Phase 2 wires app.py's /webhook route to call this directly (bypassing
PaymentService.process_payment()'s verification gate for now -- see
that route's own comment and this phase's output notes for exactly
why: the current Website client sends none of Razorpay's verification
fields to this endpoint, so enforcing verification there today would
reject every legitimate purchase). Nothing in tasks.py,
pdf_generator_weasy.py, or email_utils.py is touched, reimplemented,
or duplicated here -- this only reproduces the order-creation-and-
dispatch step that used to live inline in app.py, not the report
generation pipeline itself.

Payment Hardening Phase 5 (Safe Retry Policy) adds two things, both
additive:
    - ReportDispatchError, raised by create_paid_report_order() instead
      of letting a bare dispatch exception propagate, so the caller
      (PaymentService) learns the order_id that WAS already committed
      even though dispatch failed afterward -- without this, a later
      retry would have no safe way to know an Order already exists for
      that payment and would risk creating a second one.
    - redispatch_report_generation(order_id), which re-triggers
      generation for an EXISTING, already-paid Order. It never creates
      an Order and never re-runs payment verification -- it is only
      ever called by PaymentService for a payment that was already
      verified and whose Order was already created, when that Order's
      report_stage shows the pipeline never reached "Ready".
"""

from __future__ import annotations

import threading
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

from extensions import db
from models import Order
from modules.payments.report_product_registry import ReportProduct


class OrderValidationError(ValueError):
    """
    Paid Report Platform v1.0 -- R3. Raised by create_pending_order()
    for a missing/unknown/inactive report_slug, or a missing required
    report input, ALWAYS before any Order is added to the session --
    see create_pending_order()'s own docstring: validation runs
    entirely before db.session.add(), so a rejection here never leaves
    a partial row and never needs a rollback (nothing was ever
    staged). A ValueError subclass (not a bare ValueError) so a future
    caller can distinguish "this payload was invalid" from any other
    ValueError, while every existing catch-ValueError call site keeps
    working unchanged.
    """


class ReportDispatchError(Exception):
    """
    Raised by create_paid_report_order() when the Order was committed
    successfully but dispatching report generation failed. Carries
    order_id so the caller can record it even though the overall call
    failed -- the one piece of information a later safe retry needs to
    resume the SAME order instead of creating a duplicate.
    """

    def __init__(self, order_id: int, original_exception: Exception):
        self.order_id = order_id
        self.original_exception = original_exception
        super().__init__(f"Order {order_id} was created, but dispatch failed: {original_exception}")


# ---------------------------------------------------------------------
# Paid Report Platform v1.0 -- R3. The exact, currently-proven required-
# input sets for each generator -- derived directly from the real, live
# code that already enforces or depends on them, never invented:
#
#   - jyotishasha-frontend/components/reports/ReportCheckout.tsx::
#     handleSubmit() (the live purchase gate for every standard-report
#     product) rejects the purchase attempt unless name/email/phone/
#     dob/tob/pob/latitude/longitude are all present.
#   - tasks.py::_generate_and_send_report_core() bracket-accesses
#     order["name"]/["dob"]/["tob"]/["pob"]/["email"] (crashes if
#     missing); latitude/longitude have a silent Delhi fallback there,
#     but the live customer-facing form already requires real values --
#     this preserves that stricter, existing customer contract rather
#     than the looser one a crash-avoidance-only reading of tasks.py
#     would suggest.
# ---------------------------------------------------------------------
STANDARD_REQUIRED_FIELDS = (
    "name", "email", "phone", "dob", "tob", "pob", "latitude", "longitude",
)

# jyotishasha-frontend/app/[locale]/love/report/relationship_future_report/
# RelationshipFutureReportForm.tsx's own entire component state has NO
# phone field for either person at all -- confirmed absent, not merely
# optional -- so phone is deliberately NOT required here, unlike every
# standard report. Boy-side fields mirror that live form's own required
# inputs (name/email/dob/tob/pob/latitude/longitude) exactly.
#
# modules/love/love_data_collector.py::collect_love_report_data() hard-
# raises LoveCollectorError for a missing user name/dob/tob or lat/lng;
# modules/love/love_premium_task.py itself hard-raises RuntimeError for
# a missing/falsy partner_payload. Partner-side pob is required here to
# match that same live form's own contract (it collects pob for both
# people identically) even though collect_love_report_data()'s own
# narrower internal check only hard-requires partner name+dob --
# under-requiring here would let an Order through that the live form
# itself would never have allowed to reach payment in the first place.
LOVE_PREMIUM_PRODUCT_SLUG = "relationship_future_report"
LOVE_PREMIUM_GENERATOR = "love_premium_v1"
LOVE_PREMIUM_PRIMARY_REQUIRED_FIELDS = (
    "name", "email", "dob", "tob", "pob", "latitude", "longitude",
)
LOVE_PREMIUM_PARTNER_REQUIRED_FIELDS = (
    "name", "dob", "tob", "pob", "latitude", "longitude",
)


def _has_value(value: Any) -> bool:
    """True unless `value` is None or an empty/whitespace-only string --
    NEVER treats a legitimate falsy-but-real value (e.g. latitude=0 at
    the equator, longitude=0 at the prime meridian, both real, valid
    coordinates) as missing. A naive `if not value` would incorrectly
    reject exactly those two real cases."""
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _missing_fields(payload: Dict[str, Any], required_fields) -> list:
    return [f for f in required_fields if not _has_value(payload.get(f) if isinstance(payload, dict) else None)]


def _validate_dob(value: Any, field: str) -> None:
    """Require a real YYYY-MM-DD calendar date; preserve the original string."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise OrderValidationError(f"{field} must be a valid YYYY-MM-DD calendar date.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise OrderValidationError(f"{field} must be a valid YYYY-MM-DD calendar date.") from exc


@dataclass
class CreatedReportOrder:
    order_id: int
    status: str
    report_stage: str
    dispatched: bool
    task_id: Optional[str] = None  # populated only in Celery (USE_CELERY=True) mode


class OrderService:
    # -------------------------------------------------------------
    # Paid Report Platform v1.0 -- R3 (Pre-Payment Order Service).
    # create_pending_order() and mark_paid_and_dispatch() below are
    # NEW and are not called from anywhere yet (no route, no
    # PaymentService wiring) -- create_paid_report_order() and
    # redispatch_report_generation() further down are the EXISTING,
    # completely unmodified, still-live methods every real payment
    # goes through today.
    # -------------------------------------------------------------
    def create_pending_order(self, payload: Dict[str, Any]) -> Order:
        """
        Paid Report Platform v1.0 -- R3. Persists a COMPLETE report
        Order BEFORE any payment is attempted (the future R6 caller:
        the order-creation route, before it ever calls Razorpay).

        Non-negotiable rule this method exists to enforce: no
        incomplete paid-report Order may be created. Every required
        input for the resolved product's own generator is validated
        BEFORE this method ever calls db.session.add() -- a rejection
        (OrderValidationError) therefore never leaves a partial row
        and never requires a rollback, since nothing was ever staged
        in the session in the first place.

        report_slug is resolved through the ReportProduct registry
        (R2) -- an unknown or inactive product is rejected before any
        other validation runs. The value ultimately written to
        Order.product is ALWAYS the registry's own canonical
        report_slug (normalized: stripped + lowercased, the exact same
        normalization app.py::create_razorpay_order() already applies
        to a product slug today) -- never whatever raw casing/
        whitespace the caller happened to send, and never something a
        later step (payment data, a retry, anything else) can change
        after this call returns.

        Required fields are validated directly against the two real,
        already-proven sets this module now documents (STANDARD_
        REQUIRED_FIELDS / LOVE_PREMIUM_PRIMARY_REQUIRED_FIELDS /
        LOVE_PREMIUM_PARTNER_REQUIRED_FIELDS) -- selected by the
        resolved product's own `generator` column, never by re-deriving
        or guessing from the payload itself. This deliberately does
        NOT read/enforce ReportProduct.required_input_schema (still
        NULL for every product as of R2) -- direct validation against
        proven existing requirements is what this phase asks for; a
        schema-driven version is a future phase, once that column has
        a real, defined format.

        No field is normalized beyond the report_slug lookup itself --
        name/email/phone/dob/tob/pob/latitude/longitude/partner are
        persisted exactly as received, matching create_paid_report_
        order()'s own existing, unmodified behavior (verbatim storage,
        no reformatting) -- DOB/TOB/POB semantics are never altered.

        Raises OrderValidationError (never creates a row) for: a
        missing report_slug/product, an unknown product, an inactive
        product, or any missing required field for that product's
        generator.
        """
        raw_slug = payload.get("report_slug") or payload.get("product")
        if not _has_value(raw_slug) or not isinstance(raw_slug, str):
            raise OrderValidationError("report_slug (or product) is required.")
        report_slug = raw_slug.strip().lower()
        if not report_slug:
            raise OrderValidationError("report_slug (or product) is required.")

        product = ReportProduct.query.get(report_slug)
        if product is None:
            raise OrderValidationError(f"Unknown report product: {report_slug!r}")
        if not product.active:
            raise OrderValidationError(f"Report product is not currently available: {report_slug!r}")

        partner_payload: Optional[Dict[str, Any]] = None

        if product.generator == LOVE_PREMIUM_GENERATOR:
            missing = _missing_fields(payload, LOVE_PREMIUM_PRIMARY_REQUIRED_FIELDS)
            if missing:
                raise OrderValidationError(f"Missing required field(s): {', '.join(missing)}")
            _validate_dob(payload.get("dob"), "dob")

            partner_payload = payload.get("partner")
            if not isinstance(partner_payload, dict) or not partner_payload:
                raise OrderValidationError("partner details are required for this report.")
            partner_missing = _missing_fields(partner_payload, LOVE_PREMIUM_PARTNER_REQUIRED_FIELDS)
            if partner_missing:
                raise OrderValidationError(
                    f"Missing required partner field(s): {', '.join('partner.' + f for f in partner_missing)}"
                )
            _validate_dob(partner_payload.get("dob"), "partner.dob")
        else:
            missing = _missing_fields(payload, STANDARD_REQUIRED_FIELDS)
            if missing:
                raise OrderValidationError(f"Missing required field(s): {', '.join(missing)}")
            _validate_dob(payload.get("dob"), "dob")
            # Not required for a standard report, but stored verbatim
            # if a caller happens to send one -- never invented, never
            # rejected either way. Matches create_paid_report_order()'s
            # own existing partner_payload handling exactly.
            candidate_partner = payload.get("partner")
            if isinstance(candidate_partner, dict):
                partner_payload = candidate_partner
                if "dob" in partner_payload:
                    _validate_dob(partner_payload.get("dob"), "partner.dob")

        order = Order(
            name=payload.get("name"),
            email=payload.get("email"),
            phone=payload.get("phone"),
            product=report_slug,
            dob=payload.get("dob"),
            tob=payload.get("tob"),
            pob=payload.get("pob"),
            language=payload.get("language", "en"),
            status="PENDING",
            payment_status="CREATED",
            report_stage="Pending",
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            partner_payload=partner_payload,
            # Paid Report Platform v1.0 -- R4. Immutable price snapshot,
            # in paise, from the registry's OWN rupee price at the
            # moment this Order is created -- never recomputed or
            # trusted from any later payment payload. See models.py's
            # own column docstring / migration 0518660f81fc.
            amount_paise=product.price * 100,
        )
        db.session.add(order)
        db.session.commit()
        return order

    def mark_paid_and_dispatch(self, order_id: int):
        """
        FUTURE BOUNDARY -- Paid Report Platform v1.0 R4 (Payment
        Finalization Service). Deliberately NOT implemented in R3.

        This method name/signature is reserved so R4 has a stable,
        already-agreed place to put "flip an existing pending Order to
        PAID and dispatch generation exactly once" -- but its actual
        body requires the atomic conditional-UPDATE semantics
        (PAYMENT_PENDING -> PAID, then Pending -> Queued, each its own
        compare-and-swap) that R4's own payment-finalization design
        owns. Implementing it now would mean guessing that design
        rather than being told it -- R3's own instructions are
        explicit that this must not happen.

        Raises NotImplementedError unconditionally. Not called from
        anywhere in R3 (no route, no PaymentService wiring) -- this
        method existing does not change any current live payment
        behavior in any way.
        """
        raise NotImplementedError(
            "OrderService.mark_paid_and_dispatch() is a reserved R4 (Payment "
            "Finalization) boundary -- not implemented until that phase."
        )

    def create_paid_report_order(self, order_payload: Dict[str, Any]) -> CreatedReportOrder:
        """
        order_payload carries exactly the fields app.py's /webhook
        already reads from the client today. Required: name, email,
        product -- the same requirement app.py enforces before this
        point would be reached.
        """
        name = order_payload.get("name")
        email = order_payload.get("email")
        product = order_payload.get("product")

        if not all([name, email, product]):
            raise ValueError("name, email, and product are required to create a report order.")

        _validate_dob(order_payload.get("dob"), "dob")
        partner = order_payload.get("partner")
        if product == LOVE_PREMIUM_PRODUCT_SLUG:
            if not isinstance(partner, dict):
                raise OrderValidationError("partner details are required for this report.")
            _validate_dob(partner.get("dob"), "partner.dob")
        elif isinstance(partner, dict) and "dob" in partner:
            _validate_dob(partner.get("dob"), "partner.dob")

        order = Order(
            name=name,
            email=email,
            phone=order_payload.get("phone"),
            product=product,
            dob=order_payload.get("dob"),
            tob=order_payload.get("tob"),
            pob=order_payload.get("pob"),
            language=order_payload.get("language", "en"),
            status="PAID",
            latitude=order_payload.get("latitude"),
            longitude=order_payload.get("longitude"),
            partner_payload=order_payload.get("partner"),
        )
        db.session.add(order)
        db.session.commit()

        try:
            task_id = self._dispatch_report_generation(order.id)
        except Exception as exc:
            raise ReportDispatchError(order.id, exc) from exc

        return CreatedReportOrder(
            order_id=order.id,
            status=order.status,
            report_stage=order.report_stage,
            dispatched=True,
            task_id=task_id,
        )

    def redispatch_report_generation(self, order_id: int) -> CreatedReportOrder:
        """
        Re-trigger report generation for an EXISTING, already-paid
        Order -- used only for safe retries (Payment Hardening Phase
        5). Never creates a new Order and never touches payment
        verification; callers (PaymentService) are responsible for
        only invoking this when the payment was already verified and
        this exact order_id was already created by a prior call to
        create_paid_report_order().
        """
        order = Order.query.get(order_id)
        if order is None:
            raise ValueError(f"No Order found with id={order_id}")

        task_id = self._dispatch_report_generation(order_id)

        return CreatedReportOrder(
            order_id=order.id,
            status=order.status,
            report_stage=order.report_stage,
            dispatched=True,
            task_id=task_id,
        )

    def _dispatch_report_generation(self, order_id: int) -> Optional[str]:
        from app_config import USE_CELERY
        from tasks import generate_and_send_report

        if USE_CELERY:
            task = generate_and_send_report.delay(order_id)
            return task.id
        else:
            threading.Thread(
                target=generate_and_send_report, args=(order_id,), daemon=True,
            ).start()
            return None
