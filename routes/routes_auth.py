# routes/routes_auth.py

from flask import Blueprint, request, jsonify
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from flask_jwt_extended import create_access_token
from firebase_admin import auth as firebase_auth


routes_auth = Blueprint("routes_auth", __name__)


# ----------------------------------------------------------
# REGISTER / LINK FIREBASE USER → BACKEND USER
# ----------------------------------------------------------
@routes_auth.route("/api/auth/register", methods=["POST"])
def register_user():
    # Bucket A -- Critical Fix #2. This endpoint previously trusted
    # firebase_uid directly from the request body, with no proof the
    # caller actually owns that Firebase identity -- independently
    # verified as exploitable (a forged UID could pre-create/claim a
    # User record for an identity the caller doesn't own). Fixed by
    # reusing the exact same Firebase verification pattern already
    # used by modules/auth/routes_profile.py::update_fcm_token() and
    # this file's own, just-fixed get_backend_token() -- Authorization:
    # Bearer <firebase_id_token> + firebase_auth.verify_id_token(). No
    # new authentication mechanism was introduced. Any firebase_uid the
    # client sends in the request body is now ignored entirely; the
    # UID used below always comes from the verified token.
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    id_token = auth_header.replace("Bearer ", "").strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception:
        return jsonify({"error": "Invalid or expired Firebase token"}), 401

    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        return jsonify({"error": "Invalid Firebase token"}), 401

    data = request.get_json() or {}

    phone = data.get("phone")
    email = data.get("email")
    name = data.get("name")

    # -----------------------------------------
    # STEP 1: LOOK UP BY firebase_uid (unchanged identity -- the
    # common case, exactly as before).
    # -----------------------------------------
    user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if user:
        # Bug fix: sync the latest name/email/provider onto the
        # already-linked row -- additive only, never touches
        # firebase_uid/id/any relation, so subscriptions/FKs are
        # completely unaffected.
        changed = False
        if name and user.name != name:
            user.name = name
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if user.provider != "firebase":
            user.provider = "firebase"
            changed = True
        if changed:
            db.session.commit()

        return jsonify({
            "success": True,
            "user_id": user.id,   # existing backend_user_id
            "new": False
        }), 200

    # -----------------------------------------
    # STEP 2: LOOK UP BY email. Firebase can issue a new uid for the
    # same person (re-registration, provider change, reinstall,
    # etc.) -- re-link the existing row to the newly-verified
    # firebase_uid instead of inserting a second row, which is
    # exactly what was hitting users.email's UNIQUE constraint
    # before this fix. Same user.id preserved, so every existing FK
    # (subscriptions, etc.) keeps pointing at the same row.
    # -----------------------------------------
    if email:
        existing_by_email = User.query.filter_by(email=email).first()
        if existing_by_email:
            old_firebase_uid = existing_by_email.firebase_uid
            existing_by_email.firebase_uid = firebase_uid
            if existing_by_email.provider != "firebase":
                existing_by_email.provider = "firebase"

            # Keep app_users in lockstep, in the SAME transaction as
            # the users update above. Without this, users.firebase_uid
            # and app_users.firebase_uid diverge for the same person,
            # breaking resolve_profile_id_from_account_user_id()'s
            # join (confirmed by prior verification). Both writes are
            # flushed and committed together by the single commit()
            # below -- if it fails, both roll back together; neither
            # is ever persisted alone.
            AppUser.query.filter_by(firebase_uid=old_firebase_uid).update(
                {"firebase_uid": firebase_uid}
            )

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise

            return jsonify({
                "success": True,
                "user_id": existing_by_email.id,   # SAME id -- no second account
                "new": False
            }), 200

    # -----------------------------------------
    # STEP 3: CREATE NEW USER (unchanged from before)
    # -----------------------------------------
    new_user = User(
        firebase_uid=firebase_uid,
        phone=phone,
        email=email,
        name=name,
        provider="firebase"
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "success": True,
        "user_id": new_user.id,   # new backend_user_id
        "new": True
    }), 200


# ----------------------------------------------------------
# ISSUE BACKEND JWT (IMPORTANT)
# ----------------------------------------------------------
@routes_auth.route("/api/auth/token", methods=["POST"])
def get_backend_token():
    # Bucket A -- Critical Fix #1. This endpoint previously trusted
    # firebase_uid directly from the request body, with no proof the
    # caller actually owns that Firebase identity -- independently
    # verified as exploitable (a forged UID minted a valid backend JWT
    # for any account). Fixed by reusing this repository's existing,
    # already-proven Firebase verification pattern -- Authorization:
    # Bearer <firebase_id_token> + firebase_auth.verify_id_token() --
    # the same mechanism already used by
    # modules/auth/routes_profile.py::update_fcm_token(). No new
    # authentication mechanism was introduced. Any firebase_uid the
    # client sends in the request body is now ignored entirely; the
    # UID used below always comes from the verified token.
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    id_token = auth_header.replace("Bearer ", "").strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception:
        return jsonify({"error": "Invalid or expired Firebase token"}), 401

    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        return jsonify({"error": "Invalid Firebase token"}), 401

    user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if not user:
        return jsonify({"error": "user not found"}), 404

    # 🔥 MAIN FIX -- unchanged: JWT generation, identity, and response
    # schema are exactly as before.
    token = create_access_token(identity=str(user.id))

    return jsonify({
        "token": token,
        "user_id": user.id
    })