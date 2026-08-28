# routes/routes_chat.py

"""
Unified Chat Routes (ChatPack 51 System)

Endpoints:
1) /api/chat/free            → 1 free question per day
2) /api/chat/pack            → Use paid ChatPack (8 questions)
3) /api/chat/pack/order      → Create ₹51 Razorpay order
4) /api/chat/pack/verify     → Verify payment & activate pack
5) /api/chat/pack/status     → Debug: check remaining questions

Uses:
- chat_engine.py
- free_quota_service.py
- chat_pack_service.py

==================================================
Trust Foundation Phase 0 -- identity hardening
==================================================
Every endpoint below used to trust a client-supplied `user_id` field
(request body or query string) with no proof the caller actually owned
that identity -- confirmed exploitable (read/drain another account's
free or paid questions, or forge a wrong-account credit) by the
Identity Integrity + Ask Now Auth audit. Fixed the same way every other
hardened route in this codebase already is: @jwt_required() +
get_jwt_identity() -- no new auth mechanism, no second framework.

get_jwt_identity() returns users.id (the account, per
create_access_token(identity=str(user.id)) in routes/routes_auth.py) --
exactly what ChatPack.user_id / FreeDailyQuestion.user_id already store
in production for the overwhelming majority of real rows (confirmed
against live data during the audit, not assumed from naming). No
app_users/profile_id bridge is introduced here -- none is needed.

A request body's own `user_id` field, if a client still sends one
(e.g. an un-updated app build), is no longer read for identity at all
-- the authenticated identity is the only one ever used. This is a
deliberate simplification, not an oversight: unlike
routes_google_purchase_confirm.py's profile_id (which has a legitimate
optional/cross-account-reject shape), Ask Now's user_id has no
legitimate reason to ever come from the client once the header is
required.

/api/chat/debug/pack is no longer publicly callable at all -- it is
gated behind the SAME admin_required decorator (JWT + ADMIN_USER_IDS
allowlist) every other admin-only route in this codebase already uses
(notifications/notification_routes.py, routes/admin_orders.py). Its
business logic (reset/add) is unchanged -- it remains a legitimate
support tool, just no longer reachable by an unauthenticated caller.

==================================================
Safe Deployment Split (CTO decision) -- pre/post build-49 dual mode
==================================================
Production build 48 does not send the Bearer JWT above. Deploying
unconditional JWT enforcement before build 49 is publicly available
would break Ask Now for every currently-installed user. The fix above
is correct and stays exactly as built -- what changes here is WHEN it
becomes mandatory for the four routes build 48 actually calls:
/api/chat/free, /api/chat/pack, /api/chat/status, /api/chat/reward.
Every OTHER Ask Now route in this file (order/verify/google-verify/
alias/debug) is unconditionally strict already and untouched by this
section, because build 48 never calls any of them -- there is nothing
to preserve compatibility with there.

_asknow_jwt_enforced() is a single, server-side, default-OFF switch
(env var ASKNOW_JWT_ENFORCEMENT, re-read per request -- same posture as
notifications/notification_routes.py's own _admin_user_ids(): flip via
a Render env var + redeploy, no code change, no restart-timing race).
Deliberately NOT a generalized feature-flag platform -- one function,
one boolean, one purpose, gating exactly four routes.

_resolve_gated_user_id() is what those four routes call instead of
_authenticated_user_id(). Both routes decorate with
@jwt_required(optional=True) (never a hard 401 at the decorator level
for these four) so the resolver -- not the decorator -- makes the
compatibility decision:
    - A verified JWT, if presented, is ALWAYS used, regardless of the
      flag. A build-49 client (already sending the header) gets the
      secure path immediately, even before the flag is switched on --
      this is what makes the flag a one-way ratchet: turning it on
      never changes behavior for any client already sending a real JWT.
    - No JWT + flag ON  -> rejected (401), matching @jwt_required()'s
      own contract.
    - No JWT + flag OFF -> falls back to the exact pre-hardening
      body/query `user_id` contract (build 48's own, unchanged
      behavior) -- the ONLY place that legacy trust still exists, and
      only while the flag is OFF.

Removal checklist (once minimum_supported_build has been raised to 49
in production AND ASKNOW_JWT_ENFORCEMENT has been ON for a full deploy
cycle): delete _asknow_jwt_enforced(), delete _resolve_gated_user_id(),
change the four routes' decorator back to plain @jwt_required(), and
change their body back to `user_id = _authenticated_user_id()` --
i.e. revert this section verbatim to what Trust Foundation Phase 0
already built. Nothing else in this file needs to change.
"""
import os

