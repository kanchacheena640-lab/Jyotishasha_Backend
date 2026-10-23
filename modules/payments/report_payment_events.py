# modules/payments/report_payment_events.py

"""
payment_verified for website (Razorpay) paid-report purchases.

Website report payments are finalized by PaymentFinalizationService (POST
/webhook -- both the browser callback and Razorpay's own payment.captured
webhook), which never went through PaymentService, so no payment_verified
activity event was ever recorded for them. Admin website analytics
(report_payment_verified, report_payment_verified_by_campaign) count
exactly that event, filtered on purpose=REPORT_PURCHASE, so website report
purchases were missing from them entirely.

Contract -- identical to PaymentService's own payment_verified producer
(platform/purpose/provider/order_reference/entity/dedupe_key), plus the
schema's optional amount/currency as the Chat Pack (Razorpay) producer
already sends them:

    event_name       payment_verified (v1)
    platform         backend_internal
    properties       purpose=REPORT_PURCHASE, provider=RAZORPAY,
                     order_reference=<razorpay_order_id>,
                     amount=<Order.amount_paise in rupees>, currency=<ReportProduct.currency>
    entity           ("order", <internal Order.id>)
    dedupe_key       payment_verified:RAZORPAY:<razorpay_payment_id>
    campaign_context the request's own sanitized Razorpay order.notes snapshot

Exactly one logical event per paid Order:
  - Emitted only on FINALIZED, which exactly one transaction per Order can
    return (the atomic ProcessedPayment claim + PAYMENT_PENDING -> PAID
    commit). A concurrent browser callback / webhook retry loses the claim
    and resolves to ALREADY_FINALIZED, which emits nothing.
  - The dedupe_key is the same key PaymentService would derive for this
    Razorpay payment, and the ledger's partial unique index
    (ux_activity_events_dedupe_key) rejects any second row for it.
  - At-most-once, not exactly-once, across a process crash in the narrow
    window between the PAID commit and this write: making that durable
    would need an outbox table (a migration), deliberately not done here.

No personal data: no name, email, phone, birth details or payment
signature; the Razorpay ids are the same non-sensitive references
PaymentService and the Chat Pack producer already record.

Never raises: record_event() writes in its own session and swallows
write/duplicate failures; everything else here is wrapped too, so a
payment that is already PAID can never be failed, delayed beyond a
single ledger insert, or kept from report dispatch by analytics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from extensions import db
from modules.activity_events.service import record_event
from modules.payments.payment_models import PaymentProviderType, PaymentPurpose, PaymentRequest
from modules.payments.purchase_measurement import _major_units
from modules.payments.report_product_registry import ReportProduct

_logger = logging.getLogger(__name__)

EVENT_SOURCE = "payment_finalization_service"


def report_payment_verified_dedupe_key(request: PaymentRequest) -> Optional[str]:
    """Same derivation as PaymentService._payment_verified_dedupe_key() for
    Razorpay (the provider payment id is safe to store as-is)."""
    if request.provider != PaymentProviderType.RAZORPAY or not request.payment_id:
        return None
    return f"payment_verified:RAZORPAY:{request.payment_id}"


def _product_currency(product_slug: str) -> Optional[str]:
    """Read-only lookup on the request's shared db.session, which the caller
    goes on to use for report dispatch. The Order is already committed PAID
    and nothing is pending, so if this read fails the session is rolled back
    -- otherwise a failed read could leave the transaction aborted and break
    the dispatch that follows."""
    try:
        product = db.session.get(ReportProduct, product_slug)
        return product.currency if product is not None and product.currency else None
    except Exception:
        db.session.rollback()
        _logger.warning("report_payment_events: currency lookup failed for %r (event sent without currency)",
                        product_slug, exc_info=True)
        return None


def emit_report_payment_verified(
    request: PaymentRequest,
    *,
    order_id: int,
    product_slug: str,
    amount_paise: int,
    correlation_id: Optional[str] = None,
) -> None:
    """Record payment_verified for a website report Order that was JUST
    finalized PAID. Call only after that commit. Never raises."""
    try:
        if request.purpose != PaymentPurpose.REPORT_PURCHASE or request.provider != PaymentProviderType.RAZORPAY:
            return
        dedupe_key = report_payment_verified_dedupe_key(request)
        if dedupe_key is None or not request.reference:
            return

        properties = {
            "purpose": PaymentPurpose.REPORT_PURCHASE,
            "provider": PaymentProviderType.RAZORPAY,
            "order_reference": request.reference,
        }
        if amount_paise is not None and int(amount_paise) > 0:
            properties["amount"] = _major_units(int(amount_paise))
            currency = _product_currency(product_slug)
            if currency:
                properties["currency"] = currency

        record_event(
            event_name="payment_verified",
            occurred_at=datetime.now(timezone.utc),
            platform="backend_internal",
            source=EVENT_SOURCE,
            firebase_uid=None,
            profile_id=None,
            correlation_id=correlation_id,
            entity_type="order",
            entity_id=str(order_id),
            properties=properties,
            campaign_context=request.campaign_context,
            dedupe_key=dedupe_key,
        )
    except Exception:
        _logger.warning(
            "report_payment_events: could not record payment_verified for Order.id=%s "
            "(swallowed -- the PAID Order and report dispatch are unaffected)",
            order_id, exc_info=True,
        )
