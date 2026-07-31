# modules/models_processed_subscription_events.py

"""
ProcessedSubscriptionEvent -- the idempotency ledger for subscription
purchase/renewal/cancellation/refund events (Subscription Purchase
System -- S5), mirroring modules/models_processed_payments.py::
ProcessedPayment's exact role and shape for a recurring product
instead of a one-time payment.

Why a separate table rather than reusing ProcessedPayment: a report
purchase's payment_id is unique for the life of that transaction, full
stop. A subscription is recurring -- the SAME subscription legitimately
produces a new billing event every renewal period, forever. Keying on
a stable, per-SUBSCRIPTION identifier (Google Play's linked purchase
token; Apple's originalTransactionId) would make every renewal collide
with the first purchase's claim and be wrongly rejected as a
duplicate. This ledger is keyed on the store's PER-EVENT identifier
instead (Google: the specific orderId for one charge; Apple: the
transactionId for one transaction) -- see the Duplicate Purchase
Protection design review for the full reasoning. purchaseToken,
linkedPurchaseToken, and originalTransactionId must never be used as
transaction_id here.

One row per (store, transaction_id) -- a DB-level UNIQUE constraint,
the actual mechanism, not just a convention -- created as an
unfinished "claim" (response_payload=None) before any business
processing begins, and filled in only once that processing completes
successfully. See modules/payments/processed_subscription_event_service.py
for the claim/finalize logic built around this constraint; this file
defines only the table.
"""

from datetime import datetime

from extensions import db


class ProcessedSubscriptionEvent(db.Model):
    __tablename__ = "processed_subscription_events"

    id = db.Column(db.Integer, primary_key=True)

    store = db.Column(db.String(20), nullable=False)  # SUBSCRIPTION_STORES: GOOGLE_PLAY | APP_STORE | MANUAL
    transaction_id = db.Column(db.String(255), nullable=False, index=True)  # per-EVENT id -- see module docstring
    event_type = db.Column(db.String(40), nullable=True)  # SUBSCRIPTION_EVENT_TYPES, informational only

    # Populated once resolved -- nullable because a row is first
    # inserted as a claim (see try_claim()) before profile resolution
    # may have happened, mirroring ProcessedPayment.order_id's own
    # deliberately-no-foreign-key precedent for the same reason.
    profile_id = db.Column(db.Integer, nullable=True)

    # NULL until the claiming caller's business processing succeeds --
    # the claim-then-finalize marker. Left NULL forever if that
    # processing fails; never auto-deleted, never auto-released.
    response_payload = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "store", "transaction_id",
            name="uq_processed_subscription_events_store_transaction_id",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "store": self.store,
            "transaction_id": self.transaction_id,
            "event_type": self.event_type,
            "profile_id": self.profile_id,
            "response_payload": self.response_payload,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<ProcessedSubscriptionEvent store={self.store} "
            f"transaction_id={self.transaction_id} profile_id={self.profile_id}>"
        )
