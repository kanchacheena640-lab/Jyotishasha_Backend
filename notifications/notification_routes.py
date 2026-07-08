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
