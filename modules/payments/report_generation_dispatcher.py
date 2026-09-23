# modules/payments/report_generation_dispatcher.py

"""
ReportGenerationDispatcher -- Paid Report Platform v1.0, R5 (Report
Generation Dispatcher).

NOT WIRED to anything yet: no route, no PaymentFinalizationService call
site, no app.py change invokes this in R5. PaymentFinalizationService
(R4) never calls it either -- R6 will orchestrate the two together.
tasks.py, modules/love/love_report_router.py, modules/love/
love_premium_task.py, and OrderService's existing methods are all
completely unmodified.

PURPOSE: the ONE place that decides, for an already-PAID Order, WHICH
existing generator to hand it to, and ensures that handoff happens at
most once per Order -- never WHAT that generator does internally (no
kundali/prompt/Luna/PDF/email logic lives here).

report_slug is read ONLY from Order.product (resolved by order_id,
which itself is trusted DB state, not client input) -- never from any
caller-supplied value, and never re-derived from a webhook/browser
payload. This is deliberate: after payment, the only trustworthy
report_slug is the one already persisted on the Order row by R3's
create_pending_order() at pre-payment time.

--------------------------------------------------------------------
EXISTING GENERATION ARCHITECTURE (inspected fresh for this phase,
verified again before writing any dispatch code -- not assumed):

    OrderService._dispatch_report_generation(order_id) [UNCHANGED]:
        from app_config import USE_CELERY
        from tasks import generate_and_send_report
        if USE_CELERY: generate_and_send_report.delay(order_id) -> task.id
        else: threading.Thread(target=generate_and_send_report,
                                args=(order_id,), daemon=True).start() -> None
    This is the ONLY function in this codebase that actually starts a
    Celery task or a background thread for report generation -- both
    create_paid_report_order() and redispatch_report_generation() call
    it, and it is COPIED (not imported/reused directly, to avoid a new
    coupling to OrderService's private method) verbatim below as
    _start_generation(), same two branches, same behavior.

    tasks.py::generate_and_send_report(order_id) is the ONE Celery task
    actually registered (`@celery.task(name="tasks.generate_and_send_report")`
    when USE_CELERY=True; a plain function calling
    _generate_and_send_report_core(order_id) directly otherwise --
    confirmed by reading tasks.py's own USE_CELERY branch again for
    this phase). modules/love/love_premium_task.py::
    generate_love_premium_report is NOT independently registered as a
    Celery task anywhere -- it is only ever reached SYNCHRONOUSLY,
    inside whatever thread/Celery-worker context is already running
    _generate_and_send_report_core(), via that function's own existing,
    unmodified internal check:

        product = order.get("product")
        if product == "relationship_future_report":
            return route_report_generation(order_id, product)  # -> generate_love_premium_report()
        # ... else the standard inline kundali/prompt/GPT/PDF/email
        #     pipeline runs directly, right here in tasks.py.

    ARCHITECTURAL CONSEQUENCE (verified, not assumed): because
    generate_love_premium_report is not its own Celery task, this
    dispatcher MUST NOT call it directly in Celery mode -- there is no
    registered task to .delay() it through, and calling the plain
    function directly would run full report generation (kundali, GPT,
    PDF, email) SYNCHRONOUSLY on whatever thread/request called this
    dispatcher, a genuine behavioral regression this phase must not
    introduce. The only mode-safe way to reach it, in EITHER Celery or
    thread mode, is exactly the SAME single entry point already proven
    live today: tasks.generate_and_send_report(order_id). Its own
    internal, unmodified product check is what actually routes a
    relationship_future_report Order to generate_love_premium_report --
    this dispatcher relies on that existing behavior rather than
    duplicating it.

    Consequently, KNOWN_GENERATORS below maps BOTH "standard_v1" and
    "love_premium_v1" to the SAME _start_generation() call. The
    registry lookup's real value here is not "selecting a different
    Python callable" (there is only one safe entry point today) but
    VALIDATING, from durable DB state, that the resolved product is
    active and its generator is one this dispatcher actually knows how
    to safely hand off -- a real safety check that did not exist at all
    before this phase (tasks.py's own bare string-equality check has no
    concept of "unknown" or "inactive").
--------------------------------------------------------------------

EXACTLY-ONCE BOUNDARY (Section I -- stated precisely, not oversold):
what this phase guarantees is exactly one successful DB-level ownership
transition, report_stage: Pending -> Queued, via one atomic conditional
UPDATE (`WHERE ... AND report_stage='Pending'`) -- the same proven
idiom PaymentService._try_acquire_resume_ownership() and
PaymentFinalizationService's own PAID transition (R4) already use. It
does NOT and cannot guarantee "the AI/report generation code itself
runs exactly once end-to-end across a process crash after the queue
handoff" -- once a Celery task is enqueued or a daemon thread is
started, this service has no further control over it. Generation code
remaining idempotency-aware/recoverable through report_stage (already
true: tasks.py sets Processing before real work, Ready/Failed after --
Payment Hardening Phase 6, unmodified) is what actually protects
against a crash mid-generation; this dispatcher's own guarantee ends at
a successful Pending->Queued transition.

DISPATCH-FAILURE LIMITATION (Section D -- reported, not solved by a
schema change): if the Pending->Queued UPDATE commits but the
subsequent Celery `.delay()`/`threading.Thread(...).start()` call
itself raises (broker down, thread creation failure), this dispatcher
flips report_stage straight to "Failed" -- reusing the EXISTING,
already-tested "Failed" vocabulary (PaymentService's own RESUME
decision path and ReconciliationService.resume() already treat
"Failed" as safely re-triggerable) rather than inventing a new column
or state. The explicit, accepted limitation: report_stage="Failed"
cannot currently distinguish "a dispatch call itself failed before any
generation work began" from "generation genuinely ran and failed" --
both look identical to every existing reader of this column. Adding
that distinction (e.g. a dedicated failure-reason column) is left as
future observability work, not attempted here per this phase's own
"do not invent a large schema redesign" instruction.

GENERATION RETRY RULE (unchanged from R4, restated here): a Failed
Order is NEVER automatically re-queued by this dispatcher. Recovery
from Failed is an explicit, separate, human/admin-triggered operation
(the existing PaymentService RESUME path or ReconciliationService.resume()),
never automatic here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from extensions import db
from models import Order
from modules.payments.report_product_registry import ReportProduct

# The exact, verified-live set of generator keys this dispatcher can
# safely hand off today (see module docstring for why both currently
# resolve to the SAME underlying call). A registry row with any other
# `generator` value is rejected as UNKNOWN_GENERATOR -- never guessed,
# never silently dispatched anyway.
#
# P0.3 -- "focused_v1" (54 SELF) / "focused_dual_v1" (9 DUAL) added.
# Both also resolve to the SAME _start_generation() call below: no new
# Celery task is registered for them, exactly the same reasoning as
# why "standard_v1"/"love_premium_v1" already share one entry point --
# tasks.py::_generate_and_send_report_core() is where the actual
# focused-vs-standard-vs-relationship branch happens (see that
# function's own P0.3 addition), not here. This dispatcher's job stays
# "validate the product is active and its generator is known," never
# "pick a different Python callable."
KNOWN_GENERATORS = frozenset({"standard_v1", "love_premium_v1", "focused_v1", "focused_dual_v1"})


class ReportGenerationDispatchStatus:
    """Typed outcome of ReportGenerationDispatcher.dispatch_if_pending()."""

    DISPATCHED = "DISPATCHED"                                   # won ownership, handoff call succeeded
    DISPATCH_FAILED = "DISPATCH_FAILED"                         # won ownership, but the Celery/thread call itself raised (report_stage forced to Failed -- see module docstring)

    ALREADY_QUEUED = "ALREADY_QUEUED"
    ALREADY_PROCESSING = "ALREADY_PROCESSING"
    ALREADY_READY = "ALREADY_READY"
    FAILED_REQUIRES_MANUAL_RETRY = "FAILED_REQUIRES_MANUAL_RETRY"  # report_stage already Failed -- never auto-requeued

    INVALID_STATE = "INVALID_STATE"           # payment_status/status not both PAID, or an unrecognized report_stage value
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    UNKNOWN_PRODUCT = "UNKNOWN_PRODUCT"       # Order.product has no matching ReportProduct row
    INACTIVE_PRODUCT = "INACTIVE_PRODUCT"
    UNKNOWN_GENERATOR = "UNKNOWN_GENERATOR"   # ReportProduct.generator not in KNOWN_GENERATORS


@dataclass
class ReportGenerationDispatchResult:
    status: str                     # ReportGenerationDispatchStatus
    order_id: Optional[int] = None
    task_id: Optional[str] = None   # populated only in Celery mode, only on DISPATCHED
    message: str = ""


class ReportGenerationDispatcher:
    def dispatch_if_pending(self, order_id: int) -> ReportGenerationDispatchResult:
        order = Order.query.get(order_id)
        if order is None:
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.ORDER_NOT_FOUND,
                message=f"No Order found with id={order_id}.",
            )

        # ---------------------------------------------------------
        # Registry validation -- static properties of the product,
        # independent of the Order's own current state, so checked
        # before any state-changing attempt (no race possible here).
        # report_slug comes ONLY from the already-persisted Order.product
        # -- never from any argument this method could otherwise accept.
        # ---------------------------------------------------------
        invalid = self._validate_product(order)
        if invalid is not None:
            return invalid

        # ---------------------------------------------------------
        # The one atomic ownership transition -- ALL preconditions
        # ---------------------------------------------------------
        rows_updated = Order.query.filter_by(
            id=order.id, payment_status="PAID", status="PAID", report_stage="Pending",
        ).update(
            {"report_stage": "Queued", "processing_started_at": datetime.utcnow()},
            synchronize_session=False,
        )
        db.session.commit()

        if rows_updated != 1:
            return self._classify_non_win(order.id)

        return self._handoff(order.id)

    def dispatch_claimed(self, order_id: int) -> ReportGenerationDispatchResult:
        """Dispatch an existing PAID Order already atomically claimed as Processing."""
        order = Order.query.get(order_id)
        if order is None:
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.ORDER_NOT_FOUND, order_id=order_id,
            )
        invalid = self._validate_product(order)
        if invalid is not None:
            self._mark_claim_failed(order_id)
            return invalid
        if order.payment_status != "PAID" or order.status != "PAID" or order.report_stage != "Processing":
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.INVALID_STATE, order_id=order_id,
                message="Claimed dispatch requires a PAID Order in Processing state.",
            )
        return self._handoff(order_id)

    def _validate_product(self, order: Order) -> Optional[ReportGenerationDispatchResult]:
        product = ReportProduct.query.get(order.product)
        if product is None:
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.UNKNOWN_PRODUCT, order_id=order.id,
                message=f"Order.product={order.product!r} has no matching ReportProduct.",
            )
        if not product.active:
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.INACTIVE_PRODUCT, order_id=order.id,
                message=f"Report product {order.product!r} is not currently active.",
            )
        if product.generator not in KNOWN_GENERATORS:
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.UNKNOWN_GENERATOR, order_id=order.id,
                message=f"Report product {order.product!r} has an unrecognized generator: {product.generator!r}.",
            )
        return None

    def _handoff(self, order_id: int) -> ReportGenerationDispatchResult:
        try:
            task_id = self._start_generation(order_id)
        except Exception as exc:
            # Section D -- do not leave report_stage stuck at Queued
            # with no signal. Reuses the EXISTING "Failed" vocabulary
            # (see module docstring's DISPATCH-FAILURE LIMITATION) --
            # never automatically re-queued by this dispatcher.
            Order.query.filter_by(id=order_id).update(
                {"report_stage": "Failed"}, synchronize_session=False,
            )
            db.session.commit()
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.DISPATCH_FAILED, order_id=order_id,
                message=f"Ownership was claimed but the dispatch call itself failed: {exc}",
            )

        return ReportGenerationDispatchResult(
            status=ReportGenerationDispatchStatus.DISPATCHED, order_id=order_id, task_id=task_id,
        )

    @staticmethod
    def _mark_claim_failed(order_id: int) -> None:
        Order.query.filter_by(id=order_id, report_stage="Processing").update(
            {"report_stage": "Failed"}, synchronize_session=False,
        )
        db.session.commit()

    # ------------------------------------------------------------
    def _classify_non_win(self, order_id: int) -> ReportGenerationDispatchResult:
        order = Order.query.get(order_id)
        if order is None:
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.ORDER_NOT_FOUND, order_id=order_id,
            )
        if order.payment_status != "PAID" or order.status != "PAID":
            return ReportGenerationDispatchResult(
                status=ReportGenerationDispatchStatus.INVALID_STATE, order_id=order_id,
                message=f"payment_status={order.payment_status!r}, status={order.status!r} -- not dispatchable.",
            )
        stage_map = {
            "Queued": ReportGenerationDispatchStatus.ALREADY_QUEUED,
            "Processing": ReportGenerationDispatchStatus.ALREADY_PROCESSING,
            "Ready": ReportGenerationDispatchStatus.ALREADY_READY,
            "Failed": ReportGenerationDispatchStatus.FAILED_REQUIRES_MANUAL_RETRY,
        }
        status = stage_map.get(order.report_stage, ReportGenerationDispatchStatus.INVALID_STATE)
        return ReportGenerationDispatchResult(
            status=status, order_id=order_id,
            message=f"report_stage={order.report_stage!r}.",
        )

    @staticmethod
    def _start_generation(order_id: int) -> Optional[str]:
        """Verbatim copy of OrderService._dispatch_report_generation()'s
        own two branches (not imported/called directly, to avoid a new
        coupling between this dispatcher and OrderService's private
        method) -- same functions, same Celery/thread behavior, same
        return shape. See module docstring for why both KNOWN_GENERATORS
        values reach this one call."""
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
