# notifications/notification_service.py
#
# Admin/Marketing broadcast infrastructure ONLY (NotificationJob queue).
# Event-driven notifications (festivals, vrat, transit, dasha, ekadashi...)
# are generated exclusively by services.event_scheduler.run_daily_event_job()
# via notification_builder.py -- nothing here should produce or process
# an event notification. See auto_job_creator.py / daily_runner.py removal
# in the v1.0 freeze for why that split matters.

import logging
from datetime import datetime, timezone
from extensions import db
from notifications.notification_models import NotificationJob, NotificationLog
from sqlalchemy import and_, cast
from sqlalchemy.dialects.postgresql import JSONB

# Phase 4D -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from notifications.
from modules.activity_events.service import record_event

_activity_events_logger = logging.getLogger("activity_events")


def _emit_notification_events(*, created_rows, job):
    """Phase 4D -- observational only, called ONLY after send_job_now()'s
    own end-of-job db.session.commit() has already succeeded.
    `created_rows` is the list of (UserNotification instance) actually
    included in that commit -- every entry here, by this pipeline's own
    construction (see send_job_now()), corresponds to a real, successful
    FCM send, so both notification_created AND notification_sent are
    emitted for each one. Never called for a recipient whose send failed
    or was skipped by dedup -- no row exists for those, nothing to
    attach an event to. Each row's own emission is independently wrapped
    so one failure never prevents the rest of the batch from being
    attempted."""
    for user_notification in created_rows:
        entity_id = str(user_notification.id)
        # created_at is a naive-UTC DateTime (db.func.current_timestamp()
        # default) -- made explicitly timezone-aware ONLY for this
        # analytics call, never mutating the persisted business column.
        occurred_at = (
            user_notification.created_at.replace(tzinfo=timezone.utc)
            if user_notification.created_at is not None
            else datetime.now(timezone.utc)
        )
        notification_context = {"notification_id": entity_id, "campaign_id": str(job.id), "slot": "general"}

        try:
            record_event(
                event_name="notification_created",
                occurred_at=occurred_at,
                platform="backend_internal",
                source="notification_job",
                firebase_uid=None,
                profile_id=user_notification.user_id,
                entity_type="notification",
                entity_id=entity_id,
                properties={"notification_type": job.type, "target_scope": "broadcast"},
                notification_context=notification_context,
                dedupe_key=f"notification_created:{entity_id}",
            )
        except Exception:
            _activity_events_logger.warning(
                "notification_service: unexpected error emitting notification_created "
                "for UserNotification.id=%s (swallowed -- the notification result "
                "already decided is unaffected)",
                entity_id, exc_info=True,
            )

        try:
            record_event(
                event_name="notification_sent",
                occurred_at=datetime.now(timezone.utc),
                platform="backend_internal",
                source="notification_job",
                firebase_uid=None,
                profile_id=user_notification.user_id,
                entity_type="notification",
                entity_id=entity_id,
                properties={},
                notification_context=notification_context,
                dedupe_key=f"notification_sent:{entity_id}",
            )
        except Exception:
            _activity_events_logger.warning(
                "notification_service: unexpected error emitting notification_sent "
                "for UserNotification.id=%s (swallowed -- the notification result "
                "already decided is unaffected)",
                entity_id, exc_info=True,
            )


# ================================================================
# 1) USER FILTERING LOGIC
# ================================================================
def get_recipients(audience: dict):
    from modules.models_user import AppUser

    """
    FINAL SYSTEM:
    Only app_users (fully migrated system)
    """

    query = AppUser.query.filter(AppUser.fcm_token.isnot(None))

    # -------------------- FILTERS --------------------

    # ZODIAC (moon_sign)
    zodiac = audience.get("zodiac")
    if zodiac:
        query = query.filter(AppUser.moon_sign.in_(zodiac))

    # LAGNA
    lagna = audience.get("lagna")
    if lagna:
        query = query.filter(AppUser.lagna.in_(lagna))

    # SUBSCRIPTION
    subscription = audience.get("subscription")
    if subscription:
        query = query.filter(AppUser.subscription.in_(subscription))

    # -------------------- ALL USERS --------------------
    return query.all()

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

    # Phase 4D -- only the UserNotification rows actually staged for
    # THIS commit, in this exact call. NotificationLog-only rows (no
    # UserNotification, because the independent existing_notif dedup
    # gate below skipped it) are never added here -- per the locked
    # design, that case emits nothing.
    created_user_notifications = []

    for u in recipients:
        if not u.fcm_token:
            continue

        # 🔥 DUPLICATE CHECK (SEND LEVEL)
        # Phase 4D.1 -- NotificationLog.event_id is String(100); every
        # other producer in this codebase (event_scheduler.py,
        # notification_routes.py's admin_test_send_notification()) already
        # writes a string there. This query previously compared it
        # against job.id, a raw Python int -- PostgreSQL has no
        # varchar=integer comparison operator, so this raised
        # unconditionally on every call (confirmed: the matching INSERT
        # below happened to still succeed, since Postgres allows an
        # implicit int->varchar assignment cast on INSERT but not on a
        # WHERE comparison -- so any already-persisted row already holds
        # str(job.id)'s own text form; using the same str(job.id) here
        # is the minimal, consistent fix, not a new representation).
        existing_log = NotificationLog.query.filter_by(
            user_id=u.id,
            event_id=str(job.id),
            slot="general"
        ).first()

        if existing_log:
            continue

        # 🔤 Language resolution
        lang = getattr(u, "language", "en")

        if lang == "hi":
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
            # Phase 4D.1 -- str(job.id), matching the query fix above and
            # every other producer's existing string convention for this
            # column. Same value this INSERT already stored before this
            # fix (Postgres's own implicit int->varchar cast), now made
            # explicit so the later comparison above can actually match it.
            log = NotificationLog(
                user_id=u.id,
                event_id=str(job.id),
                slot="general"
            )
            db.session.add(log)

            # 🔥 2. SAVE USER NOTIFICATION (UI) WITH DUPLICATE CHECK
            # Phase 4D.2 -- UserNotification.data is a plain PostgreSQL
            # JSON column (not JSONB); JSON has no equality operator at
            # all, so the original `data=job.payload` filter_by() raised
            # unconditionally on every successful send (confirmed by an
            # isolated read-only repro). Cast BOTH sides to JSONB only
            # for this one comparison -- no column type change, no
            # migration -- which restores real JSON *value* equality
            # (confirmed empirically: two dicts with the same
            # keys/values in a different insertion order still compare
            # equal under jsonb, unlike a plain text/string comparison
            # would), matching this check's own original intent exactly.
            # Both sides are safely parameterized by SQLAlchemy's own
            # cast()/bind mechanism -- no raw SQL string interpolation.
            existing_notif = UserNotification.query.filter(
                UserNotification.user_id == u.id,
                cast(UserNotification.data, JSONB) == cast(job.payload, JSONB),
            ).first()

            if not existing_notif:
                notif = UserNotification(
                    user_id=u.id,
                    title=title,
                    body=body,
                    data=job.payload or {}   # 🔥 ADD THIS LINE
                )
                db.session.add(notif)
                created_user_notifications.append(notif)

        else:
            failed += 1

    # 🔥 FINAL JOB UPDATE
    job.total_recipients = success + failed
    job.mark_sent(success, failed)

    db.session.commit()

    # Phase 4D -- emitted only after the commit above has already
    # succeeded, so every row here is real and durable. Never allowed
    # to alter job/business state -- see _emit_notification_events()'s
    # own per-row isolation.
    _emit_notification_events(created_rows=created_user_notifications, job=job)

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
