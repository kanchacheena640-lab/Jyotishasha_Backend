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
import logging
import os
import time
from datetime import datetime, timezone

from openai import APITimeoutError

from modules.services.chatpack_google_verify import verify_google_chatpack
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

# Reused, not reimplemented -- the same admin allowlist gate already
# proven by notifications/notification_routes.py and routes/admin_orders.py.
from notifications.notification_routes import admin_required

from extensions import db

# Phase 4E -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from routes.
from modules.activity_events.service import record_event

# Services
from modules.services.chat_engine import chat_engine
from modules.services.asknow_intent_service import record_intent_history
from modules.services.free_quota_service import (
    has_free_quota,
    use_free_quota,
    restore_free_quota,
    get_free_quota_status,
)
from modules.services.chat_pack_service import (
    create_chatpack_order,
    verify_chatpack_payment,
    deduct_question,
    restore_question,
    get_pack_status,
)

routes_chat = Blueprint("routes_chat", __name__)

_activity_events_logger = logging.getLogger("activity_events")


def _emit_asknow_event(*, event_name, source, latency_ms=None, failure_reason=None):
    """Phase 4E -- observational only. Called ONLY after the relevant
    business state for this event has already been durably reached:
    asknow_question_submitted after use_free_quota()/deduct_question()
    already committed; asknow_answer_delivered after chat_engine()
    already returned successfully; asknow_answer_failed after the
    existing credit-compensation attempt has already run. Never passed
    the raw question, birth data, generated answer, or any exception
    object -- only pre-classified, already-safe scalars (source is
    "free"/"pack"; failure_reason, if given, is already reduced to
    "timeout"/"unknown" by the caller). No truthful durable per-question
    entity/identity/session/correlation exists for Ask Now (Phase 4E
    audit) -- all left None/omitted rather than fabricated. This
    function's entire body is wrapped in try/except so an analytics
    failure can never propagate into chat_free()/chat_pack(), never
    alter credit state, and never affect the HTTP response."""
    try:
        properties = {"source": source}
        if latency_ms is not None:
            properties["latency_ms"] = latency_ms
        if failure_reason is not None:
            properties["failure_reason"] = failure_reason

        record_event(
            event_name=event_name,
            occurred_at=datetime.now(timezone.utc),
            platform="backend_internal",
            source="asknow_chat",
            firebase_uid=None,
            profile_id=None,
            entity_type=None,
            entity_id=None,
            correlation_id=None,
            session_id=None,
            properties=properties,
            dedupe_key=None,
        )
    except Exception:
        _activity_events_logger.warning(
            "routes_chat: unexpected error emitting %s (swallowed -- "
            "the Ask Now business result already decided is unaffected)",
            event_name, exc_info=True,
        )


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

    # Ask Now Credit Safety: consume-first is kept (matches every other
    # route in this file, and avoids reserving-then-generating races
    # this codebase has no infrastructure for) -- what changes is that a
    # generation failure AFTER this point is no longer silently
    # unhandled. previous_last_used_date is exactly what
    # restore_free_quota() needs to undo THIS call, and nothing else.
    try:
        _, previous_last_used_date = use_free_quota(user_id)
    except Exception:
        current_app.logger.exception(
            "chat_free: failed to consume free quota (user_id=%s)", user_id
        )
        # Phase 4E LOCKED DECISION: consumption itself never durably
        # committed, so "submission" never truthfully happened here --
        # no Ask Now activity event of any kind.
        return jsonify({
            "success": False,
            "error": "quota_error",
            "message": "Something went wrong. Please try again.",
        }), 502

    # Phase 4E -- asknow_question_submitted. Emitted only now, strictly
    # after use_free_quota()'s own commit above has already succeeded.
    _emit_asknow_event(event_name="asknow_question_submitted", source="free")

    # Get chat answer. chat_engine() already converts an OpenAI-side
    # failure into a textual fallback answer (never raises for that) --
    # an exception escaping from here means kundali/transit generation
    # itself failed, i.e. no valid answer can be returned under the
    # existing contract. That, and only that, is compensated.
    generation_started_at = time.monotonic()
    try:
        answer = chat_engine(birth, question)
    except Exception as exc:
        db.session.rollback()
        try:
            restore_free_quota(user_id, previous_last_used_date)
        except Exception:
            current_app.logger.exception(
                "chat_free: CRITICAL -- failed to restore free quota after "
                "generation failure (user_id=%s)", user_id
            )
        else:
            current_app.logger.warning(
                "chat_free: generation failed after consuming free quota; "
                "quota restored (user_id=%s)", user_id
            )
        # Phase 4E -- asknow_answer_failed. Emitted only after the
        # compensation attempt above (successful or not -- the failure
        # itself already happened either way). Only the exception's own
        # TYPE is inspected -- never str(exc)/repr(exc)/a traceback.
        failure_reason = "timeout" if isinstance(exc, APITimeoutError) else "unknown"
        _emit_asknow_event(event_name="asknow_answer_failed", source="free", failure_reason=failure_reason)
        return jsonify({
            "success": False,
            "error": "generation_failed",
            "message": "We couldn't generate an answer right now. Please try again.",
        }), 502

    # Phase 4E -- asknow_answer_delivered. Emitted only after chat_engine()
    # has already returned successfully, before the HTTP response below.
    # latency_ms measures ONLY the chat_engine() call itself -- never
    # validation, credit deduction, or this emission/jsonify.
    latency_ms = int((time.monotonic() - generation_started_at) * 1000)
    _emit_asknow_event(event_name="asknow_answer_delivered", source="free", latency_ms=latency_ms)

    # Ask Now Improvement Batch (Objective 1/5): concern_category is
    # INTERNAL ONLY -- popped off before the API response is built (see
    # chat_engine()'s own docstring) and used solely to write one
    # question-level history row. record_intent_history() is itself
    # fully failure-isolated (its own separate DB session, catches and
    # swallows everything) -- it can never affect this response or the
    # already-finalized free-quota consumption above, and is a no-op if
    # classification did not succeed for this question.
    concern_category = answer.pop("concern_category", None)
    record_intent_history(user_id=user_id, concern_category=concern_category, source="free")

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
    try:
        result = deduct_question(user_id)
    except Exception:
        current_app.logger.exception(
            "chat_pack: failed to deduct question (user_id=%s)", user_id
        )
        return jsonify({
            "success": False,
            "error": "quota_error",
            "message": "Something went wrong. Please try again.",
        }), 502

    if not result.get("success"):
        # No active/remaining pack -- deduct_question() never committed
        # anything for this attempt, so submission never truthfully
        # happened -- no Ask Now activity event.
        return jsonify(result), 403

    # Phase 4E -- asknow_question_submitted. Emitted only now, strictly
    # after deduct_question() returned success=True (its own commit
    # above has already succeeded).
    _emit_asknow_event(event_name="asknow_question_submitted", source="pack")

    # Ask Now Credit Safety: same posture as chat_free() above -- a
    # generation failure past this point restores exactly the one
    # question this request just debited, from the exact pack row
    # deduct_question() debited (result["pack_id"]), never a full
    # pack reset and never any other pack row.
    generation_started_at = time.monotonic()
    try:
        answer = chat_engine(birth, question)
    except Exception as exc:
        db.session.rollback()
        try:
            restore_question(user_id, result["pack_id"])
        except Exception:
            current_app.logger.exception(
                "chat_pack: CRITICAL -- failed to restore pack question after "
                "generation failure (user_id=%s, pack_id=%s)",
                user_id, result["pack_id"],
            )
        else:
            current_app.logger.warning(
                "chat_pack: generation failed after consuming a pack question; "
                "question restored (user_id=%s, pack_id=%s)",
                user_id, result["pack_id"],
            )
        # Phase 4E -- asknow_answer_failed. Emitted only after the
        # compensation attempt above. Only the exception's own TYPE is
        # inspected -- never str(exc)/repr(exc)/a traceback.
        failure_reason = "timeout" if isinstance(exc, APITimeoutError) else "unknown"
        _emit_asknow_event(event_name="asknow_answer_failed", source="pack", failure_reason=failure_reason)
        return jsonify({
            "success": False,
            "error": "generation_failed",
            "message": "We couldn't generate an answer right now. Please try again.",
        }), 502

    # Phase 4E -- asknow_answer_delivered. Emitted only after chat_engine()
    # has already returned successfully, before the HTTP response below.
    latency_ms = int((time.monotonic() - generation_started_at) * 1000)
    _emit_asknow_event(event_name="asknow_answer_delivered", source="pack", latency_ms=latency_ms)

    # Ask Now Improvement Batch (Objective 1/5) -- see chat_free()'s
    # identical comment above. Same failure-isolated persistence, "pack"
    # source label.
    concern_category = answer.pop("concern_category", None)
    record_intent_history(user_id=user_id, concern_category=concern_category, source="pack")

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
