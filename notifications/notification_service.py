# notifications/notification_service.py

from datetime import datetime
from extensions import db
from modules.auth.models import User
from notifications.notification_models import NotificationJob
from sqlalchemy import and_


# ================================================================
# 1) USER FILTERING LOGIC
# ================================================================
def get_recipients(audience: dict):
    """
    Converts audience filters into SQL queries.
    Returns list of User objects (with fcm_token).
    
    Audience example:
    {
        "mode": "mixed",
        "zodiac": ["aries"],
        "lagna": ["scorpio"],
        "age_group": ["young_adult"],
        "interest": ["love"],
        "subscription": ["monthly"]
    }
    """

    query = User.query.filter(User.fcm_token.isnot(None))

    # -------------------- ZODIAC filter --------------------
    zodiac = audience.get("zodiac")
    if zodiac:
        query = query.filter(User.zodiac.in_(zodiac))

    # -------------------- LAGNA filter --------------------
    lagna = audience.get("lagna")
    if lagna:
        query = query.filter(User.ascendant.in_(lagna))

    # -------------------- AGE GROUP filter --------------------
    age_group = audience.get("age_group")
    if age_group:
        query = query.filter(User.age_group.in_(age_group))

    # -------------------- INTEREST filter --------------------
    interest = audience.get("interest")
    if interest:
        query = query.filter(User.primary_interest.in_(interest))

    # -------------------- SUBSCRIPTION filter --------------------
    subscription = audience.get("subscription")
    if subscription:
        query = query.filter(User.subscription_status.in_(subscription))

    # -------------------- LANGUAGE filter --------------------
    language = audience.get("language")
    if language:
        query = query.filter(User.language.in_(language))

    # -------------------- ALL USERS --------------------
    if audience.get("mode") == "all":
        return User.query.filter(User.fcm_token.isnot(None)).all()

    return query.all()


# ================================================================
# 2) SEND ONE JOB (no celery for now — hybrid mode)
# ================================================================
def send_job_now(job: NotificationJob, fcm_sender):
    """
    Process one notification job (send immediately).
    fcm_sender: a function injected from notification_fcm.py
    """

    recipients = get_recipients(job.audience)
    tokens = [u.fcm_token for u in recipients if u.fcm_token]

    success = 0
    failed = 0

    for token in tokens:
        ok = fcm_sender(
            token=token,
            title=job.title,
            body=job.body,
            data=job.payload
        )
        if ok:
            success += 1
        else:
            failed += 1

    job.total_recipients = len(tokens)
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
