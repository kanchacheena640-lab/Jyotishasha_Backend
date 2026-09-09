# notifications/user_notification_routes.py

from flask import Blueprint, request, jsonify
from modules.auth.models import User
from modules.models_user import AppUser
from extensions import db
from notifications.notification_models import UserNotification
from notifications import campaign_bell_service
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta


user_notification_bp = Blueprint(
    "user_notifications",
    __name__,
    url_prefix="/api/user-notifications"
)

def get_app_user_id():
    identity = get_jwt_identity()

    # 🔹 Step 1: Auth user
    user = db.session.get(User, int(identity))
    if not user:
        return None

    # 🔹 Step 2: Map to AppUser
    app_user = db.session.query(AppUser)\
        .filter_by(firebase_uid=user.firebase_uid)\
        .first()

    if not app_user:
        return None

    return app_user.id

# ===============================
# 1. UNREAD COUNT
# ===============================
@user_notification_bp.route("/unread-count", methods=["GET"])
@jwt_required()
def get_unread_count():
    user_id = get_app_user_id()

    if not user_id:
        return jsonify({"error": "User not found"}), 404

    # N6 -- unread_count() is the unified A/B + Campaign C count. Campaign
    # C never lives in UserNotification (see campaign_bell_models.py's
    # docstring for why), so merging it here is the ONLY place its
    # existence can affect this badge -- read-only aggregation, no write
    # to either table, no change to A/B's own is_read/expires_at logic.
    count = campaign_bell_service.unread_count(user_id)

    return jsonify({"unread_count": count})


# ===============================
# 2. GET LIST
# ===============================
@user_notification_bp.route("", methods=["GET"])
@jwt_required()
def get_notifications():
    user_id = get_app_user_id()

    if not user_id:
        return jsonify({"error": "User not found"}), 404

    # N6 -- unified list (A/B UserNotification rows + Campaign C Bell
    # items), merged at read time only. Each item carries "source"
    # ("AB" or "ADMIN_CAMPAIGN") so a client can distinguish them; the
    # A/B item shape itself (id/title/body/data/is_read/created_at) is
    # byte-identical to what this endpoint returned before N6.
    items = campaign_bell_service.list_unified_bell(user_id)
    return jsonify(items)


# ===============================
# 3. MARK SINGLE READ
# ===============================
@user_notification_bp.route("/mark-read", methods=["POST"])
@jwt_required()
def mark_read():
    user_id = get_app_user_id()

    data = request.json or {}
    item_id = data.get("item_id")
    notif_id = data.get("notification_id")

    if item_id:
        # N6 -- unified composite id ("ab:<int>" / "cc:<uuid>").
        ok = campaign_bell_service.mark_read(user_id, item_id)
        if not ok:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"success": True})

    # Legacy path -- unchanged from pre-N6 behavior, kept for any client
    # still posting a raw UserNotification id.
    if not notif_id:
        return jsonify({"error": "notification_id required"}), 400

    notif = db.session.query(UserNotification)\
        .filter_by(id=notif_id, user_id=user_id)\
        .first()

    if not notif:
        return jsonify({"error": "Not found"}), 404

    if not notif.is_read:
        notif.is_read = True
        db.session.commit()

    return jsonify({"success": True})

# ===============================
# 4. MARK ALL READ
# ===============================
@user_notification_bp.route("/mark-all-read", methods=["POST"])
@jwt_required()
def mark_all_read():
    user_id = get_app_user_id()
    if not user_id:
        return jsonify({"error": "User not found"}), 404

    # N6 -- now marks both A/B UserNotification rows AND Campaign C Bell
    # items read; A/B's own update (is_read=True for that user's unread
    # rows) is unchanged from pre-N6 behavior.
    campaign_bell_service.mark_all_read(user_id)

    return jsonify({"success": True})


# ===============================
# 5. DISMISS ONE (N6 -- new; did not exist before N6)
# ===============================
@user_notification_bp.route("/dismiss", methods=["POST"])
@jwt_required()
def dismiss_one():
    """Presentation-only removal from the tray -- never mutates
    campaign/execution/delivery/attempt/attribution history, and for an
    A/B row never mutates is_read/expires_at/data, only the new
    dismissed_at column."""
    user_id = get_app_user_id()
    if not user_id:
        return jsonify({"error": "User not found"}), 404
    data = request.json or {}
    item_id = data.get("item_id")
    if not item_id:
        return jsonify({"error": "item_id required"}), 400
    ok = campaign_bell_service.dismiss_one(user_id, item_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


# ===============================
# 6. CLEAR ALL (N6 -- new; did not exist before N6)
# ===============================
@user_notification_bp.route("/clear", methods=["POST"])
@jwt_required()
def clear_all():
    """Presentation-only: dismisses every currently-visible item (both
    sources) for this user. Never deletes a row, never affects A/B's
    push-budget accounting or retention trim (neither reads
    dismissed_at)."""
    user_id = get_app_user_id()
    if not user_id:
        return jsonify({"error": "User not found"}), 404
    campaign_bell_service.clear_all(user_id)
    return jsonify({"success": True})
