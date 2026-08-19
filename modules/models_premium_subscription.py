# modules/models_premium_subscription.py

"""
Subscription System - Phase 1: Data Model Only.

Premium AI Report subscriptions are evaluated PER PROFILE
(`profile_id`, the existing AppUser.id -- see modules/models_ai_reports.py
and the AI Report Engine's own architecture decision), NEVER per
account/login. This is a deliberate departure from the older,
account-scoped `modules/subscription/models.py::Subscription` (FK'd to
`users.id`) -- that model is untouched by this phase and is a separate,
legacy system; this file is the finalized, profile-scoped subscription
architecture for the Premium AI Report product specifically.

No payment gateway, no Play Billing, no App Store Billing, no
authentication, and no trial-length/entitlement CALCULATION logic lives
here -- this file only defines the tables and the fields future phases
will compute into.

Two tables, deliberately separated (current entitlement vs history):

- CurrentEntitlement: ONE row per profile_id (unique constraint), the
  fast, single source of truth for "what access does this profile have
  right now." Updated in place -- mirrors the AI Report Engine's own
  "one cache row per key, update in place" lesson (see
  modules/models_ai_reports.py's revision history).

- SubscriptionEvent: an APPEND-ONLY log, one row per subscription-
  affecting event (trial started, plan purchased, renewed, expired,
  cancelled, grace entered, refunded, ...). Rows here are never updated
  or deleted -- this is the audit trail CurrentEntitlement is derived
  from, and the natural home for store/receipt metadata a future Google
  Play / Apple Store validation phase will need.
"""

from datetime import datetime
from extensions import db


# ---------------------------------------------------------------
# Allowed values (plain constants, matching this project's existing
# style -- e.g. AI_REPORT_SEGMENTS/AI_REPORT_TYPES/AI_REPORT_STATUSES in
# modules/models_ai_reports.py -- rather than native DB enum types).
# ---------------------------------------------------------------
SUBSCRIPTION_PLANS = (
    "PRIME_MONTHLY",
    "PRIME_YEARLY",
    "PRIME_PLUS_MONTHLY",
    "PRIME_PLUS_YEARLY",
    # Subscription Purchase System -- S11: the real, finalized Google
    # Play Console product lineup -- a new 3-tier ladder (Silver/Gold/
    # Platinum) sold alongside Prime/Prime Plus, not a replacement for
    # it. Segment-access rules for these five live in
    # modules/entitlement/plan_access_policy.py, same as every plan
    # above.
    "SILVER_MONTHLY",
    "SILVER_YEARLY",
    "GOLD_MONTHLY",
    "GOLD_YEARLY",
    "PLATINUM_YEARLY",
)

# The full lifecycle CurrentEntitlement.status can be in. TRIAL is
# included here (even though the task's "Subscription" section lists
# Active/Expired/Grace/Cancelled/Pending/Refunded separately from
# "Trial") because CurrentEntitlement represents the profile's single,
# current access level end-to-end -- a profile that has never purchased
# anything but is still inside its trial window (see
# EntitlementWriteService.DEFAULT_TRIAL_DURATION_DAYS for the current
# length) IS currently entitled, and TRIAL is the only status value
# that says so.
ENTITLEMENT_STATUSES = (
    "TRIAL",
    "ACTIVE",
    "EXPIRED",
    "GRACE",
    "CANCELLED",
    "PENDING",
    "REFUNDED",   # future
)

# Distinct from ENTITLEMENT_STATUSES -- these name WHAT HAPPENED, for
# the append-only history log, not the resulting current state (the
# same event can be looked up alongside the `status` it produced).
SUBSCRIPTION_EVENT_TYPES = (
    "TRIAL_STARTED",
    "TRIAL_EXPIRED",
    "SUBSCRIPTION_PENDING_CREATED",
    "SUBSCRIPTION_STARTED",
    "SUBSCRIPTION_RENEWED",
    "SUBSCRIPTION_GRACE_ENTERED",
    "SUBSCRIPTION_EXPIRED",
    "SUBSCRIPTION_CANCELLED",
    "SUBSCRIPTION_REFUNDED",   # future
)

# Where a subscription-affecting event originated -- stored now so a
# future validation phase has somewhere to record it; nothing in this
# phase reads or validates against a real store.
SUBSCRIPTION_STORES = (
    "GOOGLE_PLAY",
    "APP_STORE",
    "MANUAL",   # e.g. admin-granted, support-comp
)


