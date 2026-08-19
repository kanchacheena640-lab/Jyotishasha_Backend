# modules/models_processed_payments.py

"""
ProcessedPayment -- the idempotency ledger for PaymentService.

Payment Hardening Phase 3: neither `orders` nor any other existing
table stores a payment's provider transaction id anywhere queryable,
which is why duplicate processing (browser refresh, double-click,
network retry, duplicate webhook, the same razorpay_payment_id
submitted twice) could not previously be detected at all. This is a
new, minimal, additive table -- it does not alter `orders` or any
other existing table's structure.

One row per successfully-verified payment, keyed by (provider,
payment_id) with a DB-level UNIQUE constraint -- the actual mechanism
that prevents two concurrent requests for the same payment from both
creating an Order, not just a lucky race. See
modules/payments/payment_service.py's process_payment() for the
claim -> business effect -> finalize sequence built around this
constraint.
"""

from datetime import datetime

from extensions import db


class ProcessedPayment(db.Model):
    __tablename__ = "processed_payments"

    id = db.Column(db.Integer, primary_key=True)

    provider = db.Column(db.String(20), nullable=False)          # PaymentProviderType

    # Widened 120 -> 255 (migration 9f4d2a7e1c6b): a real Google Play
    # purchase_token is commonly 150-190+ characters -- VARCHAR(120)
    # (a bound copied from the short razorpay_payment_id example)
    # silently raised a DataError on insert for GOOGLE_PLAY payments,
    # uncaught by _try_claim()'s own except IntegrityError (a
    # different exception class), producing an unlogged 500. 255
    # matches every other Google Play purchase-token column already in
    # this codebase (SubscriptionPurchaseMapping.purchase_token,
    # CurrentEntitlement.purchase_token, SubscriptionEvent.purchase_token).
    payment_id = db.Column(db.String(255), nullable=False, index=True)  # e.g. razorpay_payment_id or a Google Play purchase_token
    reference = db.Column(db.String(255), nullable=True)         # e.g. razorpay_order_id or the same Google Play purchase_token

    # Populated once the business effect completes -- nullable because
    # a row is first inserted as a "claim" (see _try_claim) before the
    # Order exists, to atomically win any concurrent race on payment_id.
    order_id = db.Column(db.Integer, nullable=True)
    response_payload = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("provider", "payment_id", name="uq_processed_payments_provider_payment_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "payment_id": self.payment_id,
            "reference": self.reference,
            "order_id": self.order_id,
            "response_payload": self.response_payload,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<ProcessedPayment provider={self.provider} payment_id={self.payment_id} "
            f"order_id={self.order_id}>"
        )
