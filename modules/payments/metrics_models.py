# modules/payments/metrics_models.py

"""
Plain dataclasses for the Metrics & Monitoring Foundation (Payment
Hardening Phase 8). Same role as payment_models.py /
reconciliation_models.py: shape only, no computation here.

Every numeric field that genuinely cannot be computed from current
database state is `None`, never a fabricated placeholder -- see
MetricsLimitation and metrics_service.py's module docstring for
exactly which fields this applies to and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PaymentMetrics:
    total_payments: int
    successful_payments: int
    failed_payments: int
    duplicate_payment_attempts: Optional[int]  # None: see MetricsLimitation


@dataclass
class ReportMetrics:
    pending: int
    processing: int
    ready: int
    failed: int
    other: int   # report_stage missing/NULL or an unrecognized legacy value
    total: int


@dataclass
class RetryMetrics:
    resume_attempts: Optional[int]      # None: see MetricsLimitation
    successful_resumes: Optional[int]   # None: see MetricsLimitation
    rejected_resumes: Optional[int]     # None: see MetricsLimitation


@dataclass
class GeneralMetrics:
    average_report_generation_seconds: Optional[float]  # None: see MetricsLimitation
    oldest_processing_order_id: Optional[int]
    oldest_processing_age_seconds: Optional[float]


@dataclass
class MetricsLimitation:
    """Explains, for one metric, exactly why it is None rather than a
    number -- so a caller never has to guess whether `null` means
    "zero" or "we can't tell"."""
    metric: str
    reason: str


@dataclass
class PaymentSystemMetricsSnapshot:
    generated_at: str  # ISO-8601 UTC timestamp of when this snapshot was computed
    payments: PaymentMetrics
    reports: ReportMetrics
    retries: RetryMetrics
    general: GeneralMetrics
    limitations: List[MetricsLimitation] = field(default_factory=list)
