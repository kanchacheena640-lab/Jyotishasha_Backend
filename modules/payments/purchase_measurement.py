# modules/payments/purchase_measurement.py

"""
Reports Ads P0.2 -- the ONE canonical purchase measurement object.

The only financial authority is the backend-verified internal Order with
payment_status == "PAID". build_purchase_measurement() derives the object
ENTIRELY from trusted backend state (the Order row, the ReportProduct
registry, the focused-report question catalog) -- never from anything the
browser sent -- and returns None for anything that is not a PAID focused
web/Razorpay purchase. POST /webhook attaches it to the responses that
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
    item_category    the focused-report catalog category.
    product_family   "focused_report".
    report_type      "self" (focused_v1) or "dual" (focused_dual_v1).
    payment_provider "RAZORPAY".
    source_platform  "web".

Never included: name, email, phone, DOB/TOB/place, coordinates, partner
data, payment ids, click ids or UTM values.

SCOPE: the 63 focused reports on web/Razorpay only. Original 25 reports,
the relationship report, Google Play, Meta and server-side reconciliation
are deliberately out of scope (None is returned for them).

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

FOCUSED_GENERATOR_REPORT_TYPE = {"focused_v1": "self", "focused_dual_v1": "dual"}
SUPPORTED_CURRENCIES = frozenset({"INR"})
PRODUCT_FAMILY = "focused_report"
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
        report_type = FOCUSED_GENERATOR_REPORT_TYPE.get(product.generator)
        if report_type is None:
            return None  # original / relationship reports: out of scope
        if product.currency not in SUPPORTED_CURRENCIES:
            _logger.warning("purchase_measurement: unsupported currency %r for Order.id=%s", product.currency, order.id)
            return None

        try:
            category = get_question(order.product).category
        except UnknownQuestionError:
            return None

        measurement: Dict[str, Any] = {
            "transaction_id": transaction_id_for_order(order.id),
            "value": _major_units(order.amount_paise),
            "currency": product.currency,
            "item_id": order.product,
            "item_category": category,
            "product_family": PRODUCT_FAMILY,
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
