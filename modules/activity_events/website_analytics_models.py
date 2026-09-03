# modules/activity_events/website_analytics_models.py

"""
Task 11 -- pure result shapes for the Website Analytics query/service
layer. Same role as modules/activity_events/analytics_models.py (Phase
6B.1): shape only, no computation, no database access. Kept as its own
small file rather than folded into website_analytics_service.py,
matching this codebase's own established models/service split
(analytics_models.py vs analytics_service.py; modules/payments/
metrics_models.py vs metrics_service.py).

Every shape below is a RESULT the future modules/activity_events/
website_analytics_service.py populates from real repository
aggregation -- nothing here queries ActivityEvent, and nothing here
invents its own quality-status vocabulary: `quality_status` values are
always one of website_metrics_contract.py's frozen READY/PARTIAL/
BLOCKED/GA4_EXTERNAL constants, never redefined here.

Frozen shape decisions (Task 11):
  - UnavailableMetric is the ONE representation for a metric whose
    frozen contract status is BLOCKED or GA4_EXTERNAL -- its own
    `value` is always None, never a fabricated 0 or a real query
    result (Task 11 S3/S27/S35: 0 means measured-and-empty; None means
    not connected/not computable -- the two must never be confused).
  - GroupedMetricResult / PageAttributionResult always carry an
    explicit `unknown_count`/`incomplete_count` INTEGER alongside their
    groups -- a row missing the requested dimension is a counted,
    visible fact, never silently dropped and never merged into a
    dimension-value bucket that could collide with a real value.
  - AttributionCoverageResult.coverage_percent is Optional[float] and
    is None (never NaN/Infinity, never 0.0) whenever total_eligible is
    0 -- the same zero-denominator rule analytics_contract.compute_rate()
    already freezes, reused here rather than re-invented.
  - No shape below ever carries firebase_uid/profile_id/anonymous_id/
    session_id, raw `properties`, or raw `campaign_context` (Task 11
    S30/S31) -- only the specific, already-approved dimension values a
    repository method itself returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class MetricValue:
    """A single scalar metric (e.g. cta_clicks_total). `value` is a
    real, non-negative int when quality_status permits execution --
    including a real, meaningful 0 (measured, no matching events).
    Never populated at all for an UnavailableMetric; use that shape
    instead for BLOCKED/GA4_EXTERNAL metrics."""

    metric_id: str
    quality_status: str
    value: int
    limitations: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GroupedMetricRow:
    dimension_value: str
    count: int


@dataclass(frozen=True)
class GroupedMetricResult:
    """A metric grouped by one dimension (e.g. cta_clicks_by_page).
    `rows` is already truncated/ordered by the repository (count DESC,
    dimension ASC) -- this shape never re-sorts or re-truncates.
    `unknown_count` is the count of otherwise-eligible rows missing the
    requested dimension value -- always present, never merged into
    `rows`, never confused with "direct" or with a real dimension
    value. `total` is the sum this metric's own denominator represents
    (== count of all eligible rows, known + unknown) so a caller never
    has to re-derive it by summing `rows` + `unknown_count` itself."""

    metric_id: str
    quality_status: str
    dimension: str
    rows: Tuple[GroupedMetricRow, ...]
    unknown_count: int
    total: int
    limitations: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PageAttributionRow:
    page_path: str
    dimension_value: str
    count: int


@dataclass(frozen=True)
class PageAttributionResult:
    """A Page x Attribution metric (e.g. cta_clicks_by_page_and_source).
    `rows` pair a known page_path with a known campaign dimension value
    -- both non-null by construction (Task 9A page_path AVAILABLE x
    Task 10 campaign PARTIAL coverage, combined within one row, never a
    cross-source join). `incomplete_count` is the count of otherwise-
    eligible rows missing EITHER value, a single combined bucket kept
    deliberately simple (Task 11's own repository-level design)."""

    metric_id: str
    quality_status: str
    property_dimension: str
    campaign_dimension: str
    rows: Tuple[PageAttributionRow, ...]
    incomplete_count: int
    total: int
    limitations: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AttributionCoverageResult:
    """Task 10's own frozen formula, with every raw value needed to
    audit the percentage. coverage_percent is None (never NaN/
    Infinity/0.0-by-accident) when total_eligible is 0 -- see
    analytics_contract.compute_rate(), reused by the service layer to
    compute this field, never re-implemented here."""

    metric_id: str
    quality_status: str
    total_eligible: int
    attributed: int
    unattributed: int
    coverage_percent: Optional[float]
    limitations: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UnavailableMetric:
    """The ONE representation for a metric whose frozen contract status
    is BLOCKED or GA4_EXTERNAL -- no repository query is ever executed
    to produce this shape. `value` is always None -- a dashboard/API
    consumer must render this as "unavailable"/"external", never as a
    literal 0 (Task 11 S3/S27/S35's own frozen distinction)."""

    metric_id: str
    quality_status: str
    value: None
    reason: str