from modules.services.chatpack_google_verify import verify_google_chatpack
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

# Reused, not reimplemented -- the same admin allowlist gate already
# proven by notifications/notification_routes.py and routes/admin_orders.py.
from notifications.notification_routes import admin_required

# Services
from modules.services.chat_engine import chat_engine
from modules.services.free_quota_service import (
    has_free_quota,
    use_free_quota,
    get_free_quota_status,
)
from modules.services.chat_pack_service import (
    create_chatpack_order,
    verify_chatpack_payment,
    deduct_question,
    get_pack_status,
)

routes_chat = Blueprint("routes_chat", __name__)


def _authenticated_user_id() -> int:
    """
    THE single place every UNCONDITIONALLY-strict Ask Now route below
    resolves identity from -- always the JWT's own account id, never a
    client-supplied field. See this module's own docstring for why no
    profile_id bridge is needed here (Ask Now is already users.id-scoped
    in production). NOT used by the four build-48-compatible routes --
    see _resolve_gated_user_id() for those.
    """
    return int(get_jwt_identity())


def _asknow_jwt_enforced() -> bool:
    """Safe Deployment Split -- see module docstring. Default OFF
    (unset/anything not truthy). Re-read on every call, never cached."""
    raw = os.environ.get("ASKNOW_JWT_ENFORCEMENT", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _resolve_gated_user_id():
    """
    Identity resolver for the four build-48-compatible routes ONLY. See
    module docstring for the exact precedence rules. Returns
    (user_id: int, error_response: None) on success, or
    (None, (jsonify(...), status)) -- the caller returns error_response
    immediately as-is.
    """
    verified_identity = get_jwt_identity()  # requires @jwt_required(optional=True)
    if verified_identity is not None:
        return int(verified_identity), None

    if _asknow_jwt_enforced():
        return None, (jsonify({"msg": "Missing Authorization Header"}), 401)

    # Flag OFF, no JWT -- build 48's exact pre-hardening contract.
    data = request.get_json(silent=True) or {}
    raw_user_id = data.get("user_id") or request.args.get("user_id")
    if not raw_user_id:
        return None, (jsonify({"error": "user_id missing"}), 400)
    try:
        return int(raw_user_id), None
    except (TypeError, ValueError):
        return None, (jsonify({"error": "user_id must be int"}), 400)


# ----------------------------------------------------------
# 1) FREE QUESTION — 1/day
# ----------------------------------------------------------
@routes_chat.route("/api/chat/free", methods=["POST"])
@jwt_required(optional=True)
def chat_free():
    user_id, error = _resolve_gated_user_id()
    if error:
        return error

    data = request.get_json() or {}
    birth = data.get("birth", {})
    question = data.get("question", "").strip()

    if not question or not birth:
        return jsonify({"error": "Missing required fields"}), 400

    # Check free quota
    if not has_free_quota(user_id):
        return jsonify({
            "success": False,
            "message": "Free question already used today"
        }), 403

    # Use the free quota
    use_free_quota(user_id)

    # Get chat answer
    answer = chat_engine(birth, question)

    return jsonify({
        "success": True,
        "free_used": True,
        "answer": answer
    }), 200


# ----------------------------------------------------------
# 2) PAID PACK — deduct question
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack", methods=["POST"])
@jwt_required(optional=True)
def chat_pack():
    user_id, error = _resolve_gated_user_id()
    if error:
        return error

    data = request.get_json() or {}
    birth = data.get("birth", {})
    question = data.get("question", "").strip()

    if not question or not birth:
        return jsonify({"error": "Missing required fields"}), 400

    # Try to deduct one question
    result = deduct_question(user_id)

    if not result.get("success"):
        return jsonify(result), 403

    # Get chat answer
    answer = chat_engine(birth, question)

    return jsonify({
        "success": True,
        "remaining": result["remaining"],
        "answer": answer
    }), 200


# ----------------------------------------------------------
# 3) CREATE ₹51 ORDER
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack/order", methods=["POST"])
@jwt_required()
def chatpack_order():
    user_id = _authenticated_user_id()

    order = create_chatpack_order(user_id)
    return jsonify({"success": True, "order": order}), 200


# ----------------------------------------------------------
# 4) VERIFY PAYMENT
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack/verify", methods=["POST"])
@jwt_required()
def chatpack_verify():
    user_id = _authenticated_user_id()

    data = request.get_json() or {}
    order_id = data.get("order_id")
    payment_id = data.get("payment_id")
    # Trust Foundation Phase 0: now REQUIRED -- see
    # modules/services/chat_pack_service.py::verify_chatpack_payment()'s
    # own docstring. Without a real signature, nothing is verified and
    # nothing is credited.
    signature = data.get("razorpay_signature") or data.get("signature")

    if not order_id or not payment_id or not signature:
        return jsonify({
            "error": "Missing fields",
            "message": "order_id, payment_id, and razorpay_signature are all required.",
        }), 400

    try:
        result = verify_chatpack_payment(order_id, payment_id, signature, user_id)
    except ValueError as e:
        # Verification failure / order-not-found are legitimate,
        # structured business rejections -- never grant anything, never
        # 500 for a genuinely invalid/forged payment claim.
        return jsonify({"success": False, "error": str(e)}), 400

    return jsonify(result), 200


# ----------------------------------------------------------
# 5) PACK STATUS (Debug / Postman)
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack/status", methods=["GET"])
@jwt_required()
def chatpack_status():
    user_id = _authenticated_user_id()

    status = get_pack_status(user_id)
    return jsonify(status), 200


# ----------------------------------------------------------
# 6) FREE STATUS (Debug / Postman)
# ----------------------------------------------------------
@routes_chat.route("/api/chat/free/status", methods=["GET"])
@jwt_required()
def free_status():
    user_id = _authenticated_user_id()

    status = get_free_quota_status(user_id)
    return jsonify(status), 200

# ----------------------------------------------------------
# 7) REQUIREMENT EXTRACTOR (GPT-based)
# ----------------------------------------------------------
# Unchanged by Trust Foundation Phase 0: touches no per-user identity,
# credit, or financial state -- confirmed LOW severity, out of scope for
# this pass (Trust Foundation Audit, Section K).
@routes_chat.route("/requirements", methods=["POST"])
def chat_requirements():
    from modules.services.chat_requirement_engine import get_required_data

    data = request.get_json() or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({
            "success": False,
            "error": "Missing 'question'"
        }), 400

    try:
        requirements = get_required_data(question)

        print("\n🔥 REQUIREMENT ENGINE OUTPUT:")
        print(requirements)
        print("================================\n")

        return jsonify({
            "success": True,
            "requirements": requirements
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ----------------------------------------------------------
# 7) COMBINED CHAT STATUS  (FREE + PAID)
# ----------------------------------------------------------
@routes_chat.route("/api/chat/status", methods=["POST", "GET"])
@jwt_required(optional=True)
def chat_status():
    user_id, error = _resolve_gated_user_id()
    if error:
        return error

    from modules.services.free_quota_service import get_free_quota_status
    from modules.services.chat_pack_service import get_pack_status

    # ⭐ FREE STATUS
    free_status = get_free_quota_status(user_id)

    # ⭐ PACK STATUS
    pack_status = get_pack_status(user_id)

    return {
        "success": True,
        "free_available": (free_status["used_today"] == False),
        "remaining_tokens": pack_status.get("remaining", 0)
    }, 200

# ----------------------------------------------------------
# 8) DEBUG: RESET PACK QUESTIONS FOR A USER
# ----------------------------------------------------------
# Trust Foundation Phase 0: this endpoint could previously grant a free
# 8-question pack or reset any account's used-question count to zero,
# with zero authentication at all -- the single most severe finding in
# the Trust Foundation Audit. It remains a legitimate support/testing
# tool (its business logic is unchanged), but is now reachable ONLY by
# an authenticated admin -- same admin_required gate as every other
# admin-only route in this codebase. Still takes a target `user_id` in
# the body (an admin legitimately needs to act on any account for
# support purposes) -- what changed is WHO may call it, not what it does.
@routes_chat.route("/api/chat/debug/pack", methods=["POST"])
@admin_required
def debug_add_or_reset_pack():
    from extensions import db
    from modules.models_chat_pack import ChatPack
    from datetime import datetime

    data = request.get_json() or {}
    user_id = data.get("user_id")
    action = data.get("action", "").strip().lower()

    # Validate
    if not user_id:
        return jsonify({"success": False, "error": "user_id missing"}), 400
    if action not in ("add", "reset"):
        return jsonify({"success": False, "error": "action must be 'add' or 'reset'"}), 400

    try:
        uid = int(user_id)
    except ValueError:
        return jsonify({"success": False, "error": "user_id must be int"}), 400

    # -------------------------------------
    # 🔵 RESET PACKS
    # -------------------------------------
    if action == "reset":
        packs = ChatPack.query.filter_by(user_id=uid, status="success").all()
        if not packs:
            return jsonify({
                "success": True,
                "message": "No active packs found to reset.",
                "reset_count": 0,
            }), 200

        for p in packs:
            p.questions_used = 0  # reset to full
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "All packs reset successfully.",
            "reset_count": len(packs),
        }), 200

    # -------------------------------------
    # 🔵 ADD PACK (new 8 Questions pack)
    # -------------------------------------
    if action == "add":
        pack = ChatPack(
            user_id=uid,
            amount=51,
            questions_total=8,
            questions_used=0,
            status="success",
            razorpay_order_id="ADMIN_ADD",
            razorpay_payment_id="ADMIN_ADD",
            verified_at=datetime.utcnow(),
        )
        db.session.add(pack)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "New ChatPack (8 Q) added successfully.",
            "pack_id": pack.id,
        }), 200

