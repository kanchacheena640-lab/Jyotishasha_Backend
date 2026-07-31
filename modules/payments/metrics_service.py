# modules/payments/metrics_service.py

"""
MetricsService -- backend observability for the payment/report
lifecycle (Payment Hardening Phase 8). Read-only: every method here
issues plain SQL COUNT/MIN/ORDER-BY queries against the two tables
this whole engagement already established --
modules/models_processed_payments.py::ProcessedPayment and
models.py::Order -- and computes nothing that requires a background
job, a cache, or a new column. Nothing here is invoked anywhere else
in the codebase; it exists purely to be read by the two new
/admin/api/metrics/* routes (routes/routes_metrics.py) or a future
operator running it directly in a shell.

Why some MINIMUM METRICS come back as None, not a number
----------------------------------------------------------
This system was deliberately built (Phases 3-6) so that a duplicate
submission, a rejected retry, or a resume decision leaves no new
database row -- that is the entire point of idempotency: absorbing a
duplicate must be indistinguishable, in stored state, from it never
having arrived. The *decision* (duplicate / resume / reject) is
recorded only as a structured log line via
modules/payments/payment_logger.py (stdout JSON), which is explicitly
not "database state." Since this phase must compute metrics from
existing database state, must not change the schema, and must not
modify PaymentService (the only place that ever makes these
decisions) to start persisting a counter, three related facts follow
directly from those constraints, not from any oversight:

    - Payments.duplicate_payment_attempts: a duplicate attempt is, by
      design, absorbed without writing anything -- there is no row to
      count. None here, not 0 -- 0 would falsely claim "we counted and
      found zero," when the true answer is "this system does not
      persist that count."
    - Retries.resume_attempts / successful_resumes / rejected_resumes:
      same root cause. A resumed-then-Ready Order is stored identically
      to a first-attempt-then-Ready Order; there is no way to tell them
      apart from current row state alone, so no proxy is invented here.
    - General.average_report_generation_seconds: Order has created_at
      but no completed_at/updated_at column (unchanged in this phase --
      adding one would be a schema change). Duration from "Pending" to
      "Ready" cannot be computed without a second timestamp that does
      not exist.

Every one of these is surfaced as an explicit MetricsLimitation entry
in PaymentSystemMetricsSnapshot.limitations, naming the field and the
reason, rather than silently returning a number that looks
authoritative but isn't.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from extensions import db
from models import Order
from modules.models_processed_payments import ProcessedPayment
from modules.payments.metrics_models import (
    GeneralMetrics,
    MetricsLimitation,
    PaymentMetrics,
    PaymentSystemMetricsSnapshot,
    ReportMetrics,
    RetryMetrics,
)

_KNOWN_REPORT_STAGES = ("Pending", "Processing", "Ready", "Failed")


class MetricsService:
    def payments_metrics(self) -> PaymentMetrics:
        total = ProcessedPayment.query.count()
        # Deliberately NOT `.filter(response_payload.isnot(None))`: the
        # JSON column type defaults to none_as_null=False, so a claim
        # row that ever had response_payload explicitly assigned None
        # (rather than simply left unset) is stored as a JSON `null`
        # literal, not SQL NULL -- `IS NOT NULL` would then wrongly
        # count it as finalized/successful. Checking truthiness in
        # Python after fetching just this one column is correct
        # regardless of which of the two ways "empty" ended up stored.
        successful = sum(
            1 for (payload,) in db.session.query(ProcessedPayment.response_payload).all()
            if payload
        )
        return PaymentMetrics(
            total_payments=total,
            successful_payments=successful,
            failed_payments=total - successful,
            duplicate_payment_attempts=None,
        )

    def report_metrics(self) -> ReportMetrics:
        total = Order.query.count()
        pending = Order.query.filter_by(report_stage="Pending").count()
        processing = Order.query.filter_by(report_stage="Processing").count()
        ready = Order.query.filter_by(report_stage="Ready").count()
        failed = Order.query.filter_by(report_stage="Failed").count()
        other = total - (pending + processing + ready + failed)
        return ReportMetrics(
            pending=pending, processing=processing, ready=ready,
            failed=failed, other=other, total=total,
        )

    def retry_metrics(self) -> RetryMetrics:
        return RetryMetrics(
            resume_attempts=None,
            successful_resumes=None,
            rejected_resumes=None,
        )

    def general_metrics(self) -> GeneralMetrics:
        oldest_processing = (
            Order.query.filter_by(report_stage="Processing")
            .order_by(Order.created_at.asc())
            .first()
        )
        oldest_id = None
        oldest_age_seconds = None
        if oldest_processing is not None and oldest_processing.created_at is not None:
            oldest_id = oldest_processing.id
            created_at = oldest_processing.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            oldest_age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()

        return GeneralMetrics(
            average_report_generation_seconds=None,
            oldest_processing_order_id=oldest_id,
            oldest_processing_age_seconds=oldest_age_seconds,
        )

    def full_snapshot(self) -> PaymentSystemMetricsSnapshot:
        return PaymentSystemMetricsSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat(),
            payments=self.payments_metrics(),
            reports=self.report_metrics(),
            retries=self.retry_metrics(),
            general=self.general_metrics(),
            limitations=self._limitations(),
        )

    def _limitations(self) -> List[MetricsLimitation]:
        return [
            MetricsLimitation(
                metric="payments.duplicate_payment_attempts",
                reason=(
                    "Duplicate submissions are idempotently absorbed (Payment "
                    "Hardening Phase 3) without writing any new row -- there is "
                    "nothing in the database to count. Recorded only as a "
                    "structured log event (duplicate_payment_in_progress / "
                    "retry_rejected), not as DB state."
                ),
            ),
            MetricsLimitation(
                metric="retries.resume_attempts",
                reason=(
                    "Retry decisions (IGNORE/RESUME/REJECT) are computed live by "
                    "PaymentService._decide_retry() and never persisted -- a "
                    "resumed Order looks identical, in stored state, to one that "
                    "succeeded on the first attempt. Recorded only as structured "
                    "log events (retry_resuming_pipeline / retry_resumed / "
                    "retry_rejected), not as DB state."
                ),
            ),
            MetricsLimitation(
                metric="retries.successful_resumes",
                reason="Same root cause as retries.resume_attempts -- see that entry.",
            ),
            MetricsLimitation(
                metric="retries.rejected_resumes",
                reason="Same root cause as retries.resume_attempts -- see that entry.",
            ),
            MetricsLimitation(
                metric="general.average_report_generation_seconds",
                reason=(
                    "Order has created_at but no completed_at/updated_at column, "
                    "and adding one would be a schema change (out of scope this "
                    "phase) -- so the duration from Pending to Ready cannot be "
                    "computed for any Order, historical or current."
                ),
            ),
        ]