class CurrentEntitlement(db.Model):
    __tablename__ = "current_entitlements"

    id = db.Column(db.Integer, primary_key=True)

    # profile_id IS AppUser.id -- same convention as AIReport.profile_id.
    # Premium is evaluated per profile, never per account/User.
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("app_users.id"),
        nullable=False,
        unique=True,   # exactly ONE current-entitlement row per profile
        index=True,
    )

    status = db.Column(db.String(20), nullable=False, default="PENDING")  # ENTITLEMENT_STATUSES
    plan = db.Column(db.String(30), nullable=True)  # SUBSCRIPTION_PLANS -- None while on trial / never purchased

    # Which single segment a PRIME_MONTHLY/PRIME_YEARLY purchase covers
    # (added in Phase 2 to support EntitlementService's section-access
    # rules -- see modules/entitlement/plan_access_policy.py). Unused/
    # None for PRIME_PLUS_* plans, which grant every segment.
    selected_segment = db.Column(db.String(20), nullable=True)  # AI_REPORT_SEGMENTS (modules/models_ai_reports.py)

    # Trial -- fields only, no calculation performed in this phase.
    trial_started_at = db.Column(db.DateTime, nullable=True)
    trial_expires_at = db.Column(db.DateTime, nullable=True)

    # Current paid-subscription window, if any.
    subscription_started_at = db.Column(db.DateTime, nullable=True)
    subscription_expires_at = db.Column(db.DateTime, nullable=True, index=True)

    # Metadata for a future Google Play / Apple Store validation phase.
    # Describes the CURRENT subscription only -- full history lives in
    # SubscriptionEvent, never here.
    store = db.Column(db.String(20), nullable=True)          # SUBSCRIPTION_STORES
    purchase_token = db.Column(db.String(255), nullable=True)
    auto_renew = db.Column(db.Boolean, nullable=True)

    # Traceability pointer to the most recent history row that produced
    # this current state -- optional, but cheap and useful for audit.
    last_event_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_events.id"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )

    profile = db.relationship("AppUser", backref="current_entitlement")
    last_event = db.relationship("SubscriptionEvent", foreign_keys=[last_event_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "status": self.status,
            "plan": self.plan,
            "selected_segment": self.selected_segment,
            "trial_started_at": self.trial_started_at.isoformat() if self.trial_started_at else None,
            "trial_expires_at": self.trial_expires_at.isoformat() if self.trial_expires_at else None,
            "subscription_started_at": self.subscription_started_at.isoformat() if self.subscription_started_at else None,
            "subscription_expires_at": self.subscription_expires_at.isoformat() if self.subscription_expires_at else None,
            "store": self.store,
            "auto_renew": self.auto_renew,
            "last_event_id": self.last_event_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<CurrentEntitlement profile_id={self.profile_id} "
            f"status={self.status} plan={self.plan}>"
        )


class SubscriptionEvent(db.Model):
    __tablename__ = "subscription_events"

    id = db.Column(db.Integer, primary_key=True)

    # Same profile-scoped convention as CurrentEntitlement -- NOT
    # unique here, since a profile accumulates many events over time.
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("app_users.id"),
        nullable=False,
        index=True,
    )

    event_type = db.Column(db.String(40), nullable=False, index=True)  # SUBSCRIPTION_EVENT_TYPES
    status = db.Column(db.String(20), nullable=False)                  # ENTITLEMENT_STATUSES -- resulting status
    plan = db.Column(db.String(30), nullable=True)                     # SUBSCRIPTION_PLANS -- irrelevant for trial events
    selected_segment = db.Column(db.String(20), nullable=True)         # AI_REPORT_SEGMENTS -- see CurrentEntitlement

    # The period this event established, if any (e.g. the new
    # subscription window a SUBSCRIPTION_RENEWED event produced).
    starts_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    # Metadata for a future Google Play / Apple Store receipt validation
    # phase -- stored as-is now, validated by nobody yet.
    store = db.Column(db.String(20), nullable=True)              # SUBSCRIPTION_STORES
    purchase_token = db.Column(db.String(255), nullable=True)
    transaction_id = db.Column(db.String(255), nullable=True)
    receipt_payload = db.Column(db.JSON, nullable=True)

    # Append-only: this is the only timestamp this row ever has, and it
    # is never updated after insert.
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    profile = db.relationship("AppUser", backref="subscription_events")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "event_type": self.event_type,
            "status": self.status,
            "plan": self.plan,
            "selected_segment": self.selected_segment,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "store": self.store,
            "transaction_id": self.transaction_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<SubscriptionEvent profile_id={self.profile_id} "
            f"event_type={self.event_type} status={self.status}>"
        )
