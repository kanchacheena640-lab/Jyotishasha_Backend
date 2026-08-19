from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from modules.subscription.models import Subscription
from config.razorpay_config import razorpay_client
from datetime import datetime, timedelta

# Subscription Migration Phase 1 -- resolve_profile_id_from_account_
# user_id is still used below for identity resolution. mirror_trial_
# start is no longer imported here -- Manual Trial Activation removed
# this file's own automatic trial-start call (see get_subscription()'s
# own comment on why).
from modules.subscription.dual_write_adapter import (
    resolve_profile_id_from_account_user_id,
)

# Welcome Gift Trial (S-Trial.3) -- the approved single entry point for
# every subscription WRITE (see subscription_service.py's own module
# docstring: "nobody should call EntitlementWriteService directly").
# start-trial below is a thin controller in front of this, exactly like
# every other write already in this codebase.
from modules.subscription.subscription_service import SubscriptionService

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

        # Manual Trial Activation: this used to also mirror-start a REAL
        # System C trial here (Phase 1 dual-write, best-effort) the
        # first time this legacy route ever ran for a profile -- an
        # automatic trial start this task's product decision explicitly
        # forbids, discovered as a 4th auto-provisioning path beyond the
        # 3 originally audited (bootstrap/update-fcm/register-or-update).
        # Confirmed unreachable from the current Flutter app (nothing
        # calls GET /api/subscription), so this was a latent landmine,
        # not an active bug -- removed for correctness/defense-in-depth
        # regardless. The legacy Subscription row above is untouched
        # (still created exactly as before -- other legacy consumers,
        # e.g. subscription_required, depend on it existing); only the
        # System C trial mirror is removed. A trial for this profile can
        # now only ever start via POST /api/profile/activate-trial.

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

# -------------------- Start Free Trial (Welcome Gift) -------------------- #
# NOTE: this blueprint is registered with url_prefix="/api/subscription"
# (modules/subscription/__init__.py::register_subscription) while every
# route ABOVE this one also bakes "/api/subscription" into its own
# decorator path -- a documented, intentionally-preserved quirk (see
# that file's own S4.0 comment) that makes their live URLs doubled
# (e.g. "/api/subscription/api/subscription"). This new route does NOT
# repeat that mistake: its decorator path is relative ("/start-trial"),
# so combined with the blueprint's url_prefix it resolves to exactly
# the required "/api/subscription/start-trial" -- not a doubled path.
@subscription_bp.post("/start-trial")
@jwt_required()
def start_trial():
    """
    Welcome Gift Trial (S-Trial.3). The client calls this ONLY when the
    user explicitly taps "Activate Free Gift" on the Explore page --
    there is no automatic trigger anywhere (not on login, not on
    bootstrap). This route itself has no opinion about that; it simply
    starts a trial for whichever authenticated profile calls it, exactly
    once, ever.

    Identity resolution reuses the exact same three calls already used
    by get_subscription() above and routes/routes_premium_report.py::
    get_premium_report() -- @jwt_required() + get_jwt_identity() +
    resolve_profile_id_from_account_user_id() (dual_write_adapter.py).
    No new auth mechanism.

    All trial-eligibility business rules (one-time-per-profile, never
    overwriting an active/grace paid subscription) live entirely in
    EntitlementWriteService.start_trial() and are not duplicated here --
    this route only calls SubscriptionService.start_trial() (the
    approved single write entry point) and translates its structured
    EntitlementWriteResult into HTTP:
        action == "TRIAL_STARTED" -> 200, the new trial window.
        action == "TRIAL_SKIPPED" -> 409 trial_already_claimed. Covers
            both sub-cases EntitlementWriteService already merges into
            one outcome -- this profile already trialed before (even if
            it has since expired), or already has an ACTIVE/GRACE paid
            subscription. Either way nothing about the existing state
            changes (the write service returns before touching the
            row), which is exactly "existing paid subscription:
            behavior remains unchanged."
    """
    user_id = get_jwt_identity()
    profile_id = resolve_profile_id_from_account_user_id(user_id)

    if profile_id is None:
        return jsonify({
            "ok": False,
            "error": "forbidden",
            "message": "No profile is associated with this account.",
        }), 403

    result = SubscriptionService().start_trial(profile_id)

    if result.action != "TRIAL_STARTED":
        return jsonify({"ok": False, "error": "trial_already_claimed"}), 409

    # Re-read the just-committed state via the existing read API rather
    # than re-deriving trial_started_at from business rules a second
    # time -- EntitlementWriteResult doesn't carry started_at, and this
    # is the exact same EntitlementService.get_current_entitlement() read
    # get_subscription() above already uses.
    from modules.entitlement import EntitlementService

    snapshot = EntitlementService().get_current_entitlement(profile_id)

    return jsonify({
        "ok": True,
        "status": "TRIAL",
        "trial_started_at": snapshot.trial.started_at.isoformat() if snapshot.trial.started_at else None,
        "trial_expires_at": snapshot.trial.expires_at.isoformat() if snapshot.trial.expires_at else None,
    }), 200
