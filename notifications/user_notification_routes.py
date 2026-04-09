# notifications/user_notification_routes.py

from flask import Blueprint, request, jsonify
from extensions import db
from notifications.notification_models import UserNotification
from flask_jwt_extended import jwt_required, get_jwt_identity

user_notification_bp = Blueprint(
    "user_notifications",
    __name__,
    url_prefix="/api/user-notifications"
)


# ===============================
# 1. UNREAD COUNT
# ===============================
@user_notification_bp.route("/unread-count", methods=["GET"])
@jwt_required()
def get_unread_count():
    user_id = get_jwt_identity()

    count = db.session.query(UserNotification)\
        .filter_by(user_id=user_id, is_read=False)\
        .count()

    return jsonify({"unread_count": count})


# ===============================
# 2. GET LIST
# ===============================
@user_notification_bp.route("", methods=["GET"])
@jwt_required()
def get_notifications():
    user_id = get_jwt_identity()

    notifications = db.session.query(UserNotification)\
        .filter_by(user_id=user_id)\
        .order_by(UserNotification.created_at.desc())\
        .limit(50)\
        .all()

    return jsonify([
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None
        }
        for n in notifications
    ])


# ===============================
# 3. MARK SINGLE READ
# ===============================
@user_notification_bp.route("/mark-read", methods=["POST"])
@jwt_required()
def mark_read():
    user_id = get_jwt_identity()
    data = request.json or {}

    notif_id = data.get("notification_id")

    if not notif_id:
        return jsonify({"error": "notification_id required"}), 400

    notif = db.session.query(UserNotification)\
        .filter_by(id=notif_id, user_id=user_id)\
        .first()

    if notif:
        notif.is_read = True
        db.session.commit()

    return jsonify({"success": True})


# ===============================
# 4. MARK ALL READ
# ===============================
@user_notification_bp.route("/mark-all-read", methods=["POST"])
@jwt_required()
def mark_all_read():
    user_id = get_jwt_identity()

    db.session.query(UserNotification)\
        .filter_by(user_id=user_id, is_read=False)\
        .update({"is_read": True})

    db.session.commit()

    return jsonify({"success": True})