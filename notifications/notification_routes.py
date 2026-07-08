# notifications/notification_routes.py

import os
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from notifications.notification_models import NotificationJob
from notifications.notification_service import send_job_now
from notifications.notification_fcm import send_fcm

notification_bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")
admin_notification_bp = Blueprint(
    "admin_notifications", __name__, url_prefix="/api/admin/notifications"
)


# ---------------------------------------------------
# Admin authorization (reuses existing JWT auth)
# ---------------------------------------------------
def _admin_user_ids():
    raw = os.getenv("ADMIN_USER_IDS", "")
    return {uid.strip() for uid in raw.split(",") if uid.strip()}


def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        identity = get_jwt_identity()
        if str(identity) not in _admin_user_ids():
            return jsonify({"error": "Forbidden"}), 403
        return fn(*args, **kwargs)
    return wrapper


def _parse_datetime(value: str):
    """Parse ISO string to datetime, fallback to now."""
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.utcnow()


# ---------------------------------------------------
# Create a new notification job (from dashboard)
# ---------------------------------------------------
@notification_bp.route("", methods=["POST"])
@admin_required
def create_notification_job():
    data = request.get_json() or {}

    title = data.get("title")
    body = data.get("body")
    ntype = data.get("type", "custom")
    audience = data.get("audience") or {"mode": "all"}
    payload = data.get("payload") or {}
    scheduled_at_str = data.get("scheduled_at")  # ISO string from frontend

    if not title or not body:
        return jsonify({"error": "title and body are required"}), 400

    scheduled_at = _parse_datetime(scheduled_at_str)

    job = NotificationJob(
        title=title,
        body=body,
        type=ntype,
        audience=audience,
        payload=payload,
        scheduled_at=scheduled_at,
        status="pending",
    )
    db.session.add(job)
    db.session.commit()

    return jsonify({
        "message": "Notification job created",
        "job_id": job.id
    }), 201


# ---------------------------------------------------
# List notification jobs (for dashboard table)
# ---------------------------------------------------
@notification_bp.route("", methods=["GET"])
@admin_required
def list_notification_jobs():
    status = request.args.get("status")  # optional filter

    query = NotificationJob.query.order_by(NotificationJob.created_at.desc())

    if status:
        query = query.filter(NotificationJob.status == status)

    jobs = query.limit(100).all()

    result = []
    for j in jobs:
        result.append({
            "id": j.id,
            "title": j.title,
            "body": j.body,
            "type": j.type,
            "audience": j.audience,
            "payload": j.payload,
            "scheduled_at": j.scheduled_at.isoformat() if j.scheduled_at else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "status": j.status,
            "total_recipients": j.total_recipients,
            "success_count": j.success_count,
            "failure_count": j.failure_count,
        })

    return jsonify(result), 200


# ---------------------------------------------------
# Force send a job NOW (for testing / urgent push)
# ---------------------------------------------------
@notification_bp.route("/<int:job_id>/send-now", methods=["POST"])
@admin_required
def send_notification_now(job_id):
    try:
        job = NotificationJob.query.get(job_id)

        if not job:
            return jsonify({"error": "Job not found"}), 404

        # Mark time as now (optional)
        job.scheduled_at = datetime.utcnow()
        db.session.commit()

        try:
            success, failed = send_job_now(job, send_fcm)
        except Exception as e:
            print("❌ Send job error:", e)
            success, failed = 0, 0

        return jsonify({
            "message": "Notification processed",
            "job_id": job.id,
            "success": success,
            "failed": failed
        }), 200

    except Exception as e:
        print("❌ Route error:", e)
        return jsonify({"error": "Internal Server Error"}), 500