# ----------------------------------------------------------
# 9) REWARD QUESTION — Watch Ads → +1 Question
# ----------------------------------------------------------
@routes_chat.route("/api/chat/reward", methods=["POST"])
@jwt_required(optional=True)
def chat_reward():
    """
    User watches 2 ads → we add 1 question.

    Rules:
    - If user has NO pack → create mini-pack (questions_total=1)
    - If user HAS a pack → increment questions_total by +1
      (questions_used remains SAME)
    """
    from modules.services.chat_pack_service import add_reward_question

    user_id, error = _resolve_gated_user_id()
    if error:
        return error

    result = add_reward_question(user_id)
    return jsonify(result), 200


@routes_chat.route("/api/chat/pack/google/verify", methods=["POST"])
@jwt_required()
def chatpack_google_verify():
    user_id = _authenticated_user_id()

    data = request.get_json() or {}
    product_id = data.get("product_id")
    purchase_token = data.get("purchase_token")

    if not product_id or not purchase_token:
        return jsonify({
            "success": False,
            "error": "Missing required fields"
        }), 400

    try:
        result = verify_google_chatpack(
            user_id=user_id,
            product_id=product_id,
            purchase_token=purchase_token
        )
        return jsonify(result), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500



# 🔁 BACKWARD COMPAT ALIAS (temporary safety net)
@routes_chat.route("/api/chatpack/verify", methods=["POST"])
@jwt_required()
def chatpack_verify_alias():
    user_id = _authenticated_user_id()

    data = request.get_json() or {}
    product_id = data.get("product_id")
    purchase_token = data.get("purchase_token")

    if not product_id or not purchase_token:
        return jsonify({
            "success": False,
            "error": "Missing required fields"
        }), 400

    result = verify_google_chatpack(
        user_id=user_id,
        product_id=product_id,
        purchase_token=purchase_token
    )
    return jsonify(result), 200
