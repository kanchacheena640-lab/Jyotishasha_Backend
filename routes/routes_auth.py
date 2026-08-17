# routes/routes_auth.py

from flask import Blueprint, request, jsonify
from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from firebase_admin import auth as firebase_auth

from modules.auth.account_deletion_service import (
    AccountDeletionError,
    clear_pending_firebase_marker,
    delete_account_data,
    resolve_firebase_identity,
)
from modules.auth.firebase_cleanup_service import (
    FirebaseCleanupError,
    cleanup_firebase_account,
)


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


# ----------------------------------------------------------
# DELETE ACCOUNT -- D2 (auth boundary) + D3 (Firebase Auth/Firestore
# cleanup orchestration)
# ----------------------------------------------------------
@routes_auth.route("/api/auth/delete-account", methods=["POST"])
@jwt_required()
def delete_account():
    """
    Security model (D0.1 -> D2, unchanged by D3):
      1. @jwt_required() proves the caller holds a currently-valid
         backend session -- but a JWT alone is judged NOT sufficient
         authorization for an action this destructive/irreversible.
      2. A SECOND, independent, FRESH proof of Firebase identity is
         required on every call: the same "Authorization: Bearer
         <firebase_id_token>" + firebase_auth.verify_id_token() pattern
         already used by this file's own register_user()/
         get_backend_token() and by modules/auth/routes_profile.py::
         update_fcm_token() -- reused exactly as-is, not reimplemented.
         Carried in a dedicated header (X-Firebase-ID-Token) rather than
         Authorization, since that header is already spoken for by
         @jwt_required() on this specific route.
      3. The freshly-verified Firebase uid MUST match the JWT-resolved
         account's OWN firebase_uid -- proven identity binding, not two
         independent, unrelated checks. A caller who is validly logged
         in as User A can never supply User B's Firebase token to
         delete User B's data: the mismatch is rejected before
         resolve_firebase_identity() is ever called.
      4. (S1 security fix) Step 3's cross-check is now UNCONDITIONAL.
         If the JWT's own `users` row no longer exists (a stale JWT --
         e.g. from an account already deleted, by anyone, in a prior
         call), the request is rejected outright (401, "stale_session")
         before the Firebase token is even verified. Previously this
         case skipped the cross-check entirely and let the Firebase
         token's own verified uid become the deletion target unchecked
         -- reproduced locally as a real cross-account deletion path
         (any stale-but-unexpired JWT + a genuinely fresh Firebase token
         for a completely different, still-existing account) and closed
         here. This costs no legitimate capability: `/api/auth/token`,
         the only way this app's own client ever obtains a JWT for this
         route, already requires a `users` row to exist and 404s
         otherwise -- so no genuinely fresh JWT can ever be minted for
         an identity whose `users` row is already gone.

    The deletion TARGET is derived exclusively from steps 1-3 above.
    The request body/query string are never read for identity at any
    point in this function -- there is nothing here for a client to
    override even if it tried.

    No raw Firebase token or personal profile content is ever logged --
    only structured, non-sensitive outcome data (counts, booleans).

    D3 orchestration (full A-E sequence, DB deletion and Firebase
    deletion cannot share one ACID transaction -- see
    modules/auth/firebase_cleanup_service.py's own docstring for why
    this is safe to run as two separate steps):
      A/B. Fresh Firebase identity proof + server-verified uid -- steps
           1-3 above, unchanged.
      C. delete_account_data() -- D1's DB cleanup. Always attempted
         first; a failure here aborts the whole request (500) with
         nothing changed anywhere, exactly as D2 already behaved.
      D/E. cleanup_firebase_account() -- Firestore cleanup then Auth
         deletion LAST, unconditionally attempted after step C succeeds
         (including when step C found nothing to do, i.e.
         already_absent=True) -- this is required for retrying a PRIOR
         call's Firebase-side failure even once the DB side is already
         clean. A failure here does NOT turn the response into an
         error: the privacy-critical DB deletion already committed, so
         the client is told success=True with
         firebase_cleanup_status="pending" rather than a misleading
         5xx. The client currently has no distinct retry UI for this
         status (D4, not yet built) -- see the D3 report's own
         "remaining risks" section.
         Retryability of a "pending" result (S1-updated): step C always
         deletes the `users` row on a successful DB pass, independent of
         whether step D/E subsequently fails -- so the JWT used for the
         ORIGINAL call is never valid for a retry either way, S1 fix or
         not (see point 4 above; `/api/auth/token` already 404s once
         `users` is gone). A genuine retry therefore always requires the
         account holder to sign in again first -- Firebase sign-in,
         then this app's own /api/auth/register (re-creates a `users`
         row for the same firebase_uid if Firebase Auth still has the
         user, i.e. Auth deletion itself hasn't completed yet) and
         /api/auth/token (mints a fresh JWT for that row) -- before
         re-issuing this same request, exactly as this route's own
         reauthentication_required/stale_session errors already tell
         the client to do. Once that fresh JWT is presented, resolution
         proceeds exactly as a first call would: resolve_firebase_
         identity() picks up any still-anonymized AppUser rows pending
         Firebase cleanup under that same firebase_uid, and D/E
         complete the interrupted Firestore/Auth cleanup. This is
         retryable through this SAME endpoint -- it is not a stale-JWT
         replay, it is a fresh, independently re-authenticated call that
         happens to resolve to the same firebase_uid -- EXCEPT if Auth
         deletion itself already succeeded and only the bookkeeping step
         below failed, which is not user-facing-retryable but also
         touches no personal data (see clear_pending_firebase_marker()'s
         own docstring).
      Bookkeeping (best-effort, never affects the response): once
      Firebase cleanup succeeds AND this call anonymized (rather than
      hard-deleted) any profile, clear_pending_firebase_marker() clears
      the now-stale firebase_uid marker on those rows. A failure here
      is swallowed and logged only -- the marker holds no personal
      data, so its lingering presence is a cosmetic gap, never a
      privacy or correctness issue for the client.
    """
    try:
        users_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({
            "error": "invalid_identity",
            "message": "Could not resolve the authenticated account from this session.",
        }), 401

    # S1 SECURITY FIX -- this used to read "May legitimately be None --
    # a stale JWT for an account already deleted in a prior call. Not an
    # error by itself" and skipped the cross-check below entirely
    # whenever `user` was None. That was the exact vulnerability: a JWT
    # is only a bearer credential, cryptographically valid until its own
    # expiry regardless of whether its own `users` row still exists.
    # Once that row is gone, there is nothing left on our side to bind
    # the JWT to -- ANY caller still holding that JWT (not just its
    # original owner) could pair it with a genuinely fresh Firebase
    # token for a completely different, still-existing account, and the
    # skipped cross-check let that unrelated Firebase uid become the
    # deletion target unchecked. Reproduced locally (local DB only,
    # mocked Firebase) before this fix landed.
    #
    # Fixed invariant (S1 Gate 2): a delete-account request may proceed
    # ONLY if BOTH independently authenticated identities -- the backend
    # JWT and the freshly-verified Firebase token -- still resolve to
    # the SAME currently-valid `users` row. A missing `users` row is
    # therefore rejected OUTRIGHT below, before the Firebase token is
    # even verified -- never treated as "nothing to compare, fall
    # through" and never treated as an idempotent-deletion signal at
    # this authentication boundary (idempotency is D1's own concern,
    # once identity is already established -- see delete_account_data()).
    #
    # This does not remove any legitimate capability: `/api/auth/token`
    # (the only way this app's own client ever obtains a delete-account
    # JWT) already requires a `users` row to exist and 404s otherwise --
    # so a genuinely fresh JWT can never be minted for an identity whose
    # `users` row is already gone. The only JWT that could ever reach
    # this branch is a stale one issued before that row was deleted,
    # which by definition no longer identifies anyone real to bind
    # against. A stale JWT's own original owner already completed their
    # own deletion by definition (nothing left to protect for them); a
    # different caller holding it has no legitimate use for it either.
    user = User.query.get(users_id)
    if user is None:
        return jsonify({
            "error": "stale_session",
            "message": "Your session is no longer valid. Please sign in again.",
        }), 401

    firebase_token = request.headers.get("X-Firebase-ID-Token", "").strip()
    if not firebase_token:
        return jsonify({
            "error": "reauthentication_required",
            "message": "A fresh Firebase sign-in is required before deleting your account.",
        }), 401

    try:
        decoded = firebase_auth.verify_id_token(firebase_token)
    except Exception:
        return jsonify({
            "error": "invalid_reauthentication",
            "message": "Firebase re-authentication failed or has expired. Please sign in again.",
        }), 401

    presented_firebase_uid = decoded.get("uid")
    if not presented_firebase_uid:
        return jsonify({
            "error": "invalid_reauthentication",
            "message": "Firebase re-authentication failed or has expired. Please sign in again.",
        }), 401

    # Identity-binding cross-check -- unconditional now (S1): `user` is
    # guaranteed non-None by this point (see the stale-session rejection
    # above), so this always runs.
    if not user.firebase_uid or user.firebase_uid != presented_firebase_uid:
        return jsonify({
            "error": "identity_mismatch",
            "message": "The provided Firebase identity does not match the authenticated account.",
        }), 403

    resolved = resolve_firebase_identity(presented_firebase_uid)

    try:
        result = delete_account_data(resolved)
    except AccountDeletionError:
        return jsonify({
            "error": "deletion_failed",
            "message": "Account deletion failed. Nothing was changed. Please try again.",
        }), 500

    # D3 -- Firestore + Firebase Auth cleanup. Always attempted, even
    # when result.already_absent is True: that's precisely the shape a
    # RETRY of a prior call's Firebase-side-only failure takes (DB side
    # already clean, Firebase side still pending). See this function's
    # own docstring for the full ordering/retry contract.
    firebase_cleanup_status = "pending"
    try:
        cleanup_firebase_account(presented_firebase_uid)
        firebase_cleanup_status = "complete"

        if result.anonymized_profile_ids:
            try:
                clear_pending_firebase_marker(result.anonymized_profile_ids)
            except AccountDeletionError:
                # Best-effort bookkeeping only -- never surfaced to the
                # client. See clear_pending_firebase_marker()'s own
                # docstring for why this is safe to swallow.
                pass
    except FirebaseCleanupError:
        firebase_cleanup_status = "pending"

    return jsonify({
        "success": True,
        "already_deleted": result.already_absent,
        "hard_deleted_profile_count": len(result.hard_deleted_profile_ids),
        "anonymized_profile_count": len(result.anonymized_profile_ids),
        "firebase_cleanup_status": firebase_cleanup_status,
    }), 200