# ---------------------------------------------------
# PERMANENT ADMIN TEST ENDPOINT. Never touches production
# logic itself: it only calls
# notification_builder.get_user_notifications (Builder) and
# notification_engine.send_push_notification (Engine + FCM
# sender), the exact functions services/event_scheduler.py
# calls in production, plus the same UserNotification /
# NotificationLog persistence the scheduler writes.
#
# Two modes, chosen by whether title/body/data were supplied:
#   - Builder mode (event_id only): identical to a real
#     scheduler run for that one event/user, dedup included.
#   - Manual mode (title/body[/data] supplied): Builder is
#     skipped, but the Engine/FCM sender is not -- exact
#     values given are sent as-is. Dedup is intentionally
#     skipped in this mode (see below).
#
# Access is gated by @admin_required -- the same JWT +
# ADMIN_USER_IDS allowlist every other route in this file
# uses. No new auth mechanism, no role tiers: this codebase
# has a single flat admin allowlist, not separate Super
# Admin/Admin roles, so that one check is "admin" here.
# ---------------------------------------------------
@admin_notification_bp.route("/test-send", methods=["POST"])
@admin_required
def admin_test_send_notification():
    admin_identity = get_jwt_identity()

    from modules.models_user import AppUser
    from models import AstroEvent
    from services.notification_builder import get_user_notifications
    from services.notification_engine import send_push_notification
    from notifications.notification_models import UserNotification, NotificationLog

    payload = request.get_json() or {}
    user_id = payload.get("user_id")
    event_id = payload.get("event_id")
    manual_title = payload.get("title")
    manual_body = payload.get("body")
    manual_data = payload.get("data")

    # 🔐 AUDIT LOG: who fired this, and with what, before anything else runs.
    print(
        f"🔐 AUDIT admin_test_send_notification | admin={admin_identity} "
        f"user_id={user_id} event_id={event_id} "
        f"manual={'yes' if (manual_title or manual_body or manual_data) else 'no'}"
    )

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    user = AppUser.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not user.fcm_token:
        return jsonify({"error": "User has no fcm_token"}), 400

    manual_mode = bool(manual_title or manual_body or manual_data)
    log_event_id = None
    slot = "morning"

    if manual_mode:
        # Bypass ONLY the Builder -- Engine/FCM sender below is unchanged.
        if not manual_title or not manual_body:
            return jsonify({"error": "title and body are required in manual mode"}), 400

        final_title = manual_title
        final_body = manual_body
        final_data = manual_data or {}

    else:
        if not event_id:
            return jsonify({
                "error": "event_id is required when title/body/data are not supplied"
            }), 400

        event = AstroEvent.query.get(event_id)
        if not event:
            return jsonify({"error": "Event not found"}), 404

        # Same builder call event_scheduler.py makes for its personalized
        # loop, scoped to this one event so no other event triggers here.
        candidates = get_user_notifications(user, [event], [])

        match = next(
            (n for n in candidates
             if (n.get("data") or {}).get("event_id") == str(event.id)),
            None
        )

        if not match:
            return jsonify({
                "error": "Notification Builder produced nothing for this user/event combination"
            }), 422

        final_title = match.get("title")
        final_body = match.get("body")
        final_data = match.get("data", {})

        ntype = final_data.get("type", "general")
        log_event_id = f"{ntype}_{event.id}"

        # Same dedup rule the scheduler enforces (NotificationLog per user/event/slot).
        # Manual mode above deliberately never reaches this check.
        existing_log = NotificationLog.query.filter_by(
            user_id=user.id,
            event_id=log_event_id,
            slot=slot
        ).first()

        if existing_log:
            return jsonify({
                "error": "Already sent to this user for this event (production dedup active)",
                "hint": "Use a different event_id/user_id, or clear the matching NotificationLog row to resend."
            }), 409

    success = send_push_notification(
        token=user.fcm_token,
        title=final_title,
        body=final_body,
        data=final_data
    )

    if success:
        db.session.add(UserNotification(
            user_id=user.id,
            title=final_title,
            body=final_body,
            data=final_data,
            is_read=False
        ))

        # Manual-mode sends are not real event occurrences, so they must
        # never write into NotificationLog -- that ledger drives production
        # dedup, and a manual test row there could silently suppress a real
        # future send to this same user/event.
        if not manual_mode:
            db.session.add(NotificationLog(
                user_id=user.id,
                event_id=log_event_id,
                slot=slot
            ))

        db.session.commit()

    # 🔐 AUDIT LOG: outcome of the send, tied back to the admin who triggered it.
    print(
        f"🔐 AUDIT admin_test_send_notification RESULT | admin={admin_identity} "
        f"user_id={user_id} mode={'manual' if manual_mode else 'builder'} "
        f"success={success} title={final_title!r}"
    )

    return jsonify({
        "success": success,
        "mode": "manual" if manual_mode else "builder",
        "final_title": final_title,
        "final_body": final_body,
        "final_payload": final_data,
        "fcm_response": "sent" if success else "failed"
    }), (200 if success else 502)
