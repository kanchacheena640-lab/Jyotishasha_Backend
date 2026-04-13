# notifications/notification_service.py

from datetime import datetime
from extensions import db
from notifications.notification_models import NotificationJob, NotificationLog
from sqlalchemy import and_


# ================================================================
# 1) USER FILTERING LOGIC
# ================================================================
def get_recipients(audience: dict):
    from modules.models_user import AppUser
    from modules.auth.models import User

    """
    Hybrid recipients with filters:
    - app_users (priority)
    - users (fallback)
    """

    # -------------------- NEW SYSTEM --------------------
    app_query = AppUser.query.filter(AppUser.fcm_token.isnot(None))

    # -------------------- OLD SYSTEM --------------------
    user_query = User.query.filter(User.fcm_token.isnot(None))

    # -------------------- APPLY FILTERS --------------------

    # ZODIAC
    zodiac = audience.get("zodiac")
    if zodiac:
        user_query = user_query.filter(User.zodiac.in_(zodiac))
        app_query = app_query.filter(AppUser.moon_sign.in_(zodiac))  # mapping

    # LAGNA
    lagna = audience.get("lagna")
    if lagna:
        user_query = user_query.filter(User.ascendant.in_(lagna))
        app_query = app_query.filter(AppUser.lagna.in_(lagna))

    # SUBSCRIPTION
    subscription = audience.get("subscription")
    if subscription:
        user_query = user_query.filter(User.subscription_status.in_(subscription))
        app_query = app_query.filter(AppUser.subscription.in_(subscription))

    # LANGUAGE
    language = audience.get("language")
    if language:
        user_query = user_query.filter(User.language.in_(language))
        # app_users me अभी language नहीं है → skip

    # -------------------- FETCH --------------------
    app_users = app_query.all()
    legacy_users = user_query.all()

    all_users = []

    # 🔥 Add app_users first
    for u in app_users:
        all_users.append(u)

    # 🔥 Avoid duplicate (same firebase_uid)
    app_user_uids = {u.firebase_uid for u in app_users if u.firebase_uid}

    for u in legacy_users:
        if not u.firebase_uid or u.firebase_uid not in app_user_uids:
            all_users.append(u)

    return all_users

# ================================================================
# 2) SEND ONE JOB (no celery for now — hybrid mode)
# ================================================================
def send_job_now(job: NotificationJob, fcm_sender):
    """
    Process one notification job (send immediately).
    Hindi / English per-user supported.
    Duplicate-safe via notification_logs.
    User UI-safe via user_notifications (no duplicate).
    """

    from notifications.notification_models import UserNotification

    recipients = get_recipients(job.audience)

    success = 0
    failed = 0

    for u in recipients:
        if not u.fcm_token:
            continue

        # 🔥 DUPLICATE CHECK (SEND LEVEL)
        existing_log = NotificationLog.query.filter_by(
            user_id=u.id,
            event_id=job.id,
            slot="general"
        ).first()

        if existing_log:
            continue

        # 🔤 Language resolution
        if getattr(u, "language", None) == "hi":
            title = getattr(job, "title_hi", None) or job.title
            body = getattr(job, "body_hi", None) or job.body
        else:
            title = job.title
            body = job.body

        ok = fcm_sender(
            token=u.fcm_token,
            title=title,
            body=body,
            data=job.payload
        )

        if ok:
            success += 1

            # 🔥 1. SAVE LOG (BACKEND TRACKING)
            log = NotificationLog(
                user_id=u.id,
                event_id=job.id,
                slot="general"
            )
            db.session.add(log)

            # 🔥 2. SAVE USER NOTIFICATION (UI) WITH DUPLICATE CHECK
            existing_notif = UserNotification.query.filter_by(
                user_id=u.id,
                title=title,
                body=body
            ).first()

            if not existing_notif:
                notif = UserNotification(
                    user_id=u.id,
                    title=title,
                    body=body
                )
                db.session.add(notif)

        else:
            failed += 1

    # 🔥 FINAL JOB UPDATE
    job.total_recipients = success + failed
    job.mark_sent(success, failed)

    db.session.commit()

    return success, failed


# ================================================================
# 3) PROCESS ALL DUE JOBS (for cron or celery)
# ================================================================
def process_due_jobs(fcm_sender):
    """
    Called by:
    - Cron job (Render scheduler)
    - OR Celery later

    fcm_sender is injected (Dependency Injection)
    """

    now = datetime.utcnow()

    pending_jobs = NotificationJob.query.filter(
        NotificationJob.status == "pending",
        NotificationJob.scheduled_at <= now
    ).all()

    results = []

    for job in pending_jobs:
        job.mark_processing()
        db.session.commit()

        try:
            s, f = send_job_now(job, fcm_sender)
            results.append({"job_id": job.id, "sent": s, "failed": f})
        except Exception as e:
            job.mark_failed()
            db.session.commit()
            results.append({"job_id": job.id, "error": str(e)})

    return results
