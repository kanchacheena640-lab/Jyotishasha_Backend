from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from modules.subscription.models import Subscription
from config.razorpay_config import razorpay_client
from datetime import datetime, timedelta

# Subscription Migration Phase 1 -- temporary dual-write, see
# modules/subscription/dual_write_adapter.py for what this is and why.
from modules.subscription.dual_write_adapter import (
    mirror_trial_start,
    resolve_profile_id_from_account_user_id,
)

subscription_bp = Blueprint("subscription_bp", __name__)

# -------------------- GET Subscription Status -------------------- #
@subscription_bp.get("/api/subscription")
@jwt_required()
def get_subscription():
    uid = get_jwt_identity()
    sub = Subscription.query.filter_by(user_id=uid).first()

    if not sub:
        # auto-create 15-day free plan -- UNCHANGED. Other legacy
        # consumers (e.g. modules/subscription/utils.py::
        # subscription_required, still on the legacy implementation
        # per this phase's approved scope) depend on this row existing;
        # removing this write would be a regression for them, not a
        # migration of this route.
        sub = Subscription(
            user_id=uid,
            plan="free",
            status="active",
            start_at=datetime.utcnow(),
            end_at=datetime.utcnow() + timedelta(days=15)
        )
        db.session.add(sub)
        db.session.commit()

        # Phase 1 dual-write: mirror this trial start into System C.
        # Best-effort -- cannot affect the response above, which has
        # already succeeded.
        profile_id = resolve_profile_id_from_account_user_id(uid)
        if profile_id is not None:
            mirror_trial_start(profile_id)

    # Subscription Migration Phase 3 -- this consumer is confirmed
    # READY per the approved Migration Plan. The legacy write above is
    # intentionally preserved (see comment); only the RESPONSE is now
    # sourced from the Entitlement Engine (System C) via its existing
    # read API, reusing the same identity resolution the dual-write
    # adapter already uses. No new business logic -- this reshapes an
    # already-computed EntitlementSnapshot into the same
    # {"subscription": {...}} shape this endpoint already returned. If
    # no profile can be resolved (or System C genuinely has nothing
    # for it yet, a narrow race with the dual-write mirror just above),
    # falls back to the legacy row's own data so the response is never
    # empty.
    from modules.entitlement import EntitlementService

    profile_id = resolve_profile_id_from_account_user_id(uid)
    snapshot = EntitlementService().get_current_entitlement(profile_id) if profile_id else None

    if snapshot is not None and snapshot.status != "PENDING":
        if snapshot.trial.is_active:
            plan, is_active = "free", True
            start_at, end_at = snapshot.trial.started_at, snapshot.trial.expires_at
        elif snapshot.subscription.is_active:
            plan, is_active = snapshot.plan, True
            start_at, end_at = snapshot.subscription.started_at, snapshot.subscription.expires_at
        else:
            plan = snapshot.plan or "free"
            is_active = False
            start_at = snapshot.trial.started_at or snapshot.subscription.started_at
            end_at = snapshot.trial.expires_at or snapshot.subscription.expires_at

        return jsonify({"subscription": {
            "plan": plan,
            "status": "active" if is_active else "inactive",
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
            "is_active": is_active,
            # membership_state/remaining_days (S-Trial.1) -- same
            # snapshot-derived properties as
            # modules/auth/routes_profile.py::subscription_info(), so
            # this endpoint can't disagree with that one about whether
            # a trial user counts as "no subscription". Reused, not
            # recalculated -- `snapshot` above already has both.
            "membership_state": snapshot.membership_state,
            "remaining_days": snapshot.remaining_trial_days,
        }}), 200

    # Legacy fallback -- only reached if no profile could be resolved
    # or System C genuinely has nothing yet (the narrow dual-write race
    # noted above). `sub` (the legacy Subscription row) has no
    # trial-day concept at all, so membership_state/remaining_days
    # can't be derived from it the way the branch above derives them
    # from `snapshot` -- literal "NONE"/None here is this branch's own
    # equivalent of subscription_info()'s "no profile resolved" branch,
    # keeping the contract uniform (S-Trial.2) without touching
    # `sub.to_dict()` or any legacy business logic.
    return jsonify({"subscription": {
        **sub.to_dict(),
        "membership_state": "NONE",
        "remaining_days": None,
    }}), 200

# -------------------- Create Razorpay Order for Subscription -------------------- #
@subscription_bp.post("/api/subscription/create-order")
@jwt_required()
def create_subscription_order():
    uid = get_jwt_identity()
    data = request.get_json() or {}
    plan = data.get("plan", "monthly")

    amount = 9900 if plan == "monthly" else 55100  # in paise
    notes = {
        "user_id": str(uid),
        "plan": plan,
    }

    razorpay_order = razorpay_client.order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": f"sub_{uid}_{plan}_{datetime.utcnow().timestamp()}",
        "payment_capture": 1,
        "notes": notes
    })

    return jsonify({
        "order_id": razorpay_order["id"],
        "amount": razorpay_order["amount"],
        "currency": razorpay_order["currency"],
        "plan": plan
    }), 200
