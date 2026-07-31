# modules/models_subscription_purchase_mapping.py

"""
SubscriptionPurchaseMapping -- Subscription Purchase System, S7E.

RTDN identity resolution. A Google Play RTDN notification carries only
packageName / purchaseToken / subscriptionId -- never profile_id or
any other application identity (see the S7A/S7B/S7C docstrings this
table finally resolves). This table is the one place that answers
"which profile does this purchase_token belong to", populated at
purchase time (PaymentService, see
modules/payments/subscription_purchase_mapping_service.py) and read at
RTDN time (routes/routes_rtdn.py) -- neither the RTDN dispatcher
(SubscriptionService.process_webhook_event(), S7B) nor Google
verification (GooglePlayProvider, S3) are touched to add this; both
already accept/produce exactly the values this table stores.

linked_purchase_token exists for Google's own token-replacement
mechanic: an upgrade/downgrade/resubscription issues a brand new
purchase_token, and that NEW purchase's own verification response
carries linked_purchase_token pointing back at the token it replaced.
Storing that link on the NEW row lets a later RTDN for the OLD,
now-superseded token still resolve to the same profile -- see
SubscriptionPurchaseMappingService.resolve_profile_id()'s fallback
lookup.

status distinguishes the currently-operative purchase_token for a
profile (ACTIVE) from one that has since been replaced by a newer
token (SUPERSEDED) -- informational/traceability only; resolution
itself does not filter on status (a superseded token must still
resolve correctly for a late-arriving RTDN).
"""

from __future__ import annotations

from datetime import datetime

from extensions import db

SUBSCRIPTION_PURCHASE_MAPPING_STATUSES = ("ACTIVE", "SUPERSEDED")


class SubscriptionPurchaseMapping(db.Model):
    __tablename__ = "subscription_purchase_mappings"

    id = db.Column(db.Integer, primary_key=True)

    # The primary lookup key -- one row per purchase_token Google has
    # ever issued for a profile's subscription (a new token is issued
    # on upgrade/downgrade/resubscribe; renewals under an unchanged
    # plan keep the same token and therefore the same row).
    purchase_token = db.Column(db.String(255), nullable=False, unique=True, index=True)

    # profile_id IS AppUser.id -- same convention as CurrentEntitlement/
    # SubscriptionEvent (modules/models_premium_subscription.py).
    profile_id = db.Column(
        db.Integer, db.ForeignKey("app_users.id"), nullable=False, index=True,
    )

    # Optional, account-scoped identity (Systems A/B's own convention) --
    # not required for resolution, kept only for traceability where a
    # caller happens to know it.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    provider = db.Column(db.String(20), nullable=False)  # SUBSCRIPTION_STORES
    product_id = db.Column(db.String(120), nullable=True)
    order_id = db.Column(db.String(120), nullable=True)  # most recently known orderId for this token
    linked_purchase_token = db.Column(db.String(255), nullable=True, index=True)

    status = db.Column(db.String(20), nullable=False, default="ACTIVE")  # SUBSCRIPTION_PURCHASE_MAPPING_STATUSES

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
