# modules/payments/purchase_measurement.py

"""
Reports Ads P0.2 -- the ONE canonical purchase measurement object.

The only financial authority is the backend-verified internal Order with
payment_status == "PAID". build_purchase_measurement() derives the object
ENTIRELY from trusted backend state (the Order row, the ReportProduct
registry, the focused-report question catalog / the original-report
category table below) -- never from anything the browser sent -- and
returns None for anything that is not a PAID web/Razorpay report purchase
of one of the four measured generators. POST /webhook attaches it to the responses that
already prove verification (status success / recovered_success /
already_processing / payment_confirmed_processing_delayed); nothing here
verifies, finalizes or changes a payment, and there is no second
verification path.

Returned fields (all non-PII; see ALLOWED_FIELDS):

    transaction_id   "ord_<Order.id>" -- stable, derived from the internal
                     Order, provider-neutral. Joins to orders.id and to
                     order_attributions.order_id (P0.1). The only thing it
                     reveals is a sequential order number to the buyer who
                     just paid for that very order.
    value            Order.amount_paise / 100 in major currency units
                     (Order.amount_paise is the immutable, registry-derived
                     snapshot taken at order creation -- never the current
                     registry price and never a browser value).
    currency         the registry product's currency, validated against
                     SUPPORTED_CURRENCIES (INR).
    item_id          Order.product (the canonical question_key).
    item_name        the registry product name (an English catalog title).
    item_category    the focused-report catalog category, or, for the original
                     25, the explicit ORIGINAL_REPORT_CATEGORIES entry.
    product_family   "focused_report" or "original_report".
    report_type      "self" (focused_v1), "dual" (focused_dual_v1),
                     "standard" (standard_v1) or "relationship"
                     (love_premium_v1).
    payment_provider "RAZORPAY".
    source_platform  "web".

Never included: name, email, phone, DOB/TOB/place, coordinates, partner
data, payment ids, click ids or UTM values.

SCOPE (P0.2A): all 88 paid web reports on Razorpay -- the 63 focused
reports (54 SELF / 9 DUAL) plus the original 25 (24 standard at 51,
relationship_future_report at 199). Google Play, Meta and server-side
reconciliation remain out of scope. Any other generator returns None.

build_purchase_measurement() NEVER raises: a measurement problem must
never affect the payment response it is attached to.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from extensions import db
from models import Order
from modules.intents.question_catalog import UnknownQuestionError, get_question
from modules.payments.report_product_registry import ReportProduct

_logger = logging.getLogger(__name__)

FOCUSED_FAMILY = "focused_report"
ORIGINAL_FAMILY = "original_report"

# generator -> (product_family, report_type). The ONLY places a purchase can
# be measured; anything else returns None.
MEASURED_GENERATORS = {
    "focused_v1": (FOCUSED_FAMILY, "self"),
    "focused_dual_v1": (FOCUSED_FAMILY, "dual"),
    "standard_v1": (ORIGINAL_FAMILY, "standard"),
    "love_premium_v1": (ORIGINAL_FAMILY, "relationship"),
}

# Explicit trusted item_category for EVERY original product (the 24 standard
# reports and relationship_future_report). It mirrors the category shown in the
# frontend catalog (app/data/reportsData.ts category.en, lower-cased) so the
# browser funnel events and the backend purchase carry the same value.
# test_reports_ads_p02a_original_reports_measurement.py requires these keys to
# equal EXACTLY the original registry products -- adding a product to the
# registry without adding it here fails that test.
ORIGINAL_REPORT_CATEGORIES = {
    "sadhesati_report": "transit",
    "jupiter_transit_report": "transit",
    "saturn_transit_report": "transit",
    "financial_report": "finance",
    "financial_stability_report": "finance",
    "startup_suggestion_report": "finance",
    "property_report": "finance",
    "love_relationship_report": "love",
    "love_disappointment_report": "love",
    "relationship_future_report": "love",
    "marriage_report": "marriage",
    "love_marriage_report": "marriage",
    "delay_in_marriage_report": "marriage",
    "problem_in_marriage_report": "marriage",
    "second_marriage_report": "marriage",
    "government_job_report": "self",
    "foreign_travel_report": "self",
    "business_report": "self",
    "career_report": "self",
    "gemstone_consultation": "self",
    "children_parenting_report": "self",
    "lifestyle_analysis_report": "self",
    "mood_mental_health_report": "self",
    "divorce_possibility_report": "self",
    "legal_disputes_report": "self",
}
# Runtime safety net ONLY (never intended to be used): an original product that
# somehow has no mapping above is still a real, PAID sale, so it is measured
# with this category and an ERROR is logged so the gap is noticed -- analytics
# metadata must never drop revenue nor break payment finalization.
UNMAPPED_ORIGINAL_CATEGORY = "other"

SUPPORTED_CURRENCIES = frozenset({"INR"})
PAYMENT_PROVIDER = "RAZORPAY"
SOURCE_PLATFORM = "web"

ALLOWED_FIELDS = frozenset({
    "transaction_id", "value", "currency", "item_id", "item_name", "item_category",
    "product_family", "report_type", "payment_provider", "source_platform",
})


def transaction_id_for_order(order_id: int) -> str:
    return f"ord_{int(order_id)}"


def _major_units(amount_paise: int) -> float | int:
    """paise -> major units; a whole-rupee amount stays an int (51, not 51.0)."""
    value = Decimal(int(amount_paise)) / Decimal(100)
    return int(value) if value == value.to_integral_value() else float(value)


def build_purchase_measurement(order_id: Any) -> Optional[Dict[str, Any]]:
    try:
        if order_id is None:
            return None
        order = db.session.get(Order, int(order_id))
        # THE financial gate: nothing but a PAID Order can ever be measured.
        if order is None or order.payment_status != "PAID":
            return None
        if not order.razorpay_order_id:
            return None
        if order.amount_paise is None or int(order.amount_paise) <= 0:
            return None

        product = db.session.get(ReportProduct, order.product)
        if product is None:
            return None
        family_and_type = MEASURED_GENERATORS.get(product.generator)
        if family_and_type is None:
            return None  # any other generator: out of scope
        product_family, report_type = family_and_type
        if product.currency not in SUPPORTED_CURRENCIES:
            _logger.warning("purchase_measurement: unsupported currency %r for Order.id=%s", product.currency, order.id)
            return None

        if product_family == FOCUSED_FAMILY:
            try:
                category = get_question(order.product).category
            except UnknownQuestionError:
                return None
        else:
            category = ORIGINAL_REPORT_CATEGORIES.get(order.product)
            if category is None:
                _logger.error(
                    "purchase_measurement: original product %r has no ORIGINAL_REPORT_CATEGORIES entry "
                    "(Order.id=%s) -- measured as %r; add it to the mapping",
                    order.product, order.id, UNMAPPED_ORIGINAL_CATEGORY,
                )
                category = UNMAPPED_ORIGINAL_CATEGORY

        measurement: Dict[str, Any] = {
            "transaction_id": transaction_id_for_order(order.id),
            "value": _major_units(order.amount_paise),
            "currency": product.currency,
            "item_id": order.product,
            "item_category": category,
            "product_family": product_family,
            "report_type": report_type,
            "payment_provider": PAYMENT_PROVIDER,
            "source_platform": SOURCE_PLATFORM,
        }
        if product.name:
            measurement["item_name"] = product.name
        return measurement
    except Exception:
        _logger.warning(
            "purchase_measurement: could not build measurement for Order.id=%r (swallowed -- the payment response is unaffected)",
            order_id, exc_info=True,
        )
        return None
