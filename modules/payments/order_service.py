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
from dataclasses import dataclass
from typing import Any, Dict, Optional

from extensions import db
from models import Order


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


@dataclass
class CreatedReportOrder:
    order_id: int
    status: str
    report_stage: str
    dispatched: bool
    task_id: Optional[str] = None  # populated only in Celery (USE_CELERY=True) mode


class OrderService:
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
