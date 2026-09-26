# modules/payments/revenue_dashboard_service.py

"""
Reports Revenue Dashboard -- Phase 1 (backend query layer).

Every rule here is taken verbatim from the End-to-End Data Truth Audit;
nothing is substituted for convenience. See routes/routes_revenue.py for
the two routes that call this module.

PAID ORDER
    Order.status == "PAID" -- NOT Order.payment_status. Google Play/App
    orders reach status="PAID" directly at creation
    (OrderService.create_paid_report_order()) and NEVER get
    payment_status="PAID" (that column stays at its "CREATED" default
    forever for that path -- confirmed both by tracing
    modules/payments/payment_service.py::_apply_business_effect() /
    OrderService.create_paid_report_order(), and empirically in the
    local database: 5 real rows with status='PAID',
    payment_status='CREATED'). Using payment_status as the sole PAID
    criterion would silently drop every current App sale.

REVENUE
    Order.amount_paise / 100, for PAID rows only. A PAID row with
    amount_paise NULL or <= 0 is still counted in total_paid_orders, but
    contributes 0 to revenue and is counted separately in
    metadata.invalid_amount_orders -- never silently treated as a real
    ₹0 sale.

AVERAGE ORDER VALUE
    valid revenue / number of PAID orders with a valid (non-null,
    positive) amount_paise -- never divided by every PAID order (that
    would understate AOV whenever an invalid-amount row exists).

EMAILED (never "Delivered" -- the audit found the code only proves SMTP
acceptance, never inbox delivery or in-app viewing)
    Order.report_stage == "Ready" AND Order.email_status == "SENT".

PLATFORM
    ProcessedPayment.provider joined by ProcessedPayment.order_id ==
    Order.id: "RAZORPAY" -> web, "GOOGLE_PLAY" -> app, anything else or
    a missing row -> "unknown" (never defaulted to web or app).

REPORTING DATE
    COALESCE(ProcessedPayment.created_at, Order.created_at) --
    ProcessedPayment.created_at is written inside the SAME atomic
    finalize transaction as the PAID transition (Razorpay) or
    immediately before order creation (Google Play), so it is the
    closest available proxy to the real payment moment; Order.created_at
    is pre-payment for the web flow and is only ever used as a fallback,
    flagged via `reporting_date_approximate=True` on the affected rows.

TIMEZONE (see this module's own docstring section further down and the
returned report for the one assumption this cannot fully verify from
the repository alone).

JOIN SAFETY: ProcessedPayment(provider, payment_id) is DB-UNIQUE
(modules/models_processed_payments.py's own __table_args__), and this
module further restricts to `order_id IS NOT NULL`, then picks exactly
one authoritative ProcessedPayment row per Order (see
_authoritative_claim_subquery() below) so no Order can ever be counted,
revenue-summed, or listed more than once because of this join.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, or_

from extensions import db
from models import Order, OrderAttribution
from modules.models_processed_payments import ProcessedPayment
from modules.payments.report_product_registry import ReportProduct

# ---------------------------------------------------------------------
# Timezone handling
# ---------------------------------------------------------------------
#
# ONE ASSUMPTION THIS MODULE MAKES, STATED EXPLICITLY (per the audit's
# own instruction to never silently guess): ProcessedPayment.created_at
# is written with Python's datetime.utcnow() (modules/models_processed_
# payments.py, explicit, unambiguous naming) into a plain `db.DateTime`
# column (no `timezone=True` -- Postgres TIMESTAMP WITHOUT TIME ZONE,
# confirmed by inspecting the column definition), so this module treats
# every ProcessedPayment.created_at value as a naive UTC instant. This
# repository has no TZ override anywhere (render.yaml, no Dockerfile,
# no os.environ TZ reference found) and Render's own native Python
# runtime is documented to run in UTC by default -- but that platform
# fact is NOT something this repository's own files can prove on their
# own. If that assumption is ever wrong in production, every date-range
# boundary below would be off by whatever the container's real UTC
# offset is. This is flagged again in build_revenue_summary()'s /
# build_paid_orders_page()'s own return metadata.
#
# Order.created_at (the FALLBACK date, used only when no ProcessedPayment
# row exists) uses Python's datetime.now() -- server-local naive time,
# genuinely ambiguous per the audit (confirmed empirically: local dev
# machine shows an exact 19,800-second/5.5-hour skew against
# ProcessedPayment.created_at, matching IST-UTC). This module does NOT
# attempt to convert Order.created_at's own timezone -- it is compared
# using the SAME UTC-boundary arithmetic as ProcessedPayment.created_at
# (the only self-consistent choice without a second, unverifiable
# assumption), and every row using this fallback is marked
# reporting_date_approximate=True so the dashboard can display that
# honestly instead of asserting a precise date.
#
# The dashboard is India-facing, so calendar boundaries (Today/Last 7
# Days/This Month) are computed in Asia/Kolkata and converted to UTC
# instants for the SQL WHERE clause -- correct IF the UTC assumption
# above holds; this is the one thing a deploy-time check should confirm
# (e.g. `SELECT NOW(), current_setting('TIMEZONE')` on the production
# Postgres server, or checking Render's service environment for a TZ
# variable) before this dashboard's date filters are treated as exact.

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def kolkata_date_bounds_to_utc(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """[start_date 00:00:00 IST, end_date 23:59:59.999999 IST], both
    converted to naive UTC instants (tzinfo stripped after conversion,
    to compare directly against this schema's naive-UTC columns).
    end_date is inclusive."""
    start_ist = datetime.combine(start_date, datetime.min.time(), tzinfo=IST)
    end_ist = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=IST)
    start_utc = start_ist.astimezone(UTC).replace(tzinfo=None)
    end_utc = end_ist.astimezone(UTC).replace(tzinfo=None)
    return start_utc, end_utc


class InvalidRevenueFilter(ValueError):
    """Raised for a malformed platform/date filter. Route layer turns
    this into a 400, never a fabricated empty/zeroed report."""


PLATFORM_ALL = "all"
PLATFORM_WEB = "web"
PLATFORM_APP = "app"
VALID_PLATFORMS = (PLATFORM_ALL, PLATFORM_WEB, PLATFORM_APP)

PROVIDER_TO_PLATFORM = {"RAZORPAY": PLATFORM_WEB, "GOOGLE_PLAY": PLATFORM_APP}

SOURCE_GOOGLE_ADS = "google_ads"
SOURCE_META_ADS = "meta_ads"
SOURCE_ORGANIC_DIRECT = "organic_direct"
SOURCE_OTHER_UNKNOWN = "other_unknown"
ALL_SOURCES = (SOURCE_GOOGLE_ADS, SOURCE_META_ADS, SOURCE_ORGANIC_DIRECT, SOURCE_OTHER_UNKNOWN)

_GOOGLE_UTM_SOURCES = ("google", "googleads", "google_ads", "adwords")
_META_UTM_SOURCES = ("facebook", "instagram", "meta", "fb", "ig")
_PAID_UTM_MEDIA = ("cpc", "ppc", "paid", "paidsearch", "paid_search", "paidsocial", "paid_social", "display")


def parse_date_filters(start_raw: Optional[str], end_raw: Optional[str]) -> tuple[date, date]:
    """Both optional; default to a wide-open range (effectively "all
    time") only when NEITHER is given, exactly like the frozen
    AnalyticsWindow convention elsewhere in this codebase (routes/
    routes_analytics.py) -- a partially-given range is still a real
    request and is validated, never silently widened."""
    today = datetime.now(IST).date()
    if not start_raw and not end_raw:
        return date(2020, 1, 1), today
    if not start_raw or not end_raw:
        raise InvalidRevenueFilter("Both start and end are required together, or neither.")
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except ValueError:
        raise InvalidRevenueFilter("start/end must be YYYY-MM-DD.")
    if end_date < start_date:
        raise InvalidRevenueFilter("end must not be before start.")
    return start_date, end_date


def parse_platform_filter(raw: Optional[str]) -> str:
    value = (raw or PLATFORM_ALL).strip().lower()
    if value not in VALID_PLATFORMS:
        raise InvalidRevenueFilter(f"platform must be one of {VALID_PLATFORMS!r}.")
    return value


# ---------------------------------------------------------------------
# Shared query building
# ---------------------------------------------------------------------

def _authoritative_claim_join_condition(pp):
    """The join predicate that selects exactly one ProcessedPayment row
    per Order: pp.order_id == Order.id AND pp.id is the LOWEST id among
    every claim row sharing that same order_id (i.e. the first
    successful claim). A payment_id is claimed at most once per
    (provider, payment_id) by the DB's own UNIQUE constraint, and
    _resolve_existing_claim() in payment_finalization_service.py never
    creates a second row for an already-finalized Order, so in practice
    at most one row per order_id already exists -- this MIN(id)
    tie-break is a defensive backstop, not evidence a real duplicate has
    ever been observed, per the audit's own "verify cardinality" ask.
    Expressed as a correlated scalar subquery (never a second join),
    so this can never itself duplicate an Order row."""
    other = db.aliased(ProcessedPayment)
    lowest_id_for_this_order = (
        db.session.query(func.min(other.id))
        .filter(other.order_id == pp.order_id)
        .correlate(pp)
        .scalar_subquery()
    )
    return and_(pp.order_id == Order.id, pp.id == lowest_id_for_this_order)


def _platform_expr(provider_col):
    return case(
        (provider_col == "RAZORPAY", literal(PLATFORM_WEB)),
        (provider_col == "GOOGLE_PLAY", literal(PLATFORM_APP)),
        else_=literal("unknown"),
    )


def _source_expr(oa: OrderAttribution):
    """Mirrors the audit's own G rules exactly -- a click id always wins
    over UTM text; UTM alone requires BOTH a Google/Meta-identifying
    source AND a medium that clearly indicates paid traffic (never
    inferred from source text alone, which would misclassify organic
    Google/Facebook referrals as paid)."""
    utm_source_lc = func.lower(func.coalesce(oa.utm_source, literal("")))
    utm_medium_lc = func.lower(func.coalesce(oa.utm_medium, literal("")))
    google_click = or_(oa.gclid.isnot(None), oa.gbraid.isnot(None), oa.wbraid.isnot(None))
    meta_click = oa.fbclid.isnot(None)
    google_utm_paid = and_(utm_source_lc.in_(_GOOGLE_UTM_SOURCES), utm_medium_lc.in_(_PAID_UTM_MEDIA))
    meta_utm_paid = and_(utm_source_lc.in_(_META_UTM_SOURCES), utm_medium_lc.in_(_PAID_UTM_MEDIA))
    organic_direct = and_(
        oa.attribution_type == "none",
        oa.utm_source.is_(None), oa.utm_medium.is_(None), oa.utm_campaign.is_(None),
        oa.gclid.is_(None), oa.gbraid.is_(None), oa.wbraid.is_(None), oa.fbclid.is_(None),
    )
    return case(
        (oa.order_id.is_(None), literal(SOURCE_OTHER_UNKNOWN)),  # no OrderAttribution row at all
        (or_(google_click, google_utm_paid), literal(SOURCE_GOOGLE_ADS)),
        (or_(meta_click, meta_utm_paid), literal(SOURCE_META_ADS)),
        (organic_direct, literal(SOURCE_ORGANIC_DIRECT)),
        else_=literal(SOURCE_OTHER_UNKNOWN),  # ambiguous UTM-only / partial signal
    )


@dataclass
class _BaseQueryPieces:
    reporting_date: Any
    reporting_date_approximate: Any
    platform: Any
    source: Any
    amount_valid: Any
    valid_amount_paise: Any


def _paid_orders_base_query(platform_filter: str, start_date: date, end_date: date):
    """The ONE query both endpoints build on: every PAID Order, joined
    (LEFT, at most once each) to its authoritative ProcessedPayment claim
    and its OrderAttribution row. Filtering by platform/date happens on
    THIS query so summary and orders-list can never disagree about which
    rows are in scope."""
    pp = db.aliased(ProcessedPayment)

    reporting_date = func.coalesce(pp.created_at, Order.created_at)
    reporting_date_approximate = pp.id.is_(None)
    platform_expr = _platform_expr(pp.provider)
    source_expr = _source_expr(OrderAttribution)
    amount_valid = and_(Order.amount_paise.isnot(None), Order.amount_paise > 0)
    valid_amount_paise = case((amount_valid, Order.amount_paise), else_=literal(0))

    start_utc, end_utc = kolkata_date_bounds_to_utc(start_date, end_date)

    query = (
        db.session.query(
            Order, pp, OrderAttribution,
            reporting_date.label("reporting_date"),
            reporting_date_approximate.label("reporting_date_approximate"),
            platform_expr.label("platform"),
            source_expr.label("source"),
            amount_valid.label("amount_valid"),
            valid_amount_paise.label("valid_amount_paise"),
        )
        .select_from(Order)
        .outerjoin(pp, _authoritative_claim_join_condition(pp))
        .outerjoin(OrderAttribution, OrderAttribution.order_id == Order.id)
        .filter(Order.status == "PAID")
        .filter(reporting_date >= start_utc, reporting_date < end_utc)
    )
    if platform_filter == PLATFORM_WEB:
        query = query.filter(platform_expr == PLATFORM_WEB)
    elif platform_filter == PLATFORM_APP:
        query = query.filter(platform_expr == PLATFORM_APP)
    # PLATFORM_ALL: no extra filter -- web + app + unknown, per the contract.
    return query, _BaseQueryPieces(reporting_date, reporting_date_approximate, platform_expr, source_expr, amount_valid, valid_amount_paise)


def _delivery_status_label(report_stage: Optional[str], email_status: Optional[str]) -> str:
    stage = report_stage or "Pending"
    email = email_status or "NOT_ATTEMPTED"
    if stage == "Ready" and email == "SENT":
        return "Emailed"
    if stage == "Ready" and email == "FAILED":
        return "Ready / Email Failed"
    if stage == "Ready":
        return "Ready / Not Sent"
    return stage


def _report_name_map() -> Dict[str, str]:
    return {p.report_slug: p.name for p in ReportProduct.query.with_entities(ReportProduct.report_slug, ReportProduct.name).all()}


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def build_revenue_summary(platform_filter: str, start_date: date, end_date: date) -> Dict[str, Any]:
    query, pieces = _paid_orders_base_query(platform_filter, start_date, end_date)

    total_paid_orders = 0
    total_revenue_paise = 0
    invalid_amount_orders = 0
    unknown_platform_orders = 0
    approximate_date_orders = 0
    reports_emailed = 0
    by_source: Dict[str, Dict[str, int]] = {s: {"orders": 0, "revenue_paise": 0} for s in ALL_SOURCES}
    valid_amount_order_count = 0

    for order, pp, oa, reporting_date, is_approx, platform, source, amount_valid, valid_amount_paise in query:
        total_paid_orders += 1
        if amount_valid:
            total_revenue_paise += int(valid_amount_paise)
            valid_amount_order_count += 1
        else:
            invalid_amount_orders += 1
        if platform == "unknown":
            unknown_platform_orders += 1
        if is_approx:
            approximate_date_orders += 1
        if (order.report_stage or "") == "Ready" and (order.email_status or "") == "SENT":
            reports_emailed += 1
        bucket = by_source.setdefault(source, {"orders": 0, "revenue_paise": 0})
        bucket["orders"] += 1
        if amount_valid:
            bucket["revenue_paise"] += int(valid_amount_paise)

    avg_order_value_paise = (total_revenue_paise // valid_amount_order_count) if valid_amount_order_count else 0

    return {
        "filters": {"platform": platform_filter, "start": start_date.isoformat(), "end": end_date.isoformat()},
        "kpis": {
            "total_paid_orders": total_paid_orders,
            "total_revenue_paise": total_revenue_paise,
            "total_revenue": total_revenue_paise / 100,
            "reports_emailed": reports_emailed,
            "average_order_value_paise": avg_order_value_paise,
            "average_order_value": avg_order_value_paise / 100,
        },
        "sources": [
            {"source": s, "orders": by_source[s]["orders"], "revenue_paise": by_source[s]["revenue_paise"], "revenue": by_source[s]["revenue_paise"] / 100}
            for s in ALL_SOURCES
        ],
        "metadata": {
            "invalid_amount_orders": invalid_amount_orders,
            "unknown_platform_orders": unknown_platform_orders,
            "approximate_date_orders": approximate_date_orders,
            "reporting_date_source": "processed_payments.created_at, falling back to orders.created_at when no ProcessedPayment row exists",
            "timezone_assumption": (
                "Calendar boundaries computed in Asia/Kolkata and converted to UTC on the assumption that "
                "ProcessedPayment.created_at is a naive UTC instant (Python datetime.utcnow(), no DB timezone "
                "column, no TZ override found in this repository). Not independently verified against the "
                "production server clock -- see this module's own docstring."
            ),
            "delivered_terminology_note": "\"Emailed\" means the SMTP send succeeded (report_stage=Ready AND email_status=SENT) -- it does not prove inbox delivery.",
        },
    }


def build_paid_orders_page(platform_filter: str, start_date: date, end_date: date, page: int, per_page: int) -> Dict[str, Any]:
    query, pieces = _paid_orders_base_query(platform_filter, start_date, end_date)
    total = query.count()
    rows = (
        query.order_by(pieces.reporting_date.desc(), Order.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    names = _report_name_map()

    orders = []
    for order, pp, oa, reporting_date, is_approx, platform, source, amount_valid, valid_amount_paise in rows:
        orders.append({
            "order_id": order.id,
            "reporting_date": reporting_date.isoformat() if reporting_date else None,
            "reporting_date_approximate": bool(is_approx),
            "platform": platform,
            "report_slug": order.product,
            "report_name": names.get(order.product, order.product),
            "amount_paise": order.amount_paise,
            "amount": (order.amount_paise / 100) if order.amount_paise else None,
            "amount_valid": bool(amount_valid),
            "source": source,
            "report_stage": order.report_stage,
            "email_status": order.email_status,
            "delivery_status": _delivery_status_label(order.report_stage, order.email_status),
        })

    return {
        "filters": {"platform": platform_filter, "start": start_date.isoformat(), "end": end_date.isoformat(), "page": page, "per_page": per_page},
        "pagination": {"page": page, "per_page": per_page, "total": total, "total_pages": (total + per_page - 1) // per_page if per_page else 0},
        "orders": orders,
    }
