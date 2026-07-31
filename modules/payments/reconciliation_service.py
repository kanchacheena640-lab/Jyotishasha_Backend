# modules/payments/reconciliation_service.py

"""
ReconciliationService -- the backend foundation for safe MANUAL
recovery of stuck or failed report executions (Payment Hardening
Phase 7). This is not a new payment or pipeline mechanism: it is a
read-mostly wrapper around the exact same Order.report_stage lifecycle
that PaymentService's automatic retry path (Phase 5/6) already relies
on, exposed as its own entry point for a human (or a future admin
tool) to call directly -- e.g. for the edge cases automatic retry
cannot reach at all: an interrupted deployment, a worker crash, or an
infrastructure outage where no client ever resubmits the original
webhook to trigger PaymentService's own retry logic.

Two operations:
    inspect(order_id) -> ReconciliationDecision
        Purely read-only. Classifies one Order's report_stage into one
        of five actions (see reconciliation_models.ReconciliationAction).
        Safe to call any number of times; never mutates anything.

    resume(order_id) -> ReconciliationResumeResult
        Only actually resumes when inspect() says RESUME_ALLOWED.
        Never creates a new Order and never re-runs payment
        verification -- it calls OrderService.redispatch_report_
        generation(order_id), the exact same already-public method
        PaymentService's own RESUME path (Phase 5/6) calls, against
        the SAME existing Order row. "Existing payment" is reused
        implicitly: an Order only ever reaches "Failed" after a real
        payment was verified and claimed in Phase 3's ProcessedPayment
        ledger, and resume() never touches that ledger -- it only acts
        on the Order's report_stage.

Concurrency safety (reusing Payment Hardening Phase 6.2's proven
mechanism, not a new one): before dispatching, resume() performs the
identical atomic conditional UPDATE that
PaymentService._try_acquire_resume_ownership() uses --
`UPDATE orders SET report_stage='Processing' WHERE id=:id AND
report_stage='Failed'` -- so that two reconciliation calls for the
same order_id (or a reconciliation call racing an automatic webhook
retry) can never both dispatch. Exactly one caller's UPDATE matches a
row; every other caller is told the order is already running. This is
intentionally re-implemented here rather than imported from
PaymentService, so that this phase touches zero existing files
(payment_service.py included) -- it is the same one-line SQL idiom,
not a second, divergent mechanism.

Abandoned-Processing detection (Payment Hardening Blocker 02): the
Final Audit found that thread-mode dispatch (USE_CELERY=False, the
current deployment) has no liveness signal at all -- if the process
running a daemon thread crashes or is restarted mid-generation,
report_stage is left at "Processing" forever, and BOTH automatic
retry and this service's own resume() correctly refuse to touch a
"Processing" Order (to avoid resuming one that's genuinely still
running). That refusal is exactly right when the order really is
running, and exactly wrong when the process that was running it no
longer exists -- and nothing before this change could tell the two
apart.

Order.processing_started_at (set by tasks.py and love_premium_task.py
the moment report_stage becomes "Processing", and reset fresh by
_try_acquire_resume_ownership() on every resume) is the fix: a
"Processing" Order older than ABANDONED_PROCESSING_THRESHOLD_SECONDS
with no further update is presumed abandoned rather than running, and
inspect() reclassifies it as RESUME_ALLOWED instead of
ALREADY_RUNNING. resume()'s atomic ownership check is extended to
match on EITHER `report_stage='Failed'` OR (`report_stage='Processing'
AND processing_started_at` older than the threshold) -- still one
conditional UPDATE, still DB-enforced, still no Python lock, no
scheduler, no Celery, no Redis. Nothing sweeps for abandoned orders on
its own; an operator (or a future caller) must still explicitly call
resume() -- this only makes that call succeed instead of being
refused when the Order is genuinely stuck.

Progress heartbeat, not just a start time (Payment Hardening Blocker
02.1): the Blocker 02 validation review found a real gap -- writing
processing_started_at only ONCE, at the very start of Processing,
meant "20 minutes since the pipeline started" and "20 minutes since
the process died" looked identical, and the OpenAI SDK's own default
per-attempt timeout (600s) with up to 2 retries means a single,
perfectly healthy GPT call can legitimately take close to 30 minutes
before tasks.py/love_premium_task.py ever reach the next line. tasks.py
and love_premium_task.py now also write processing_started_at the
moment the GPT call returns -- the smallest addition that matters,
since GPT is the one stage whose own legitimate duration can approach
what used to be the abandonment threshold, and everything after it
(kundali drawing, PDF) is comparatively fast, local, CPU-bound work.
This is what "time since last progress" (not "time since pipeline
started") means in practice: a slow-but-alive GPT call that eventually
succeeds resets the clock the moment it does, so PDF generation always
gets its own fresh window rather than inheriting however long GPT
happened to take.

This does NOT make a heartbeat possible *during* the GPT call itself --
no Python code runs while that single synchronous call is blocked, with
or without a scheduler, so no write can happen mid-call. What actually
protects a legitimately slow-but-alive GPT call is
ABANDONED_PROCESSING_THRESHOLD_SECONDS itself now being set safely
above that call's own worst-case configured duration (~1800s: 3
attempts x 600s) rather than below it. The heartbeat's job is to make
sure that threshold, once safely sized for the riskiest single stage,
applies fully to every OTHER stage too, instead of that stage
inheriting whatever time was already spent earlier in the pipeline.

Honest limitation, unchanged in kind: this is still a time-based
heuristic, not true liveness detection (which would need a concurrently
running heartbeat thread or external infrastructure, both out of
scope). A single stage that is somehow slower than its own worst-case
bound (e.g. GPT hanging well past its own SDK timeout+retries, which
would itself be an OpenAI-side bug) could still be misclassified. Given
the stated constraints, this is the closest a checkpoint-based
heuristic can get without adding infrastructure -- and resume() still
requires an explicit, deliberate call; nothing auto-triggers it.

Deliberately NOT included here (out of scope per this phase's own
instructions): no Admin UI, no dashboard, no scheduler/cron sweep of
stuck orders, no change to any existing API contract, no change to
PaymentService's public interface, no change to the report pipeline
itself. This file is additive only.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from extensions import db
from models import Order
from modules.payments.order_service import OrderService
from modules.payments.reconciliation_models import (
    ReconciliationAction,
    ReconciliationDecision,
    ReconciliationResumeResult,
)


class ReconciliationService:
    # Payment Hardening Blocker 02 / 02.1: how long a "Processing" Order
    # can go without a fresh processing_started_at (start of Processing,
    # or the post-GPT heartbeat, or a resume) before it is presumed
    # abandoned rather than genuinely running. Set to safely exceed the
    # OpenAI SDK's own worst-case single-attempt duration for the GPT
    # stage (default read timeout 600s x up to 3 attempts = 1800s) --
    # the one stage whose legitimate duration can approach an
    # abandonment threshold on its own. See module docstring.
    ABANDONED_PROCESSING_THRESHOLD_SECONDS = 40 * 60

    def __init__(self, order_service: Optional[OrderService] = None):
        self._order_service = order_service or OrderService()

    def inspect(self, order_id: int) -> ReconciliationDecision:
        order = Order.query.get(order_id)
        if order is None:
            return ReconciliationDecision(
                order_id=order_id,
                report_stage=None,
                action=ReconciliationAction.INVALID_STATE,
                reason=f"No Order exists with id={order_id}.",
            )

        if order.report_stage == "Pending":
            return ReconciliationDecision(
                order_id=order_id,
                report_stage="Pending",
                action=ReconciliationAction.NO_ACTION,
                reason=(
                    "Payment was verified but report generation has not "
                    "been dispatched yet; this Order is not stuck, no "
                    "action needed."
                ),
            )

        if order.report_stage == "Processing":
            age = self._processing_age_seconds(order)
            if age is not None and age >= self.ABANDONED_PROCESSING_THRESHOLD_SECONDS:
                return ReconciliationDecision(
                    order_id=order_id,
                    report_stage="Processing",
                    action=ReconciliationAction.RESUME_ALLOWED,
                    reason=(
                        f"report_stage has been Processing for "
                        f"{int(age)}s with no update -- presumed "
                        f"abandoned (crashed or restarted process, "
                        f"thread mode has no other liveness signal) "
                        f"rather than genuinely running; safe to "
                        f"resume for the existing Order."
                    ),
                )
            return ReconciliationDecision(
                order_id=order_id,
                report_stage="Processing",
                action=ReconciliationAction.ALREADY_RUNNING,
                reason=(
                    "Report generation is currently in progress (or "
                    "began too recently to presume otherwise); resuming "
                    "now would risk a duplicate GPT call, PDF write, or "
                    "email send."
                ),
            )

        if order.report_stage == "Ready":
            return ReconciliationDecision(
                order_id=order_id,
                report_stage="Ready",
                action=ReconciliationAction.ALREADY_COMPLETED,
                reason="Report generation already finished successfully; nothing to reconcile.",
            )

        if order.report_stage == "Failed":
            return ReconciliationDecision(
                order_id=order_id,
                report_stage="Failed",
                action=ReconciliationAction.RESUME_ALLOWED,
                reason=(
                    "Payment was verified and an Order exists, but "
                    "report generation did not complete; safe to "
                    "resume for the existing Order."
                ),
            )

        return ReconciliationDecision(
            order_id=order_id,
            report_stage=order.report_stage,
            action=ReconciliationAction.INVALID_STATE,
            reason=(
                f"Unrecognized report_stage {order.report_stage!r}; "
                "refusing to guess a safe action."
            ),
        )

    def _processing_age_seconds(self, order: Order) -> Optional[float]:
        """
        None (rather than 0) whenever age genuinely can't be
        determined -- e.g. an Order left "Processing" by a version of
        the pipeline that predates processing_started_at. None is
        deliberately treated by inspect() as "not stale": a missing
        signal must never be interpreted as license to resume.
        """
        if order.processing_started_at is None:
            return None
        started = order.processing_started_at
        if started.tzinfo is not None:
            started = started.replace(tzinfo=None)
        return (datetime.utcnow() - started).total_seconds()

    def resume(self, order_id: int) -> ReconciliationResumeResult:
        decision = self.inspect(order_id)
        if decision.action != ReconciliationAction.RESUME_ALLOWED:
            return ReconciliationResumeResult(
                order_id=order_id, resumed=False, decision=decision,
            )

        if not self._try_acquire_resume_ownership(order_id):
            # Lost the race to a concurrent caller -- another
            # reconciliation request, or an automatic webhook retry,
            # already claimed this Order for resume a moment earlier.
            lost_decision = ReconciliationDecision(
                order_id=order_id,
                report_stage="Processing",
                action=ReconciliationAction.ALREADY_RUNNING,
                reason=(
                    "Another request already claimed this Order for "
                    "resume; it is now Processing."
                ),
            )
            return ReconciliationResumeResult(
                order_id=order_id, resumed=False, decision=lost_decision,
            )

        resumed_order = self._order_service.redispatch_report_generation(order_id)
        return ReconciliationResumeResult(
            order_id=order_id,
            resumed=True,
            decision=decision,
            task_id=resumed_order.task_id,
        )

    def _try_acquire_resume_ownership(self, order_id: int) -> bool:
        """
        Same atomic compare-and-swap idiom as
        PaymentService._try_acquire_resume_ownership() (Payment
        Hardening Phase 6.2) -- one conditional UPDATE, DB-enforced,
        no Python lock, no in-memory flag, safe across concurrent
        requests and worker processes. Extended for Blocker 02: the
        WHERE clause also matches a "Processing" Order whose
        processing_started_at is older than the abandonment threshold
        -- still a single atomic UPDATE, so two callers (or a caller
        racing the still-alive original attempt, however unlikely)
        can never both win it. processing_started_at is reset to now()
        on a successful claim, exactly like a fresh dispatch, so the
        newly-resumed attempt gets its own full abandonment window.
        """
        cutoff = datetime.utcnow() - timedelta(
            seconds=self.ABANDONED_PROCESSING_THRESHOLD_SECONDS
        )
        rows_updated = Order.query.filter(
            Order.id == order_id,
            db.or_(
                Order.report_stage == "Failed",
                db.and_(
                    Order.report_stage == "Processing",
                    Order.processing_started_at.isnot(None),
                    Order.processing_started_at < cutoff,
                ),
            ),
        ).update(
            {"report_stage": "Processing", "processing_started_at": datetime.utcnow()},
            synchronize_session=False,
        )
        db.session.commit()
        return rows_updated == 1
