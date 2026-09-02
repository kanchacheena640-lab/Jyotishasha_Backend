# modules/activity_events/analytics_repository.py

"""
Phase 6B.2 -- the pure PostgreSQL/SQLAlchemy read layer over
activity_events. QUERY MECHANICS ONLY: this file knows how to count,
distinct-count, group, and filter -- it does not know what "DAU" or
"Ask Now delivery rate" mean. That composition belongs to the future
modules/activity_events/analytics_service.py (Phase 6B.3), which will
call these primitives and shape their results into the frozen
analytics_models.py dataclasses using analytics_contract.py's rules
(compute_rate, active_user_window, etc.). Nothing here imports or
constructs an analytics_models.py dataclass.

Read-only by construction: every method below issues a plain
`db.session.query(...)` SELECT and returns a Python int/dict -- never
`.add()`, `.commit()`, `.update()`, or `.delete()`. Same convention
modules/payments/metrics_service.py already uses for its own read-only
observability queries (ProcessedPayment.query.count(), etc.) -- no
independent analytics session/transaction is introduced.

Environment is a REQUIRED keyword argument on every method, with no
default -- forgetting to pass it is a TypeError, not a silent
production/local mix. The real Phase 6B.3 AnalyticsService will always
pass environment=AnalyticsService.ENVIRONMENT ("production"); this
file's OWN tests pass environment="local" so they can safely exercise
real queries against jyotishasha_local. Hard-coding "production" HERE
would make local repository testing impossible -- that hard-coding
belongs to the service layer, per Phase 6B.2's own task boundary.

occurred_at (never recorded_at) drives every window filter, using a
half-open interval [start, end) -- `occurred_at >= start AND
occurred_at < end`, never BETWEEN (which is inclusive on both ends and
would double-count a row landing exactly on a shared boundary between
two adjacent windows).

JSONB dimension access follows this codebase's own existing convention
(modules/alerts/persistence_repository.py::UserNotification.data[...]
.astext, modules/services/attention_policy.py's identical pattern) --
SQLAlchemy's `Column[key].astext`, never a raw/interpolated JSON path.
Only an explicit, closed allowlist of dimension names may be queried
(APPROVED_PROPERTY_DIMENSIONS / APPROVED_NOTIFICATION_CONTEXT_
DIMENSIONS) -- an unlisted key raises UnsupportedAnalyticsDimension
rather than silently building an arbitrary-key query. A row missing
the requested dimension is EXCLUDED from a grouped result, never
folded into a fabricated "unknown" bucket.

Report-product separation (Phase 6A/6B.1's frozen "AI Report Engine
vs. purchased report, never merged" rule) is enforced here using
fields VERIFIED against the real producers, not guessed:
  - modules/ai_report_engine/lifecycle_manager.py's own
    _emit_ai_report_event() sets entity_type="ai_report" on every
    report_generation_* row it emits (the subscription-gated engine).
  - tasks.py's _emit_report_event() AND modules/love/love_premium_
    task.py's _emit_report_event() (a second, independent Order-based
    pipeline -- confirmed by its own docstring, "plugs Love Premium
    into the EXISTING report pipeline," and its `from models import
    Order` -- NOT part of the AI Report Engine despite its "love"
    name) both set entity_type="order" on every report_generation_*
    row they emit -- the one-off Order-based purchased-report journey.
  entity_type therefore reliably separates these two products for
  report_generation_started/completed/failed; count_events()'s
  `entity_type` parameter is exactly this filter.
  - modules/payments/payment_models.py's PaymentPurpose.REPORT_
    PURCHASE ("REPORT_PURCHASE", confirmed distinct from
    PaymentPurpose.SUBSCRIPTION == "SUBSCRIPTION" and
    PAYMENT_PURPOSE_ASK_NOW_CHAT_PACK == "ASK_NOW_CHAT_PACK") is the
    `purpose` property already carried by payment_initiated/
    payment_verified/payment_failed/payment_duplicate_ignored --
    `purpose` is already an approved property dimension, so
    count_events(..., property_filters={"purpose": "REPORT_PURCHASE"})
    isolates the purchased-report payment stage with no new mechanism.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Union

from sqlalchemy import distinct, func

from extensions import db
from modules.activity_events.analytics_models import AnalyticsWindow
from modules.models_activity_events import ActivityEvent

EventNames = Union[str, Iterable[str]]


class UnsupportedAnalyticsDimension(ValueError):
    """Raised for any properties/notification_context/entity_type
    dimension outside this file's own explicit allowlists -- never
    silently ignored, never used to build an arbitrary-key query."""


# ---------------------------------------------------------------------
# Approved dimensions -- closed vocabularies only. Adding a new value
# here is itself a design-freeze-worthy change, same discipline
# CLIENT_INGESTIBLE_EVENTS (modules/activity_events/ingestion_policy.py)
# already follows for event ownership.
# ---------------------------------------------------------------------
APPROVED_PROPERTY_DIMENSIONS = frozenset({
    "cta_id", "screen_name", "feature_name", "report_type", "placement",
    "source", "category", "provider", "purpose",
})

APPROVED_NOTIFICATION_CONTEXT_DIMENSIONS = frozenset({
    "notification_id", "campaign_id", "slot",
})

# The exact entity_type vocabulary this column is documented to carry
# (modules/models_activity_events.py's own column comment) -- only
# "ai_report" and "order" are actually exercised by any Phase 6B.1
# frozen metric today, but the full documented set is accepted here so
# this filter isn't artificially narrower than the column's own
# contract.
ALLOWED_ENTITY_TYPES = frozenset({
    "order", "ai_report", "subscription_event", "chat_pack",
    "processed_payment", "notification",
})


def _normalize_event_names(event_names: Optional[EventNames]) -> Optional[list]:
    if event_names is None:
        return None
    if isinstance(event_names, str):
        return [event_names]
    return list(event_names)


class ActivityEventsAnalyticsRepository:
    """Query mechanics only -- see module docstring. Every method takes
    `window` (an already-validated AnalyticsWindow) and `environment`
    (required, no default) first, then the same optional `event_names`/
    `platform` shape throughout, so call sites read uniformly."""

    # -------------------------------------------------------------
    # Shared filter application -- every method below funnels through
    # this so the environment/window/platform/event_name/entity_type
    # rules can never diverge between methods.
    # -------------------------------------------------------------
    @staticmethod
    def _apply_common_filters(
        query,
        *,
        window: AnalyticsWindow,
        environment: str,
        event_names: Optional[EventNames] = None,
        platform: Optional[str] = None,
        entity_type: Optional[str] = None,
    ):
        query = query.filter(ActivityEvent.environment == environment)
        query = query.filter(
            ActivityEvent.occurred_at >= window.start,
            ActivityEvent.occurred_at < window.end,
        )
        if platform is not None:
            query = query.filter(ActivityEvent.platform == platform)
        names = _normalize_event_names(event_names)
        if names is not None:
            query = query.filter(ActivityEvent.event_name.in_(names))
        if entity_type is not None:
            if entity_type not in ALLOWED_ENTITY_TYPES:
                raise UnsupportedAnalyticsDimension(
                    f"Unknown entity_type: {entity_type!r}; must be one of "
                    f"{sorted(ALLOWED_ENTITY_TYPES)}"
                )
            query = query.filter(ActivityEvent.entity_type == entity_type)
        return query

    @staticmethod
    def _apply_property_filters(
        query, property_filters: Optional[Mapping[str, str]],
    ):
        if not property_filters:
            return query
        for key, value in property_filters.items():
            if key not in APPROVED_PROPERTY_DIMENSIONS:
                raise UnsupportedAnalyticsDimension(
                    f"Unknown property dimension: {key!r}; must be one of "
                    f"{sorted(APPROVED_PROPERTY_DIMENSIONS)}"
                )
            query = query.filter(ActivityEvent.properties[key].astext == value)
        return query

    # -------------------------------------------------------------
    # A. Total / filtered row count
    # -------------------------------------------------------------
    def count_events(
        self,
        *,
        window: AnalyticsWindow,
        environment: str,
        event_names: Optional[EventNames] = None,
        platform: Optional[str] = None,
        entity_type: Optional[str] = None,
        property_filters: Optional[Mapping[str, str]] = None,
    ) -> int:
        """Row count. `event_names=None` means "every event in the
        window" -- an explicit, documented behavior, not an accident of
        an unset filter. `property_filters` is an exact-match AND of
        `properties[key].astext == value` pairs over APPROVED_PROPERTY_
        DIMENSIONS only (e.g. {"cta_id": "report_catalog_buy_now"},
        {"purpose": "REPORT_PURCHASE"})."""
        query = db.session.query(func.count(ActivityEvent.event_id))
        query = self._apply_common_filters(
            query, window=window, environment=environment,
            event_names=event_names, platform=platform, entity_type=entity_type,
        )
        query = self._apply_property_filters(query, property_filters)
        return query.scalar() or 0

    # -------------------------------------------------------------
    # B. Distinct users -- firebase_uid ONLY, never profile_id.
    # -------------------------------------------------------------
    def count_distinct_users(
        self,
        *,
        window: AnalyticsWindow,
        environment: str,
        event_names: Optional[EventNames] = None,
        platform: Optional[str] = None,
    ) -> int:
        """COUNT(DISTINCT firebase_uid) among non-null firebase_uid
        rows. profile_id is never read here and never substitutes for
        a missing firebase_uid -- see module docstring / Phase 6A
        section F."""
        query = db.session.query(func.count(distinct(ActivityEvent.firebase_uid)))
        query = self._apply_common_filters(
            query, window=window, environment=environment,
            event_names=event_names, platform=platform,
        )
        query = query.filter(ActivityEvent.firebase_uid.isnot(None))
        return query.scalar() or 0

    # -------------------------------------------------------------
    # C. Distinct sessions -- app/process sessions, as recorded.
    # -------------------------------------------------------------
    def count_distinct_sessions(
        self,
        *,
        window: AnalyticsWindow,
        environment: str,
        event_names: Optional[EventNames] = None,
        platform: Optional[str] = None,
    ) -> int:
        """COUNT(DISTINCT session_id) among non-null session_id rows.
        No sessionization/time-gap logic -- this merely counts the
        already-recorded app/process session ids (Phase 6A section G)."""
        query = db.session.query(func.count(distinct(ActivityEvent.session_id)))
        query = self._apply_common_filters(
            query, window=window, environment=environment,
            event_names=event_names, platform=platform,
        )
        query = query.filter(ActivityEvent.session_id.isnot(None))
        return query.scalar() or 0

    # -------------------------------------------------------------
    # D. Group by an approved `properties` JSON dimension.
    # -------------------------------------------------------------
    def group_by_property(
        self,
        *,
        window: AnalyticsWindow,
        environment: str,
        event_names: EventNames,
        dimension: str,
        platform: Optional[str] = None,
    ) -> Dict[str, int]:
        """Row count grouped by `properties[dimension]`. A row where
        that key is missing/NULL is EXCLUDED, never folded into a fake
        "unknown" bucket. Result is a plain dict, built from a query
        explicitly ordered by the dimension value -- deterministic
        regardless of PostgreSQL's own physical row order."""
        if dimension not in APPROVED_PROPERTY_DIMENSIONS:
            raise UnsupportedAnalyticsDimension(
                f"Unknown property dimension: {dimension!r}; must be one of "
                f"{sorted(APPROVED_PROPERTY_DIMENSIONS)}"
            )
        value_expr = ActivityEvent.properties[dimension].astext
        query = db.session.query(value_expr, func.count(ActivityEvent.event_id))
        query = self._apply_common_filters(
            query, window=window, environment=environment,
            event_names=event_names, platform=platform,
        )
        query = query.filter(value_expr.isnot(None))
        query = query.group_by(value_expr).order_by(value_expr)
        return {value: count for value, count in query.all()}

    # -------------------------------------------------------------
    # E. Group by an approved `notification_context` dimension.
    # -------------------------------------------------------------
    def group_by_notification_context(
        self,
        *,
        window: AnalyticsWindow,
        environment: str,
        event_names: EventNames,
        dimension: str,
        platform: Optional[str] = None,
    ) -> Dict[str, int]:
        """Same shape as group_by_property(), reading from
        notification_context instead of properties -- a SEPARATE
        allowlist (APPROVED_NOTIFICATION_CONTEXT_DIMENSIONS), since the
        two JSONB columns hold different, non-interchangeable
        vocabularies (Phase 6A section 16)."""
        if dimension not in APPROVED_NOTIFICATION_CONTEXT_DIMENSIONS:
            raise UnsupportedAnalyticsDimension(
                f"Unknown notification_context dimension: {dimension!r}; must "
                f"be one of {sorted(APPROVED_NOTIFICATION_CONTEXT_DIMENSIONS)}"
            )
        value_expr = ActivityEvent.notification_context[dimension].astext
        query = db.session.query(value_expr, func.count(ActivityEvent.event_id))
        query = self._apply_common_filters(
            query, window=window, environment=environment,
            event_names=event_names, platform=platform,
        )
        query = query.filter(value_expr.isnot(None))
        query = query.group_by(value_expr).order_by(value_expr)
        return {value: count for value, count in query.all()}
